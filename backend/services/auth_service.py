"""Authentication service: JWT, password hashing, TOTP, token management."""

import asyncio
import hashlib
import os
import secrets
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Any

from dateutils import utcnow

import bcrypt
import jwt
import pyotp
from cryptography.fernet import Fernet
import base64

from config import settings


# --- Password hashing ---

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode(), password_hash.encode())


# Dummy hash for timing-attack protection (always run bcrypt even for unknown emails)
_DUMMY_HASH = hash_password("dummy-password-for-timing-safety")


def verify_password_safe(password: str, password_hash: str | None) -> bool:
    """Verify password, using dummy hash if no real hash exists (timing protection)."""
    if password_hash is None:
        verify_password(password, _DUMMY_HASH)
        return False
    return verify_password(password, password_hash)


# bcrypt mit 12 Runden rechnet rund 0.2 s. Direkt im async-Handler steht so lange
# der Event-Loop des Workers (K002). Eigener kleiner Pool statt asyncio.to_thread:
# der Standard-Pool trägt die yfinance- und DB-Aufrufe und soll nicht mit Hashes
# volllaufen; zwei Threads begrenzen zugleich die CPU-Last paralleler Logins.
_bcrypt_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="bcrypt")


async def hash_password_async(password: str) -> str:
    """hash_password ausserhalb des Event-Loops."""
    return await asyncio.get_running_loop().run_in_executor(_bcrypt_executor, hash_password, password)


async def verify_password_async(password: str, password_hash: str) -> bool:
    """verify_password ausserhalb des Event-Loops."""
    return await asyncio.get_running_loop().run_in_executor(
        _bcrypt_executor, verify_password, password, password_hash
    )


async def verify_password_safe_async(password: str, password_hash: str | None) -> bool:
    """verify_password_safe ausserhalb des Event-Loops (gleicher Timing-Schutz)."""
    return await asyncio.get_running_loop().run_in_executor(
        _bcrypt_executor, verify_password_safe, password, password_hash
    )


def _hash_backup_codes(codes: list[str]) -> list[str]:
    return [hash_backup_code(code) for code in codes]


async def hash_backup_codes_async(codes: list[str]) -> list[str]:
    """Hasht alle Backup-Codes in EINEM Thread-Aufruf (8 Hashes rechnen rund 1.5 s)."""
    return await asyncio.get_running_loop().run_in_executor(_bcrypt_executor, _hash_backup_codes, codes)


def _match_backup_code(normalized: str, candidates: list[tuple[uuid.UUID, str]]) -> uuid.UUID | None:
    for code_id, code_hash in candidates:
        if verify_password(normalized, code_hash):
            return code_id
    return None


# --- Session invalidation helpers ---

async def bump_token_version(db, user_id) -> None:
    """Atomically invalidate all outstanding access tokens of a user (no commit)."""
    from sqlalchemy import update
    from models.user import User
    await db.execute(
        update(User).where(User.id == user_id).values(token_version=User.token_version + 1)
    )


async def invalidate_reset_tokens(db, user_id) -> None:
    """Mark all open password-reset tokens of a user as used (no commit)."""
    from sqlalchemy import update
    from models.password_reset_token import PasswordResetToken
    await db.execute(
        update(PasswordResetToken)
        .where(PasswordResetToken.user_id == user_id, PasswordResetToken.used == False)
        .values(used=True)
    )


# --- JWT ---

ACCESS_TOKEN_EXPIRE_MINUTES = 15
REFRESH_TOKEN_EXPIRE_DAYS = 30


def create_access_token(user_id: str, email: str, token_version: int = 0) -> tuple[str, int]:
    """Returns (token, expires_in_seconds). ``tv`` binds the token to User.token_version."""
    now = utcnow()
    expires = now + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": user_id,
        "email": email,
        "iat": now,
        "exp": expires,
        "type": "access",
        "tv": token_version,
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm="HS256")
    return token, ACCESS_TOKEN_EXPIRE_MINUTES * 60


def decode_access_token(token: str) -> dict | None:
    """Decode and verify access token. Returns payload or None."""
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        if payload.get("type") != "access":
            return None
        return payload
    except jwt.ExpiredSignatureError:
        _enc_logger.debug("Access token expired")
        return None
    except jwt.InvalidTokenError as e:
        _enc_logger.debug(f"Invalid access token: {e}")
        return None


