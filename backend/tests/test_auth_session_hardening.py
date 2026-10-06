"""Security hardening Block A: token_version, atomic refresh, reset-token and
force_password_change enforcement, API-token creation password check."""

import hashlib
from datetime import timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, update

from dateutils import utcnow
from models.api_token import ApiToken
from models.password_reset_token import PasswordResetToken
from models.user import RefreshToken, User
from services.auth_service import create_access_token

pytestmark = pytest.mark.asyncio

PW = "TestPassw0rd!2026"
NEW_PW = "NewPassw0rd!2027"
EMAIL = "hard@example.com"


def h(token):
    return {"Authorization": f"Bearer {token}"}


async def signup(client, email=EMAIL):
    await client.post("/api/auth/register", json={"email": email, "password": PW})
    res = await client.post("/api/auth/login", json={"email": email, "password": PW})
    assert res.status_code == 200, res.text
    return res.json()


async def get_user(db, email=EMAIL):
    res = await db.execute(
        select(User).where(func.lower(User.email) == email).execution_options(populate_existing=True)
    )
    return res.scalars().first()


async def make_reset_token(db, user, raw="raw-reset-token"):
    db.add(PasswordResetToken(
        user_id=user.id,
        token_hash=hashlib.sha256(raw.encode()).hexdigest(),
        expires_at=utcnow() + timedelta(minutes=30),
    ))
    await db.commit()
    return raw


async def api_token(client, jwt, password=PW):
    return await client.post(
        "/api/settings/api-tokens",
        json={"name": "k", "current_password": password},
        headers=h(jwt),
    )


class TestTokenVersion:
    async def test_token_without_tv_rejected(self, client, db):
        s = await signup(client)
        import jwt as pyjwt
        from config import settings
        payload = pyjwt.decode(s["access_token"], settings.jwt_secret, algorithms=["HS256"])
        assert payload["tv"] == 0
        payload.pop("tv")
        legacy = pyjwt.encode(payload, settings.jwt_secret, algorithm="HS256")
        assert (await client.get("/api/auth/me", headers=h(legacy))).status_code == 401

    async def test_old_access_token_dead_after_logout_all(self, client):
        s = await signup(client)
        assert (await client.get("/api/auth/me", headers=h(s["access_token"]))).status_code == 200
        res = await client.post("/api/auth/logout-all", headers=h(s["access_token"]))
        assert res.status_code == 204
        assert (await client.get("/api/auth/me", headers=h(s["access_token"]))).status_code == 401

    async def test_old_access_token_dead_after_change_password(self, client):
        s = await signup(client)
        res = await client.post(
            "/api/auth/change-password", headers=h(s["access_token"]),
            json={"current_password": PW, "new_password": NEW_PW},
        )
        assert res.status_code == 200, res.text
        assert (await client.get("/api/auth/me", headers=h(s["access_token"]))).status_code == 401

    async def test_old_access_token_dead_after_revoke_all_sessions(self, client):
        s = await signup(client)
        assert (await client.delete("/api/auth/sessions", headers=h(s["access_token"]))).status_code == 204
        assert (await client.get("/api/auth/me", headers=h(s["access_token"]))).status_code == 401

    async def test_old_access_token_dead_after_reset_password(self, client, db):
        s = await signup(client)
        raw = await make_reset_token(db, await get_user(db))
        res = await client.post("/api/auth/reset-password", json={"token": raw, "new_password": NEW_PW})
        assert res.status_code == 200, res.text
        assert (await client.get("/api/auth/me", headers=h(s["access_token"]))).status_code == 401

    async def test_refresh_issues_token_with_current_version(self, client, db):
        s = await signup(client)
        await client.post("/api/auth/logout-all", headers=h(s["access_token"]))
        # logout-all revoked the refresh token -> new login gives tv == 1
        s2 = await signup(client)
        assert (await client.get("/api/auth/me", headers=h(s2["access_token"]))).status_code == 200
        r = await client.post("/api/auth/refresh", json={"refresh_token": s2["refresh_token"]})
        assert r.status_code == 200
        assert (await client.get("/api/auth/me", headers=h(r.json()["access_token"]))).status_code == 200


