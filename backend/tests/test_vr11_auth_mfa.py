"""Vollreview 11/2026, Fixer «auth»: zweiter Faktor und bcrypt.

K089 (Versuchsbudget je Konto, TOTP-Zeitschritt nur einmal), K165 (Backup-Code
atomar entwerten), K002/K103 (bcrypt ausserhalb des Event-Loops).
"""

import logging
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pyotp
import pytest
from sqlalchemy import func, select, update

from models.backup_code import BackupCode
from models.user import User
from services import auth_service, cache

PW = "TestPassw0rd!2026"
EMAIL = "mfa@example.com"
BACKUP_CODE = "ABCD1234-EF567890"


def h(token):
    return {"Authorization": f"Bearer {token}"}


async def register(client, email=EMAIL):
    res = await client.post("/api/auth/register", json={"email": email, "password": PW})
    assert res.status_code == 201, res.text


async def login(client, email=EMAIL, password=PW, totp_code=None):
    body = {"email": email, "password": password}
    if totp_code:
        body["totp_code"] = totp_code
    return await client.post("/api/auth/login", json=body)


async def get_user(db, email=EMAIL):
    res = await db.execute(
        select(User).where(func.lower(User.email) == email).execution_options(populate_existing=True)
    )
    return res.scalars().first()


async def enable_mfa(db, email=EMAIL):
    """MFA direkt in der DB aktivieren. Liefert (user, TOTP)."""
    user = await get_user(db, email)
    secret = auth_service.generate_totp_secret()
    user.mfa_enabled = True
    user.totp_secret = auth_service.encrypt_totp_secret(secret)
    await db.commit()
    return user, pyotp.TOTP(secret)


def wrong_code(totp):
    """Ein sechsstelliger Code, der in keinem nahen Zeitschritt gilt."""
    now = time.time()
    near = {totp.at(now + offset) for offset in (-60, -30, 0, 30, 60, 90)}
    return next(c for c in (f"{n:06d}" for n in range(1000)) if c not in near)


def next_step_code(totp):
    """Code des nächsten Zeitschritts: gilt auch, wenn die 30-s-Grenze dazwischen fällt."""
    return totp.at(time.time() + 30)


class TestSecondFactorLock:
    async def test_five_failures_lock_the_second_factor(self, client, db, caplog):
        await register(client)
        user, totp = await enable_mfa(db)
        bad = wrong_code(totp)

        with caplog.at_level(logging.WARNING, logger="api.auth"):
            for _ in range(auth_service.MFA_MAX_FAILED_ATTEMPTS):
                res = await login(client, totp_code=bad)
                assert res.status_code == 401, res.text
            # Auch der richtige Code hilft jetzt nicht mehr.
            locked = await login(client, totp_code=totp.now())

        assert locked.status_code == 429
        assert "15 Minuten" in locked.json()["detail"]
        messages = [r.getMessage() for r in caplog.records]
        assert sum("Second factor failed" in m for m in messages) == 5
        assert any("Second factor locked" in m and str(user.id) in m for m in messages)

    async def test_lock_ends_when_the_counter_expires(self, client, db):
        await register(client)
        user, totp = await enable_mfa(db)
        bad = wrong_code(totp)
        for _ in range(5):
            await login(client, totp_code=bad)
        assert (await login(client, totp_code=totp.now())).status_code == 429

        cache.delete(f"mfa_attempts:{user.id}")  # Ablauf der 15 Minuten
        assert (await login(client, totp_code=totp.now())).status_code == 200

    async def test_counter_lives_fifteen_minutes(self, monkeypatch):
        seen = []
        real_set = cache.set

        def spy_set(key, value, ttl=cache.DEFAULT_TTL):
            seen.append((key, value, ttl))
            return real_set(key, value, ttl)

        monkeypatch.setattr(cache, "set", spy_set)
        uid = uuid.uuid4()
        for expected in range(1, 6):
            assert auth_service.reserve_mfa_attempt(uid) is True
            assert seen[-1] == (f"mfa_attempts:{uid}", expected, 15 * 60)
        # Gesperrt: der Versuch zählt nicht, die Sperre verlängert sich nicht.
        assert auth_service.reserve_mfa_attempt(uid) is False
        assert len(seen) == 5
        auth_service.clear_mfa_attempts(uid)
        assert auth_service.reserve_mfa_attempt(uid) is True

    async def test_success_resets_the_counter(self, client, db):
        await register(client)
        _, totp = await enable_mfa(db)
        bad = wrong_code(totp)

        for _ in range(4):
            assert (await login(client, totp_code=bad)).status_code == 401
        assert (await login(client, totp_code=totp.now())).status_code == 200
        for _ in range(4):
            assert (await login(client, totp_code=bad)).status_code == 401
        assert (await login(client, totp_code=next_step_code(totp))).status_code == 200

    async def test_lock_counts_per_account(self, client, db):
        await register(client)
        _, totp = await enable_mfa(db)
        await register(client, "other@example.com")
        _, other_totp = await enable_mfa(db, "other@example.com")

        bad = wrong_code(totp)
        for _ in range(5):
            await login(client, totp_code=bad)
        assert (await login(client, totp_code=totp.now())).status_code == 429
        assert (await login(client, "other@example.com", totp_code=other_totp.now())).status_code == 200

    async def test_wrong_password_never_locks_the_account(self, client, db):
        """Ohne Passwort kann niemand den zweiten Faktor eines Kontos sperren, und
        für Passwort-Fehlversuche gibt es keinen Zähler je Konto (K103, Entscheid)."""
        await register(client)
        _, totp = await enable_mfa(db)
        for _ in range(8):
            res = await login(client, password="Falsch0Passw!rd99", totp_code=wrong_code(totp))
            assert res.status_code == 401
            assert res.json()["detail"] == "Ungültige Anmeldedaten"
        assert (await login(client, totp_code=totp.now())).status_code == 200

    async def test_backup_code_failures_count_too(self, client, db):
        await register(client)
        user, totp = await enable_mfa(db)
        db.add(BackupCode(user_id=user.id, code_hash=auth_service.hash_backup_code(BACKUP_CODE)))
        await db.commit()

        for _ in range(5):
            res = await login(client, totp_code="00000000-00000000")
            assert res.status_code == 401
        assert (await login(client, totp_code=BACKUP_CODE)).status_code == 429
        assert (await login(client, totp_code=totp.now())).status_code == 429

    async def test_authenticated_totp_routes_share_the_lock(self, client, db):
        await register(client)
        token = (await login(client)).json()["access_token"]
        _, totp = await enable_mfa(db)
        bad = wrong_code(totp)

        for _ in range(5):
            res = await client.post(
                "/api/auth/mfa/regenerate-backup-codes", json={"totp_code": bad}, headers=h(token),
            )
            assert res.status_code == 401
        res = await client.post(
            "/api/auth/mfa/regenerate-backup-codes", json={"totp_code": totp.now()}, headers=h(token),
        )
        assert res.status_code == 429
        res = await client.post(
            "/api/auth/mfa/disable", json={"password": PW, "totp_code": totp.now()}, headers=h(token),
        )
        assert res.status_code == 429
        assert (await get_user(db)).mfa_enabled is True