def create_refresh_token() -> tuple[str, str, datetime]:
    """Returns (raw_token, token_hash, expires_at)."""
    raw = secrets.token_urlsafe(48)
    hashed = hashlib.sha256(raw.encode()).hexdigest()
    expires_at = utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    return raw, hashed, expires_at


def hash_refresh_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode()).hexdigest()


# --- Encryption ---

import logging as _logging

_enc_logger = _logging.getLogger(__name__)

# Legacy key for migration fallback (loaded from env, not hardcoded)
_LEGACY_DEFAULT_KEY = os.environ.get("LEGACY_ENCRYPTION_KEY", "")


def _get_fernet() -> Fernet:
    key = settings.encryption_key
    try:
        return Fernet(key.encode() if isinstance(key, str) else key)
    except Exception as e:
        _enc_logger.debug(f"Key is not a valid Fernet key, trying raw material: {type(e).__name__}")
        # Key is not a valid Fernet key — try using it as raw 32-byte material
        raw = key.encode() if isinstance(key, str) else key
        key_bytes = base64.urlsafe_b64decode(raw) if len(raw) >= 44 else raw
        if len(key_bytes) < 32:
            raise ValueError(
                f"ENCRYPTION_KEY must be a valid Fernet key or at least 32 bytes of key material, "
                f"got {len(key_bytes)} bytes. Generate one with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
            )
        fernet_key = base64.urlsafe_b64encode(key_bytes[:32])
        return Fernet(fernet_key)


def _derive_legacy_fernet(raw_key: str) -> Fernet:
    """Derive Fernet key using pre-Batch-1 null-padding method."""
    padded = raw_key[:32].ljust(32, "0").encode()
    return Fernet(base64.urlsafe_b64encode(padded))


def _get_legacy_fernets() -> list[Fernet]:
    """Build list of legacy Fernet instances for migration fallback."""
    seen = set()
    legacy = []

    for raw_key in [settings.encryption_key, _LEGACY_DEFAULT_KEY]:
        # Ein leerer Schlüssel ergäbe 32 Nullen: ein öffentlich bekannter Fernet-Key,
        # mit dem jeder gültige Chiffrate erzeugen könnte (K152). Er steht nicht
        # in dieser Liste; siehe _null_key_fernet.
        if not raw_key:
            continue
        try:
            f = _derive_legacy_fernet(raw_key)
            # Deduplicate by the derived Fernet key material
            derived = base64.urlsafe_b64encode(raw_key[:32].ljust(32, "0").encode())
            if derived not in seen:
                seen.add(derived)
                legacy.append(f)
        except Exception as e:
            _enc_logger.debug(f"Could not derive legacy Fernet: {type(e).__name__}")

    return legacy


def _null_key_fernet() -> Fernet:
    """Fernet zum Schlüssel aus 32 Nullen, den ein leerer LEGACY_ENCRYPTION_KEY ergab.

    Der Schlüssel ist öffentlich bekannt: wer in eine verschlüsselte Spalte
    schreiben kann, erzeugt damit gültige Chiffrate (K152). Er dient nur noch
    dem Lesen von Altwerten, solange LEGACY_NULL_KEY_ENABLED nicht false ist.
    """
    return _derive_legacy_fernet("")


KEY_CURRENT = "current"
KEY_LEGACY = "legacy"
KEY_NULL = "null"


def decrypt_with_key_kind(encrypted: str, *, include_null_key: bool | None = None) -> tuple[str, str]:
    """Decrypt value and report which key opened it.

    Returns (decrypted_text, KEY_CURRENT | KEY_LEGACY | KEY_NULL). Order: current
    key, legacy keys, null key. ``include_null_key=None`` follows
    ``settings.legacy_null_key_enabled``; the re-encryption script passes True to
    find such values after the switch-off as well. Raises ValueError when no key
    opens the value.
    """
    data = encrypted.encode()

    # Try current key first
    try:
        return _get_fernet().decrypt(data).decode(), KEY_CURRENT
    except Exception as e:
        _enc_logger.debug(f"Current key decryption failed, trying legacy keys: {e}")

    # Try legacy keys
    for legacy_f in _get_legacy_fernets():
        try:
            return legacy_f.decrypt(data).decode(), KEY_LEGACY
        except Exception as e:
            _enc_logger.debug(f"Legacy key decryption attempt failed: {e}")
            continue

    if include_null_key is None:
        include_null_key = settings.legacy_null_key_enabled
    if include_null_key:
        try:
            return _null_key_fernet().decrypt(data).decode(), KEY_NULL
        except Exception as e:
            _enc_logger.debug(f"Null key decryption attempt failed: {e}")

    raise ValueError("Entschlüsselung fehlgeschlagen — weder aktueller noch Legacy-Key funktioniert")