class TestApiTokenCreation:
    async def test_missing_password_rejected(self, client):
        s = await signup(client)
        res = await client.post("/api/settings/api-tokens", json={"name": "k"}, headers=h(s["access_token"]))
        assert res.status_code == 422

    async def test_wrong_password_401(self, client):
        s = await signup(client)
        res = await api_token(client, s["access_token"], "wrong-password")
        assert res.status_code == 401

    async def test_correct_password_201(self, client):
        s = await signup(client)
        res = await api_token(client, s["access_token"])
        assert res.status_code == 201

    async def test_api_key_dead_after_reset_password(self, client, db):
        s = await signup(client)
        key = (await api_token(client, s["access_token"])).json()["token"]
        assert (await client.get("/api/v1/external/portfolio/summary", headers={"X-API-Key": key})).status_code != 401
        raw = await make_reset_token(db, await get_user(db))
        assert (await client.post("/api/auth/reset-password", json={"token": raw, "new_password": NEW_PW})).status_code == 200
        assert (await client.get("/api/v1/external/portfolio/summary", headers={"X-API-Key": key})).status_code == 401

    async def test_api_key_survives_change_password(self, client):
        s = await signup(client)
        key = (await api_token(client, s["access_token"])).json()["token"]
        res = await client.post(
            "/api/auth/change-password", headers=h(s["access_token"]),
            json={"current_password": PW, "new_password": NEW_PW},
        )
        assert res.status_code == 200
        assert (await client.get("/api/v1/external/portfolio/summary", headers={"X-API-Key": key})).status_code != 401


class TestRefreshAtomic:
    async def test_second_consumption_yields_no_second_pair(self, client):
        s = await signup(client)
        first = await client.post("/api/auth/refresh", json={"refresh_token": s["refresh_token"]})
        assert first.status_code == 200
        second = await client.post("/api/auth/refresh", json={"refresh_token": s["refresh_token"]})
        assert second.status_code == 401

    async def test_replay_outside_grace_kills_access_tokens(self, client):
        from services import cache
        s = await signup(client)
        rotated = await client.post("/api/auth/refresh", json={"refresh_token": s["refresh_token"]})
        assert rotated.status_code == 200
        th = hashlib.sha256(s["refresh_token"].encode()).hexdigest()
        cache.delete(f"refresh_rotation_grace:{th}")
        replay = await client.post("/api/auth/refresh", json={"refresh_token": s["refresh_token"]})
        assert replay.status_code == 401
        me = await client.get("/api/auth/me", headers=h(rotated.json()["access_token"]))
        assert me.status_code == 401

    async def test_conditional_update_consumes_only_once(self, client, db):
        s = await signup(client)
        th = hashlib.sha256(s["refresh_token"].encode()).hexdigest()

        def stmt():
            return (
                update(RefreshToken)
                .where(RefreshToken.token_hash == th, RefreshToken.revoked == False, RefreshToken.expires_at > utcnow())
                .values(revoked=True)
                .returning(RefreshToken.user_id)
            )
        assert (await db.execute(stmt())).scalar_one_or_none() is not None
        assert (await db.execute(stmt())).scalar_one_or_none() is None

    async def test_expired_token_401(self, client, db):
        s = await signup(client)
        await db.execute(update(RefreshToken).values(expires_at=utcnow() - timedelta(days=1)))
        await db.commit()
        res = await client.post("/api/auth/refresh", json={"refresh_token": s["refresh_token"]})
        assert res.status_code == 401

    async def test_unknown_token_401(self, client):
        res = await client.post("/api/auth/refresh", json={"refresh_token": "nope"})
        assert res.status_code == 401


class TestResetTokenInvalidation:
    async def test_old_reset_token_dead_after_change_password(self, client, db):
        s = await signup(client)
        raw = await make_reset_token(db, await get_user(db))
        res = await client.post(
            "/api/auth/change-password", headers=h(s["access_token"]),
            json={"current_password": PW, "new_password": NEW_PW},
        )
        assert res.status_code == 200
        res = await client.post("/api/auth/reset-password", json={"token": raw, "new_password": "Other0Passw!rd2028"})
        assert res.status_code == 400

    async def test_old_reset_token_dead_after_force_change(self, client, db):
        s = await signup(client)
        u = await get_user(db)
        raw = await make_reset_token(db, u)
        u.force_password_change = True
        await db.commit()
        res = await client.post(
            "/api/auth/force-change-password", headers=h(s["access_token"]),
            json={"new_password": NEW_PW},
        )
        assert res.status_code == 200, res.text
        res = await client.post("/api/auth/reset-password", json={"token": raw, "new_password": "Other0Passw!rd2028"})
        assert res.status_code == 400