class TestTotpReplay:
    async def test_same_code_is_rejected_the_second_time(self, client, db):
        await register(client)
        _, totp = await enable_mfa(db)
        code = totp.now()

        assert (await login(client, totp_code=code)).status_code == 200
        replay = await login(client, totp_code=code)
        assert replay.status_code == 401
        assert replay.json()["detail"] == "Ungültiger MFA-Code"
        # Der nächste Zeitschritt gilt wieder.
        assert (await login(client, totp_code=next_step_code(totp))).status_code == 200

    async def test_time_step_is_consumed_per_user(self):
        secret = auth_service.generate_totp_secret()
        totp = pyotp.TOTP(secret)
        code = totp.now()
        user_a, user_b = uuid.uuid4(), uuid.uuid4()

        assert auth_service.consume_totp_code(user_a, secret, code) is True
        assert auth_service.consume_totp_code(user_a, secret, code) is False
        assert auth_service.consume_totp_code(user_b, secret, code) is True
        assert auth_service.consume_totp_code(user_a, secret, wrong_code(totp)) is False

    async def test_match_totp_step_accepts_the_neighbours_only(self):
        secret = auth_service.generate_totp_secret()
        totp = pyotp.TOTP(secret)
        now = time.time()
        current = int(now) // 30

        assert auth_service.match_totp_step(secret, totp.at(now)) in (current, current + 1)
        assert auth_service.match_totp_step(secret, totp.at(now + 30)) is not None
        assert auth_service.match_totp_step(secret, totp.at(now + 300)) is None
        assert auth_service.match_totp_step(secret, totp.at(now - 300)) is None

    async def test_code_from_mfa_setup_cannot_be_replayed_at_login(self, client, db):
        await register(client)
        token = (await login(client)).json()["access_token"]
        secret = (await client.post("/api/auth/mfa/setup", headers=h(token))).json()["secret"]
        code = pyotp.TOTP(secret).now()
        res = await client.post("/api/auth/mfa/verify-setup", json={"totp_code": code}, headers=h(token))
        assert res.status_code == 200, res.text

        assert (await login(client, totp_code=code)).status_code == 401

    async def test_code_used_at_login_cannot_disable_mfa(self, client, db):
        await register(client)
        _, totp = await enable_mfa(db)
        code = totp.now()
        session = await login(client, totp_code=code)
        assert session.status_code == 200

        res = await client.post(
            "/api/auth/mfa/disable", json={"password": PW, "totp_code": code},
            headers=h(session.json()["access_token"]),
        )
        assert res.status_code == 401
        assert (await get_user(db)).mfa_enabled is True