def _decrypt_with_fallback(encrypted: str) -> tuple[str, bool]:
    """Decrypt value, trying current key then legacy keys.

    Returns (decrypted_text, needs_reencrypt).
    needs_reencrypt is True when a legacy key succeeded.
    """
    decrypted, kind = decrypt_with_key_kind(encrypted)
    if kind == KEY_NULL:
        # Ohne Klartext und ohne Chiffrat: die Zeile nennt nur den Umstand.
        _enc_logger.warning(
            "Value decrypted with the public null legacy key only. Re-encrypt with "
            "scripts/vr11_reencrypt_legacy_fields.py, then set LEGACY_NULL_KEY_ENABLED=false"
        )
    return decrypted, kind != KEY_CURRENT


def encrypt_totp_secret(secret: str) -> str:
    f = _get_fernet()
    return f.encrypt(secret.encode()).decode()


def decrypt_totp_secret(encrypted: str) -> str:
    decrypted, needs_reencrypt = _decrypt_with_fallback(encrypted)
    if needs_reencrypt:
        _enc_logger.info("TOTP secret mit Legacy-Key entschlüsselt — Re-Encryption nötig")
    return decrypted


def encrypt_value(value: str) -> str:
    """Encrypt a generic string value with Fernet."""
    f = _get_fernet()
    return f.encrypt(value.encode()).decode()


def decrypt_value(encrypted: str) -> str:
    """Decrypt a generic Fernet-encrypted string, with legacy key fallback."""
    decrypted, needs_reencrypt = _decrypt_with_fallback(encrypted)
    if needs_reencrypt:
        _enc_logger.info("Wert mit Legacy-Key entschlüsselt — Re-Encryption nötig")
    return decrypted


def generate_totp_secret() -> str:
    return pyotp.random_base32()


def verify_totp(secret: str, code: str) -> bool:
    totp = pyotp.TOTP(secret)
    return totp.verify(code, valid_window=1)


# Ein Code gilt für seinen Zeitschritt und die beiden Nachbarn, also höchstens
# 90 s. So lange muss die Markierung «verbraucht» mindestens leben.
_TOTP_STEP_MARK_TTL = 120


def match_totp_step(secret: str, code: str) -> int | None:
    """Zeitschritt, zu dem ``code`` passt (aktueller Schritt ±1), sonst None."""
    totp = pyotp.TOTP(secret)
    current = totp.timecode(datetime.now())
    for offset in (-1, 0, 1):
        if pyotp.utils.strings_equal(str(code), totp.generate_otp(current + offset)):
            return current + offset
    return None


def consume_totp_code(user_id: uuid.UUID, secret: str, code: str) -> bool:
    """Prüft einen TOTP-Code und verbraucht seinen Zeitschritt für diesen Nutzer.

    Derselbe Zeitschritt gilt kein zweites Mal (RFC 6238, Abschnitt 5.2): ein
    mitgelesener Code ist damit wertlos. Die Markierung ist ein Lock ohne
    Freigabe — atomar über alle Prozesse, ohne Redis prozesslokal (K089).
    """
    step = match_totp_step(secret, code)
    if step is None:
        return False
    from services import cache
    return cache.acquire_lock(f"totp_step:{user_id}:{step}", _TOTP_STEP_MARK_TTL)


# Zweiter Faktor: Versuche je Konto, nicht je IP. Das IP-Limit der Routen hält
# keinen Angreifer auf, der das Passwort kennt und die Adresse wechselt (K089).
MFA_MAX_FAILED_ATTEMPTS = 5
MFA_LOCK_SECONDS = 15 * 60


def _mfa_attempts_key(user_id: uuid.UUID) -> str:
    return f"mfa_attempts:{user_id}"