class TestForcePasswordChangeEnforced:
    async def _forced(self, client, db):
        s = await signup(client)
        u = await get_user(db)
        u.force_password_change = True
        await db.commit()
        return s

    async def test_protected_endpoint_403(self, client, db):
        s = await self._forced(client, db)
        res = await client.get("/api/settings", headers=h(s["access_token"]))
        assert res.status_code == 403
        assert res.headers.get("X-Password-Change-Required") == "1"
        assert res.json()["detail"] == "Passwortänderung erforderlich"

    async def test_me_allowed(self, client, db):
        s = await self._forced(client, db)
        assert (await client.get("/api/auth/me", headers=h(s["access_token"]))).status_code == 200

    async def test_force_change_allowed_then_normal_after_relogin(self, client, db):
        s = await self._forced(client, db)
        res = await client.post(
            "/api/auth/force-change-password", headers=h(s["access_token"]), json={"new_password": NEW_PW}
        )
        assert res.status_code == 200
        login = await client.post("/api/auth/login", json={"email": EMAIL, "password": NEW_PW})
        assert login.status_code == 200
        assert (await client.get("/api/settings", headers=h(login.json()["access_token"]))).status_code == 200

    async def test_external_api_unaffected(self, client, db):
        s = await signup(client)
        key = (await api_token(client, s["access_token"])).json()["token"]
        u = await get_user(db)
        u.force_password_change = True
        await db.commit()
        res = await client.get("/api/v1/external/portfolio/summary", headers={"X-API-Key": key})
        assert res.status_code != 401 and res.status_code != 403


class TestRefreshTokenVersion:
    async def _inject(self, db, user, tv):
        from services.auth_service import create_refresh_token
        raw, th, exp = create_refresh_token()
        db.add(RefreshToken(user_id=user.id, token_hash=th, expires_at=exp, token_version=tv))
        await db.commit()
        return raw

    async def test_stale_version_rejected(self, client, db):
        s = await signup(client)
        user = await get_user(db)
        await db.execute(update(User).where(User.id == user.id).values(token_version=user.token_version + 1))
        await db.commit()
        res = await client.post("/api/auth/refresh", json={"refresh_token": s["refresh_token"]})
        assert res.status_code == 401

    async def test_race_token_dies_on_logout_all(self, client, db):
        s = await signup(client)
        user = await get_user(db)
        # R2: created by a parallel refresh that read the version before the revoke
        r2 = await self._inject(db, user, user.token_version)
        res = await client.post("/api/auth/logout-all", headers=h(s["access_token"]))
        assert res.status_code == 204
        # simulate READ COMMITTED: R2 was invisible to the revoke -> still unrevoked
        th = hashlib.sha256(r2.encode()).hexdigest()
        await db.execute(update(RefreshToken).where(RefreshToken.token_hash == th).values(revoked=False))
        await db.commit()
        res = await client.post("/api/auth/refresh", json={"refresh_token": r2})
        assert res.status_code == 401

    async def test_race_token_dies_on_reset_password(self, client, db):
        s = await signup(client)
        user = await get_user(db)
        r2 = await self._inject(db, user, user.token_version)
        raw = await make_reset_token(db, user)
        res = await client.post("/api/auth/reset-password", json={"token": raw, "new_password": NEW_PW})
        assert res.status_code == 200
        th = hashlib.sha256(r2.encode()).hexdigest()
        await db.execute(update(RefreshToken).where(RefreshToken.token_hash == th).values(revoked=False))
        await db.commit()
        res = await client.post("/api/auth/refresh", json={"refresh_token": r2})
        assert res.status_code == 401

    async def test_normal_refresh_carries_current_version(self, client, db):
        s = await signup(client)
        res = await client.post("/api/auth/refresh", json={"refresh_token": s["refresh_token"]})
        assert res.status_code == 200
        user = await get_user(db)
        th = hashlib.sha256(res.json()["refresh_token"].encode()).hexdigest()
        rt = (await db.execute(select(RefreshToken).where(RefreshToken.token_hash == th))).scalars().first()
        assert rt.token_version == user.token_version

    async def test_login_after_logout_all_refreshes(self, client, db):
        s = await signup(client)
        await client.post("/api/auth/logout-all", headers=h(s["access_token"]))
        s2 = (await client.post("/api/auth/login", json={"email": EMAIL, "password": PW})).json()
        res = await client.post("/api/auth/refresh", json={"refresh_token": s2["refresh_token"]})
        assert res.status_code == 200


class TestMfaDisableRevokes:
    async def test_mfa_disable_revokes_refresh_tokens(self, client, db):
        s = await signup(client)
        u = await get_user(db)
        await db.execute(update(RefreshToken).where(RefreshToken.user_id == u.id).values(revoked=False))
        from api import auth as auth_api
        import services.auth_service as svc
        u.mfa_enabled = True
        u.totp_secret = svc.encrypt_totp_secret(svc.generate_totp_secret())
        await db.commit()
        import pyotp
        code = pyotp.TOTP(svc.decrypt_totp_secret(u.totp_secret)).now()
        res = await client.post("/api/auth/mfa/disable", headers=h(s["access_token"]),
                                json={"password": PW, "totp_code": code})
        assert res.status_code == 200, res.text
        rts = (await db.execute(select(RefreshToken).where(RefreshToken.user_id == u.id)
               .execution_options(populate_existing=True))).scalars().all()
        assert rts and all(rt.revoked for rt in rts)
