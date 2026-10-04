"""Security hardening Block C: registration default, atomic invite redemption."""

import uuid

import pytest
from sqlalchemy import delete, func, select, update

from models.app_setting import AppSetting, InviteCode
from models.user import User

pytestmark = pytest.mark.asyncio

PW = "TestPassw0rd!2026"


async def set_mode(db, mode):
    await db.execute(update(AppSetting).where(AppSetting.key == "registration_mode").values(value=mode))
    await db.commit()


async def add_invite(db, code="INVITE-1"):
    db.add(InviteCode(code=code, created_by=uuid.uuid4()))
    await db.commit()
    return code


async def user_count(db):
    return (await db.execute(select(func.count()).select_from(User))).scalar_one()


class TestDefaultMode:
    async def test_missing_setting_falls_back_to_invite_only(self, client, db):
        await db.execute(delete(AppSetting).where(AppSetting.key == "registration_mode"))
        await db.commit()
        res = await client.get("/api/auth/registration-mode")
        assert res.json()["mode"] == "invite_only"
        res = await client.post("/api/auth/register", json={"email": "a@example.com", "password": PW})
        assert res.status_code == 400
        assert await user_count(db) == 0


class TestInviteRedemption:
    async def test_code_works_exactly_once(self, client, db):
        await set_mode(db, "invite_only")
        code = await add_invite(db)
        first = await client.post("/api/auth/register", json={"email": "a@example.com", "password": PW, "invite_code": code})
        assert first.status_code == 201, first.text
        second = await client.post("/api/auth/register", json={"email": "b@example.com", "password": PW, "invite_code": code})
        assert second.status_code == 400
        assert await user_count(db) == 1
        inv = (await db.execute(select(InviteCode).execution_options(populate_existing=True))).scalars().one()
        assert inv.is_active is False and str(inv.used_by) == first.json()["user_id"]

    async def test_lost_race_rolls_back_user(self, client, db, monkeypatch):
        """Simulate a concurrent redemption between the invite lookup and the
        conditional UPDATE: the second registration must not create a user."""
        await set_mode(db, "invite_only")
        code = await add_invite(db)

        import api.auth as auth_api
        real_validate = auth_api.validate_password

        def validate_and_steal(pw):
            # Runs after the invite SELECT, before the UPDATE — mark it as used.
            from sqlalchemy import update as sa_update
            stmt = sa_update(InviteCode).where(InviteCode.code == code).values(is_active=False, used_by=uuid.uuid4())
            pending.append(stmt)
            return real_validate(pw)

        pending = []
        monkeypatch.setattr(auth_api, "validate_password", validate_and_steal)
        orig_flush = db.flush

        async def flush_then_steal(*a, **kw):
            await orig_flush(*a, **kw)
            while pending:
                await db.execute(pending.pop())

        monkeypatch.setattr(db, "flush", flush_then_steal)
        res = await client.post("/api/auth/register", json={"email": "a@example.com", "password": PW, "invite_code": code})
        assert res.status_code == 400
        monkeypatch.setattr(db, "flush", orig_flush)
        assert await user_count(db) == 0
