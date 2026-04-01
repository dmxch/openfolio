"""Authentication service: JWT, password hashing, TOTP, token management."""

import hashlib
import os
import secrets
import uuid
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


# --- JWT ---

ACCESS_TOKEN_EXPIRE_MINUTES = 15
REFRESH_TOKEN_EXPIRE_DAYS = 30


def create_access_token(user_id: str, email: str) -> tuple[str, int]:
    """Returns (token, expires_in_seconds)."""
    now = utcnow()
    expires = now + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": user_id,
        "email": email,
        "iat": now,
        "exp": expires,
        "type": "access",
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


def _decrypt_with_fallback(encrypted: str) -> tuple[str, bool]:
    """Decrypt value, trying current key then legacy keys.

    Returns (decrypted_text, needs_reencrypt).
    needs_reencrypt is True when a legacy key succeeded.
    """
    data = encrypted.encode()

    # Try current key first
    try:
        return _get_fernet().decrypt(data).decode(), False
    except Exception as e:
        _enc_logger.debug(f"Current key decryption failed, trying legacy keys: {e}")

    # Try legacy keys
    for legacy_f in _get_legacy_fernets():
        try:
            return legacy_f.decrypt(data).decode(), True
        except Exception as e:
            _enc_logger.debug(f"Legacy key decryption attempt failed: {e}")
            continue

    raise ValueError("Entschlüsselung fehlgeschlagen — weder aktueller noch Legacy-Key funktioniert")


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
    from sqlalchemy import select
    from models.backup_code import BackupCode

    normalized = code.strip().upper().replace("-", "")
    result = await db.execute(
        select(BackupCode).where(
            BackupCode.user_id == user_id,
            BackupCode.used == False,
        )
    )
    for bc in result.scalars().all():
        if verify_password(normalized, bc.code_hash):
            bc.used = True
            bc.used_at = utcnow()
            return True
    return False


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
    if len(password) > 128:
        errors.append("Maximal 128 Zeichen")
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