class TestBackupCodeAtomic:
    """K165: Zwei parallele Logins dürfen denselben Backup-Code nicht beide verbrauchen."""

    async def _user_with_code(self, db):
        user = User(email=EMAIL, password_hash="x")
        db.add(user)
        await db.flush()
        db.add(BackupCode(user_id=user.id, code_hash=auth_service.hash_backup_code(BACKUP_CODE)))
        await db.commit()
        return user

    async def test_lost_race_is_rejected(self, db, monkeypatch):
        user = await self._user_with_code(db)
        orig_execute = db.execute
        state = {"stolen": False}

        async def execute_then_steal(stmt, *args, **kwargs):
            result = await orig_execute(stmt, *args, **kwargs)
            if not state["stolen"]:
                # Direkt nach dem SELECT der offenen Codes entwertet ein paralleler
                # Login denselben Code.
                state["stolen"] = True
                await orig_execute(update(BackupCode).values(used=True))
            return result

        monkeypatch.setattr(db, "execute", execute_then_steal)
        assert await auth_service.verify_backup_code(db, user.id, BACKUP_CODE) is False

    async def test_code_works_exactly_once(self, db):
        user = await self._user_with_code(db)
        assert await auth_service.verify_backup_code(db, user.id, "abcd1234-ef567890 ") is True
        await db.commit()
        row = (await db.execute(select(BackupCode).execution_options(populate_existing=True))).scalars().one()
        assert row.used is True and row.used_at is not None
        assert await auth_service.verify_backup_code(db, user.id, BACKUP_CODE) is False

    async def test_wrong_code_consumes_nothing(self, db):
        user = await self._user_with_code(db)
        assert await auth_service.verify_backup_code(db, user.id, "00000000-00000000") is False
        row = (await db.execute(select(BackupCode).execution_options(populate_existing=True))).scalars().one()
        assert row.used is False

    async def test_login_with_backup_code_once(self, client, db):
        await register(client)
        user, _ = await enable_mfa(db)
        db.add(BackupCode(user_id=user.id, code_hash=auth_service.hash_backup_code(BACKUP_CODE)))
        await db.commit()

        assert (await login(client, totp_code=BACKUP_CODE)).status_code == 200
        assert (await login(client, totp_code=BACKUP_CODE)).status_code == 401


class _CountingExecutor(ThreadPoolExecutor):
    def __init__(self):
        super().__init__(max_workers=2, thread_name_prefix="bcrypt-test")
        self.submitted = 0

    def submit(self, fn, /, *args, **kwargs):
        self.submitted += 1
        return super().submit(fn, *args, **kwargs)


@pytest.fixture
def bcrypt_spy(monkeypatch):
    """Ersetzt bcrypt durch einen schnellen Ersatz und merkt sich, in welchem
    Thread gerechnet wurde und wie oft der Pool einen Auftrag bekam."""
    threads = []

    def fake_hash(password):
        threads.append(threading.current_thread().name)
        return f"fake${password}"

    def fake_verify(password, password_hash):
        threads.append(threading.current_thread().name)
        return password_hash == f"fake${password}"

    executor = _CountingExecutor()
    monkeypatch.setattr(auth_service, "hash_password", fake_hash)
    monkeypatch.setattr(auth_service, "verify_password", fake_verify)
    monkeypatch.setattr(auth_service, "_bcrypt_executor", executor)
    spy = SimpleNamespace(threads=threads, executor=executor)

    def reset():
        threads.clear()
        executor.submitted = 0

    spy.reset = reset
    yield spy
    executor.shutdown(wait=False)


def assert_only_pool_threads(spy, calls):
    assert len(spy.threads) == calls, spy.threads
    assert all(name.startswith("bcrypt-test") for name in spy.threads), spy.threads