def reserve_mfa_attempt(user_id: uuid.UUID) -> bool:
    """Zählt einen Versuch am zweiten Faktor. False: der zweite Faktor ist gesperrt.

    Gezählt wird VOR der Prüfung: auch parallele Versuche erhalten zusammen nur
    das Budget. Ein Erfolg setzt den Zähler mit ``clear_mfa_attempts`` zurück. Ein
    gesperrter Versuch zählt nicht, die Sperre endet also 15 Minuten nach dem
    letzten gezählten Fehlversuch. Zwischen zwei Prozessen ist das Lesen und
    Schreiben nicht atomar; das Budget kann sich dadurch höchstens verdoppeln.
    """
    from services import cache
    key = _mfa_attempts_key(user_id)
    count = int(cache.get(key) or 0)
    if count >= MFA_MAX_FAILED_ATTEMPTS:
        return False
    cache.set(key, count + 1, ttl=MFA_LOCK_SECONDS)
    return True


def clear_mfa_attempts(user_id: uuid.UUID) -> None:
    """Setzt den Zähler nach einem gültigen zweiten Faktor zurück."""
    from services import cache
    cache.delete(_mfa_attempts_key(user_id))


def get_totp_uri(secret: str, email: str) -> str:
    totp = pyotp.TOTP(secret)
    return totp.provisioning_uri(name=email, issuer_name="OpenFolio")


def generate_backup_codes(count: int = 8) -> list[str]:
    codes = []
    for _ in range(count):
        part1 = secrets.token_hex(4).upper()
        part2 = secrets.token_hex(4).upper()
        codes.append(f"{part1}-{part2}")
    return codes


def hash_backup_code(code: str) -> str:
    """Hash a backup code for storage using bcrypt. Normalize: uppercase, strip whitespace."""
    normalized = code.strip().upper().replace("-", "")
    return hash_password(normalized)


async def verify_backup_code(db: Any, user_id: uuid.UUID, code: str) -> bool:
    """Verify and consume a backup code. Returns True if valid."""
    from sqlalchemy import select, update
    from models.backup_code import BackupCode

    normalized = code.strip().upper().replace("-", "")
    result = await db.execute(
        select(BackupCode.id, BackupCode.code_hash).where(
            BackupCode.user_id == user_id,
            BackupCode.used == False,
        )
    )
    candidates = [(row.id, row.code_hash) for row in result]
    if not candidates:
        return False
    # Alle offenen Codes in EINEM Thread-Aufruf prüfen (K002).
    code_id = await asyncio.get_running_loop().run_in_executor(
        _bcrypt_executor, _match_backup_code, normalized, candidates
    )
    if code_id is None:
        return False
    # Atomar entwerten: zwei parallele Logins bestehen beide die Prüfung oben, das
    # bedingte UPDATE lässt aber nur einen durch (K165).
    consumed = await db.execute(
        update(BackupCode)
        .where(BackupCode.id == code_id, BackupCode.used == False)
        .values(used=True, used_at=utcnow())
        .returning(BackupCode.id)
    )
    return consumed.scalar_one_or_none() is not None


# --- Password validation ---

_COMMON_PASSWORDS = frozenset({
    "password", "123456", "12345678", "qwerty", "abc123", "monkey", "master",
    "dragon", "111111", "baseball", "iloveyou", "trustno1", "sunshine",
    "letmein", "football", "shadow", "michael", "password1", "password123",
    "welcome", "admin123", "login", "starwars", "princess", "passw0rd",
    "batman", "access", "hello", "charlie", "donald", "654321", "987654321",
    "123123", "1q2w3e", "qwerty123", "1234567890", "password1234", "abcdef",
    "123abc", "p@ssw0rd", "admin", "root", "test", "guest", "changeme",
    "default", "openfolio", "portfolio", "finance", "trading", "invest",
    "bitcoin", "crypto", "12345", "123456789", "1234567", "qwertyuiop",
    "1q2w3e4r", "asdfghjkl", "password!", "letmein1", "welcome1", "secret",
    "computer", "internet", "database", "server", "security", "pa$$word",
    "mustang", "freedom", "whatever", "thunder", "ginger", "pepper",
    "killer", "hockey", "soccer", "ranger", "buster", "harley", "cookie",
    "peanut", "dallas", "sparky", "maggie", "chelsea", "diamond", "hunter",
    "bailey", "jasmine", "qwer1234", "1qaz2wsx", "zxcvbnm", "1234qwer",
})


