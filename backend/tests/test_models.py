"""Tests for SQLAlchemy models — creation, defaults, constraints."""

import pytest
import pytest_asyncio
from datetime import datetime

from dateutils import utcnow
from models.user import User, UserSettings
from models.backup_code import BackupCode
from services.auth_service import hash_password, hash_backup_code

pytestmark = pytest.mark.asyncio


class TestUserModel:
    async def test_create_user(self, db):
        user = User(email="test@example.com", password_hash=hash_password("TestPass1"))
        db.add(user)
        await db.commit()
        await db.refresh(user)

        assert user.id is not None
        assert user.email == "test@example.com"
        assert user.is_active is True
        assert user.is_admin is False
        assert user.mfa_enabled is False
        assert user.force_password_change is False
        assert isinstance(user.created_at, datetime)

    async def test_user_settings_defaults(self, db):
        user = User(email="test@example.com", password_hash=hash_password("TestPass1"))
        db.add(user)
        await db.commit()
        await db.refresh(user)

        settings = UserSettings(user_id=user.id)
        db.add(settings)
        await db.commit()
        await db.refresh(settings)

        assert settings.base_currency == "CHF"
        assert settings.broker == "swissquote"
        assert settings.number_format == "ch"


class TestBackupCodeModel:
    async def test_create_backup_code(self, db):
        user = User(email="test@example.com", password_hash=hash_password("TestPass1"))
        db.add(user)
        await db.commit()
        await db.refresh(user)

        bc = BackupCode(user_id=user.id, code_hash=hash_backup_code("ABCD-1234"))
        db.add(bc)
        await db.commit()
        await db.refresh(bc)

        assert bc.id is not None
        assert bc.used is False
        assert bc.used_at is None
        assert isinstance(bc.created_at, datetime)

    async def test_backup_code_mark_used(self, db):
        user = User(email="test@example.com", password_hash=hash_password("TestPass1"))
        db.add(user)
        await db.commit()
        await db.refresh(user)

        bc = BackupCode(user_id=user.id, code_hash=hash_backup_code("ABCD-1234"))
        db.add(bc)
        await db.commit()

        bc.used = True
        bc.used_at = utcnow()
        await db.commit()
        await db.refresh(bc)

        assert bc.used is True
        assert bc.used_at is not None