class TestBcryptOffTheEventLoop:
    """K002: Kein Auth-Pfad rechnet bcrypt im Event-Loop."""

    async def test_account_routes_hash_in_the_pool(self, client, bcrypt_spy):
        await register(client)
        assert_only_pool_threads(bcrypt_spy, 1)

        bcrypt_spy.reset()
        assert (await client.post("/api/auth/register", json={"email": EMAIL, "password": PW})).status_code == 409
        assert_only_pool_threads(bcrypt_spy, 1)  # Dummy-Hash gegen das Timing-Orakel

        bcrypt_spy.reset()
        assert (await login(client, password="Falsch0Passw!rd99")).status_code == 401
        assert (await login(client, "nobody@example.com")).status_code == 401
        session = await login(client)
        assert session.status_code == 200
        assert_only_pool_threads(bcrypt_spy, 3)
        token = session.json()["access_token"]

        bcrypt_spy.reset()
        res = await client.post(
            "/api/auth/change-email", json={"password": "Falsch0Passw!rd99", "new_email": "x@example.com"},
            headers=h(token),
        )
        assert res.status_code == 401
        assert_only_pool_threads(bcrypt_spy, 1)

        bcrypt_spy.reset()
        res = await client.post(
            "/api/auth/change-password", json={"current_password": PW, "new_password": "NewPassw0rd!2027"},
            headers=h(token),
        )
        assert res.status_code == 200, res.text
        assert_only_pool_threads(bcrypt_spy, 2)

        token = (await login(client, password="NewPassw0rd!2027")).json()["access_token"]
        bcrypt_spy.reset()
        res = await client.request(
            "DELETE", "/api/auth/account", json={"password": "NewPassw0rd!2027"}, headers=h(token),
        )
        assert res.status_code == 204
        assert_only_pool_threads(bcrypt_spy, 1)

    async def test_reset_and_forced_change_hash_in_the_pool(self, client, db, bcrypt_spy):
        import hashlib
        from datetime import timedelta

        from dateutils import utcnow
        from models.password_reset_token import PasswordResetToken

        await register(client)
        user = await get_user(db)
        db.add(PasswordResetToken(
            user_id=user.id,
            token_hash=hashlib.sha256(b"raw-reset").hexdigest(),
            expires_at=utcnow() + timedelta(minutes=30),
        ))
        await db.commit()

        bcrypt_spy.reset()
        res = await client.post(
            "/api/auth/reset-password", json={"token": "raw-reset", "new_password": "NewPassw0rd!2027"},
        )
        assert res.status_code == 200, res.text
        assert_only_pool_threads(bcrypt_spy, 1)

        token = (await login(client, password="NewPassw0rd!2027")).json()["access_token"]
        user = await get_user(db)
        user.force_password_change = True
        await db.commit()
        bcrypt_spy.reset()
        res = await client.post(
            "/api/auth/force-change-password", json={"new_password": "Other0Passw!rd2028"}, headers=h(token),
        )
        assert res.status_code == 200, res.text
        assert_only_pool_threads(bcrypt_spy, 1)

    async def test_mfa_setup_hashes_all_backup_codes_in_one_pool_call(self, client, bcrypt_spy):
        await register(client)
        token = (await login(client)).json()["access_token"]
        secret = (await client.post("/api/auth/mfa/setup", headers=h(token))).json()["secret"]

        bcrypt_spy.reset()
        res = await client.post(
            "/api/auth/mfa/verify-setup", json={"totp_code": pyotp.TOTP(secret).now()}, headers=h(token),
        )
        assert res.status_code == 200, res.text
        assert len(res.json()["backup_codes"]) == 8
        assert_only_pool_threads(bcrypt_spy, 8)
        assert bcrypt_spy.executor.submitted == 1

        bcrypt_spy.reset()
        res = await client.post(
            "/api/auth/mfa/regenerate-backup-codes",
            json={"totp_code": next_step_code(pyotp.TOTP(secret))}, headers=h(token),
        )
        assert res.status_code == 200, res.text
        assert_only_pool_threads(bcrypt_spy, 8)
        assert bcrypt_spy.executor.submitted == 1

    async def test_backup_code_login_checks_all_codes_in_one_pool_call(self, client, db, bcrypt_spy):
        await register(client)
        user, _ = await enable_mfa(db)
        for code in auth_service.generate_backup_codes():
            db.add(BackupCode(user_id=user.id, code_hash=auth_service.hash_backup_code(code)))
        await db.commit()

        bcrypt_spy.reset()
        res = await login(client, totp_code="00000000-00000000")
        assert res.status_code == 401
        assert res.json()["detail"] == "Ungültiger Backup-Code"
        # Ein Aufruf für das Passwort, einer für alle acht Codes.
        assert_only_pool_threads(bcrypt_spy, 9)
        assert bcrypt_spy.executor.submitted == 2

    async def test_admin_temp_password_hashes_in_the_pool(self, client, db, bcrypt_spy):
        from services import admin_service

        await register(client)
        user = await get_user(db)

        bcrypt_spy.reset()
        result = await admin_service.set_temp_password(db, uuid.uuid4(), user.id)
        assert_only_pool_threads(bcrypt_spy, 1)
        assert (await login(client, password=result["temp_password"])).status_code == 200