def validate_password(password: str) -> list[str]:
    """Returns list of validation errors. Empty = valid."""
    errors = []
    if len(password) < 12:
        errors.append("Mindestens 12 Zeichen")
    # bcrypt beruecksichtigt nur die ersten 72 Bytes — laengere Passwoerter wuerden
    # still abgeschnitten. Byte-, nicht Zeichenlaenge: Umlaute zaehlen doppelt.
    if len(password.encode("utf-8")) > 72:
        errors.append("Maximal 72 Bytes (Umlaute und Sonderzeichen zählen doppelt)")
    if not any(c.isupper() for c in password):
        errors.append("Mindestens 1 Grossbuchstabe")
    if not any(c.islower() for c in password):
        errors.append("Mindestens 1 Kleinbuchstabe")
    if not any(c.isdigit() for c in password):
        errors.append("Mindestens 1 Zahl")
    if not any(c in "!@#$%^&*()_+-=[]{}|;:,.<>?" for c in password):
        errors.append("Mindestens 1 Sonderzeichen (!@#$%^&*...)")
    if password.lower() in _COMMON_PASSWORDS:
        errors.append("Dieses Passwort ist zu häufig — bitte ein anderes wählen")
    return errors


def escape_like(value: str) -> str:
    """Escape SQL LIKE wildcard characters in user input."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


# --- Encrypted value migration ---

async def migrate_encrypted_values() -> tuple[int, int]:
    """Re-encrypt all legacy-encrypted values with the current key.

    Called once at startup. For each encrypted field, tries to decrypt
    with the current key. If that fails but a legacy key succeeds,
    re-encrypts with the current key and updates the DB row.
    """
    from sqlalchemy import select

    # Import here to avoid circular imports
    from db import async_session
    from models.user import User, UserSettings
    from models.smtp_config import SmtpConfig

    migrated = 0
    errors = 0

    async with async_session() as db:
        # 1) UserSettings.fred_api_key
        result = await db.execute(
            select(UserSettings).where(UserSettings.fred_api_key.isnot(None))
        )
        for s in result.scalars().all():
            try:
                _, needs = _decrypt_with_fallback(s.fred_api_key)
                if needs:
                    plain = _decrypt_with_fallback(s.fred_api_key)[0]
                    s.fred_api_key = encrypt_value(plain)
                    migrated += 1
                    _enc_logger.info(f"FRED API Key re-encrypted for user {s.user_id}")
            except Exception as e:
                errors += 1
                _enc_logger.warning(f"FRED API Key migration failed for user {s.user_id}: {e}")

        # 2) SmtpConfig.password_encrypted
        result = await db.execute(
            select(SmtpConfig).where(SmtpConfig.password_encrypted.isnot(None))
        )
        for smtp in result.scalars().all():
            try:
                _, needs = _decrypt_with_fallback(smtp.password_encrypted)
                if needs:
                    plain = _decrypt_with_fallback(smtp.password_encrypted)[0]
                    smtp.password_encrypted = encrypt_value(plain)
                    migrated += 1
                    _enc_logger.info(f"SMTP password re-encrypted for user {smtp.user_id}")
            except Exception as e:
                errors += 1
                _enc_logger.warning(f"SMTP password migration failed for user {smtp.user_id}: {e}")

        # 3) User.totp_secret
        result = await db.execute(
            select(User).where(User.totp_secret.isnot(None))
        )
        for user in result.scalars().all():
            try:
                _, needs = _decrypt_with_fallback(user.totp_secret)
                if needs:
                    plain = _decrypt_with_fallback(user.totp_secret)[0]
                    user.totp_secret = encrypt_totp_secret(plain)
                    migrated += 1
                    _enc_logger.info(f"TOTP secret re-encrypted for user {user.id}")
            except Exception as e:
                errors += 1
                _enc_logger.warning(f"TOTP secret migration failed for user {user.id}: {e}")

        if migrated > 0:
            await db.commit()
            _enc_logger.info(f"Encryption migration: {migrated} value(s) re-encrypted")
        if errors > 0:
            _enc_logger.warning(f"Encryption migration: {errors} value(s) failed")

    return migrated, errors
