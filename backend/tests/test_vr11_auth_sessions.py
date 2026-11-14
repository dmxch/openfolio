"""Vollreview 11/2026, Fixer «auth»: Sitzungen.

K034 (widerrufene Refresh-Tokens lösen keinen Global-Logout mehr aus),
K151 (Logout ohne Access-Token), K016 (get_current_user gibt die Connection frei).
"""

from sqlalchemy import func, select
from starlette.requests import Request

from models.user import RefreshToken, User
from services import cache
from services.auth_service import hash_refresh_token

PW = "TestPassw0rd!2026"
NEW_PW = "NewPassw0rd!2027"
EMAIL = "sessions@example.com"


def h(token):
    return {"Authorization": f"Bearer {token}"}


async def login(client, email=EMAIL, password=PW):
    res = await client.post("/api/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    return res.json()


async def signup(client, email=EMAIL):
    res = await client.post("/api/auth/register", json={"email": email, "password": PW})
    assert res.status_code == 201, res.text
    return await login(client, email)


async def refresh(client, token):
    return await client.post("/api/auth/refresh", json={"refresh_token": token})


async def token_row(db, raw):
    res = await db.execute(
        select(RefreshToken)
        .where(RefreshToken.token_hash == hash_refresh_token(raw))
        .execution_options(populate_existing=True)
    )
    return res.scalars().first()


def assert_plain_401(res):
    """401 ohne Diebstahl-Meldung: kein Global-Revoke."""
    assert res.status_code == 401
    assert "kompromittiert" not in res.json()["detail"]


async def assert_session_alive(client, session):
    assert (await client.get("/api/auth/me", headers=h(session["access_token"]))).status_code == 200
    assert (await refresh(client, session["refresh_token"])).status_code == 200


class TestRevokedTokenReplay:
    """K034: Nur die Wiedervorlage eines ROTIERTEN Tokens ist ein Diebstahl-Signal."""

    async def test_token_revoked_by_password_change_spares_new_session(self, client):
        phone = await signup(client)
        desktop = await login(client)
        res = await client.post(
            "/api/auth/change-password", headers=h(desktop["access_token"]),
            json={"current_password": PW, "new_password": NEW_PW},
        )
        assert res.status_code == 200, res.text
        fresh = await login(client, password=NEW_PW)

        # Das Handy öffnet die App und legt sein widerrufenes Token vor.
        assert_plain_401(await refresh(client, phone["refresh_token"]))
        await assert_session_alive(client, fresh)

    async def test_token_revoked_by_logout_all_spares_new_session(self, client):
        phone = await signup(client)
        desktop = await login(client)
        assert (await client.post("/api/auth/logout-all", headers=h(desktop["access_token"]))).status_code == 204
        fresh = await login(client)

        assert_plain_401(await refresh(client, phone["refresh_token"]))
        await assert_session_alive(client, fresh)

    async def test_single_revoked_session_spares_the_others(self, client, db):
        laptop = await signup(client)
        phone = await login(client)
        phone_row = await token_row(db, phone["refresh_token"])

        res = await client.delete(f"/api/auth/sessions/{phone_row.id}", headers=h(laptop["access_token"]))
        assert res.status_code == 204
        # Gelöscht, nicht markiert: sonst sähe die Zeile wie ein rotierter Token aus.
        assert await token_row(db, phone["refresh_token"]) is None

        assert_plain_401(await refresh(client, phone["refresh_token"]))
        await assert_session_alive(client, laptop)

    async def test_logged_out_token_spares_the_others(self, client, db):
        laptop = await signup(client)
        phone = await login(client)

        res = await client.post("/api/auth/logout", json={"refresh_token": phone["refresh_token"]})
        assert res.status_code == 204
        assert await token_row(db, phone["refresh_token"]) is None

        assert_plain_401(await refresh(client, phone["refresh_token"]))
        await assert_session_alive(client, laptop)

    async def test_stolen_rotated_token_still_revokes_everything(self, client):
        victim = await signup(client)
        other_device = await login(client)
        rotated = await refresh(client, victim["refresh_token"])
        assert rotated.status_code == 200
        cache.delete(f"refresh_rotation_grace:{hash_refresh_token(victim['refresh_token'])}")

        replay = await refresh(client, victim["refresh_token"])
        assert replay.status_code == 401
        assert "kompromittiert" in replay.json()["detail"]

        assert (await refresh(client, rotated.json()["refresh_token"])).status_code == 401
        assert (await refresh(client, other_device["refresh_token"])).status_code == 401
        me = await client.get("/api/auth/me", headers=h(rotated.json()["access_token"]))
        assert me.status_code == 401

    async def test_second_replay_cannot_log_the_account_out_again(self, client):
        victim = await signup(client)
        assert (await refresh(client, victim["refresh_token"])).status_code == 200
        cache.delete(f"refresh_rotation_grace:{hash_refresh_token(victim['refresh_token'])}")
        first = await refresh(client, victim["refresh_token"])
        assert "kompromittiert" in first.json()["detail"]

        # Der Nutzer meldet sich neu an. Wer das alte Token besitzt, darf diese
        # Sitzung nicht beliebig oft wieder beenden.
        fresh = await login(client)
        assert_plain_401(await refresh(client, victim["refresh_token"]))
        await assert_session_alive(client, fresh)

    async def test_logout_does_not_erase_a_rotated_token(self, client, db):
        """Ein Dieb darf die Spur seines Tokens nicht per Logout tilgen: die
        rotierte Zeile bleibt, die Wiedervorlage löst weiter den Global-Revoke aus."""
        victim = await signup(client)
        rotated = await refresh(client, victim["refresh_token"])
        assert rotated.status_code == 200
        cache.delete(f"refresh_rotation_grace:{hash_refresh_token(victim['refresh_token'])}")

        res = await client.post("/api/auth/logout", json={"refresh_token": victim["refresh_token"]})
        assert res.status_code == 204
        row = await token_row(db, victim["refresh_token"])
        assert row is not None and row.revoked is True

        replay = await refresh(client, victim["refresh_token"])
        assert replay.status_code == 401
        assert "kompromittiert" in replay.json()["detail"]
        assert (await refresh(client, rotated.json()["refresh_token"])).status_code == 401

    async def test_revoke_session_does_not_erase_a_rotated_token(self, client, db):
        victim = await signup(client)
        rotated = await refresh(client, victim["refresh_token"])
        old_row = await token_row(db, victim["refresh_token"])

        res = await client.delete(
            f"/api/auth/sessions/{old_row.id}", headers=h(rotated.json()["access_token"]),
        )
        assert res.status_code == 204
        row = await token_row(db, victim["refresh_token"])
        assert row is not None and row.revoked is True


class TestLogoutWithoutAccessToken:
    """K151: Der Besitz des Refresh-Tokens genügt zum Widerruf."""

    async def test_logout_without_access_token(self, client, db):
        s = await signup(client)
        res = await client.post("/api/auth/logout", json={"refresh_token": s["refresh_token"]})
        assert res.status_code == 204
        assert (await refresh(client, s["refresh_token"])).status_code == 401
        count = (await db.execute(select(func.count()).select_from(RefreshToken))).scalar_one()
        assert count == 0

    async def test_logout_with_expired_access_token(self, client):
        s = await signup(client)
        res = await client.post(
            "/api/auth/logout", json={"refresh_token": s["refresh_token"]},
            headers=h("abgelaufen.oder.kaputt"),
        )
        assert res.status_code == 204
        assert (await refresh(client, s["refresh_token"])).status_code == 401

    async def test_logout_with_unknown_token_is_silent(self, client):
        s = await signup(client)
        res = await client.post("/api/auth/logout", json={"refresh_token": "gibt-es-nicht"})
        assert res.status_code == 204
        await assert_session_alive(client, s)

    async def test_logout_needs_the_refresh_token(self, client):
        s = await signup(client)
        res = await client.post("/api/auth/logout", json={}, headers=h(s["access_token"]))
        assert res.status_code == 422


class TestGetCurrentUserReleasesConnection:
    """K016: Nach der Authentifizierung ist keine Transaktion mehr offen."""

    async def test_no_open_transaction_after_auth(self, client, db):
        from auth import get_current_user

        s = await signup(client)
        await db.commit()
        assert not db.in_transaction()

        request = Request({
            "type": "http",
            "method": "GET",
            "path": "/api/auth/me",
            "query_string": b"",
            "headers": [(b"authorization", f"Bearer {s['access_token']}".encode())],
            "server": ("test", 80),
            "scheme": "http",
        })
        user = await get_current_user(request, db)

        assert not db.in_transaction()
        # Der Nutzer bleibt geladen: kein Lazy-Load auf der beendeten Transaktion.
        assert isinstance(user, User)
        assert user.email == EMAIL
        assert user.token_version == 0 and user.is_admin is False
        assert not db.in_transaction()
