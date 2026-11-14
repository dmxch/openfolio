"""Vollreview 11/2026, Welle 3, Fixer «misc»: K152 entschärft.

Der öffentlich bekannte Null-Schlüssel bleibt zum Lesen im Ring, bis der
Betreiber ihn mit LEGACY_NULL_KEY_ENABLED=false abschaltet. Jede Entschlüsselung
an diesem Schlüssel warnt. scripts/vr11_reencrypt_legacy_fields.py zählt die
betroffenen Werte und verschlüsselt sie neu.
"""

from __future__ import annotations

import base64
import logging
import uuid
from datetime import date
from decimal import Decimal

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import Text, select

from config import Settings
from models.position import AssetType, Position
from models.smtp_config import SmtpConfig
from models.transaction import Transaction, TransactionType
from models.user import User, UserSettings
from scripts import vr11_reencrypt_legacy_fields as script
from services import auth_service
from services.bucket_service import create_system_buckets, get_liquid_default_bucket
from services.encryption_helpers import decrypt_field

SECRET = "JBSWY3DPEHPK3PXP"


def _null_key_ciphertext(plain: str) -> str:
    """Chiffrat mit dem Schlüssel, den ein leerer LEGACY_ENCRYPTION_KEY ergab: 32 Nullen."""
    return Fernet(base64.urlsafe_b64encode(b"0" * 32)).encrypt(plain.encode()).decode()


@pytest.fixture(autouse=True)
def _no_legacy_env_key(monkeypatch):
    monkeypatch.setattr(auth_service, "_LEGACY_DEFAULT_KEY", "")


# --- Ring ---------------------------------------------------------------------


class TestNullKeyRing:
    def test_setting_defaults_to_enabled(self):
        assert Settings.model_fields["legacy_null_key_enabled"].default is True

    def test_setting_reads_the_environment_variable(self, monkeypatch):
        monkeypatch.setenv("LEGACY_NULL_KEY_ENABLED", "false")
        assert Settings().legacy_null_key_enabled is False
        monkeypatch.setenv("LEGACY_NULL_KEY_ENABLED", "true")
        assert Settings().legacy_null_key_enabled is True

    def test_null_key_values_stay_readable_by_default(self):
        """Welle 2 nahm den Schlüssel sofort aus dem Ring: Altwerte wären verloren."""
        token = _null_key_ciphertext(SECRET)
        assert auth_service.decrypt_value(token) == SECRET
        assert auth_service.decrypt_totp_secret(token) == SECRET
        assert decrypt_field(token) == SECRET

    def test_null_key_decryption_warns_without_plaintext(self, caplog):
        token = _null_key_ciphertext(SECRET)
        with caplog.at_level(logging.WARNING, logger="services.auth_service"):
            auth_service.decrypt_value(token)
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1
        message = warnings[0].getMessage()
        assert "null legacy key" in message
        assert "vr11_reencrypt_legacy_fields.py" in message
        assert SECRET not in caplog.text
        assert token not in caplog.text

    def test_current_key_decryption_does_not_warn(self, caplog):
        token = auth_service.encrypt_value(SECRET)
        with caplog.at_level(logging.DEBUG, logger="services.auth_service"):
            assert auth_service.decrypt_value(token) == SECRET
        assert not [r for r in caplog.records if r.levelno >= logging.INFO]

    def test_switched_off_null_key_is_rejected(self, monkeypatch):
        monkeypatch.setattr(auth_service.settings, "legacy_null_key_enabled", False)
        token = _null_key_ciphertext(SECRET)
        with pytest.raises(ValueError):
            auth_service.decrypt_value(token)
        with pytest.raises(ValueError):
            auth_service.decrypt_totp_secret(token)
        # decrypt_field fällt auf den gespeicherten Wert zurück, nie auf den Klartext.
        assert decrypt_field(token) == token

    def test_null_key_is_not_part_of_the_legacy_list(self):
        """Die Liste trägt nur geheime Schlüssel; der Null-Schlüssel hat seinen eigenen Schalter."""
        assert len(auth_service._get_legacy_fernets()) == 1

    def test_key_kind_is_reported(self, monkeypatch):
        monkeypatch.setattr(auth_service, "_LEGACY_DEFAULT_KEY", "old-installation-key")
        legacy = auth_service._derive_legacy_fernet("old-installation-key").encrypt(b"x").decode()

        assert auth_service.decrypt_with_key_kind(auth_service.encrypt_value("x")) == ("x", "current")
        assert auth_service.decrypt_with_key_kind(legacy) == ("x", "legacy")
        assert auth_service.decrypt_with_key_kind(_null_key_ciphertext("x")) == ("x", "null")
        with pytest.raises(ValueError):
            auth_service.decrypt_with_key_kind("kein-chiffrat")

    def test_script_mode_reads_null_key_values_after_the_switch_off(self, monkeypatch):
        monkeypatch.setattr(auth_service.settings, "legacy_null_key_enabled", False)
        token = _null_key_ciphertext("x")
        assert auth_service.decrypt_with_key_kind(token, include_null_key=True) == ("x", "null")
        with pytest.raises(ValueError):
            auth_service.decrypt_with_key_kind(token)

    async def test_startup_migration_reencrypts_null_key_values(self, db):
        """Die drei Spalten der Start-Migration hängen nach dem ersten Start nicht mehr am Null-Schlüssel."""
        user = User(email="mig@test.local", password_hash="x", totp_secret=_null_key_ciphertext(SECRET))
        db.add(user)
        await db.commit()

        migrated, errors = await auth_service.migrate_encrypted_values()
        assert (migrated, errors) == (1, 0)

        stored = (await db.execute(
            select(User.totp_secret).where(User.id == user.id)
        )).scalar_one()
        assert auth_service.decrypt_with_key_kind(stored) == (SECRET, "current")


# --- Skript -------------------------------------------------------------------


async def _seed(db) -> dict:
    user = User(email=f"u{uuid.uuid4().hex[:8]}@test.local", password_hash="x",
                totp_secret=_null_key_ciphertext(SECRET))
    db.add(user)
    await db.commit()
    await db.refresh(user)
    db.add(UserSettings(
        user_id=user.id, noticed_buckets_migration=True,
        fmp_api_key=_null_key_ciphertext("fmp-key"),
        fred_api_key=auth_service.encrypt_value("fred-key"),
    ))
    db.add(SmtpConfig(
        user_id=user.id, host="smtp.example.org", port=587, username="u",
        password_encrypted=_null_key_ciphertext("smtp-pw"), from_email="u@example.org",
    ))
    await db.commit()
    await create_system_buckets(db, user.id)
    bucket = await get_liquid_default_bucket(db, user.id)
    pos = Position(
        user_id=user.id, bucket_id=bucket.id, ticker="ACME", name="Acme", type=AssetType.stock,
        currency="CHF", shares=Decimal("1"), cost_basis_chf=Decimal("100"),
        notes=_null_key_ciphertext("geheime Notiz"),
        iban="CH93 0076 2011 6238 5295 7",  # Klartext-Altwert
        bank_name=auth_service.encrypt_value("Kantonalbank"),
    )
    db.add(pos)
    await db.commit()
    await db.refresh(pos)
    for note in (_null_key_ciphertext("Notiz 1"), _null_key_ciphertext("Notiz 2"),
                 auth_service.encrypt_value("Notiz 3"), None, ""):
        db.add(Transaction(
            user_id=user.id, position_id=pos.id, type=TransactionType.buy, date=date(2024, 1, 2),
            shares=Decimal("1"), price_per_share=Decimal("100"), currency="CHF",
            fx_rate_to_chf=Decimal("1"), fees_chf=Decimal("0"), taxes_chf=Decimal("0"),
            total_chf=Decimal("100"), notes=note,
        ))
    await db.commit()
    return {"user": user, "position": pos}


def _by_column(report: dict) -> dict[str, dict]:
    return {f"{c['table']}.{c['column']}": c for c in report["columns"]}


class TestReencryptScript:
    def test_listed_columns_exist_and_are_text(self):
        seen = set()
        for model, column_names in script.ENCRYPTED_COLUMNS:
            for name in column_names:
                column = model.__table__.c[name]
                assert isinstance(column.type, Text), f"{model.__tablename__}.{name}"
                seen.add((model.__tablename__, name))
        # Stichprobe über die Kategorien aus .claude/skills/standards: IBAN, Bank,
        # Seriennummer, Lagerort, Notizen, Adressen, PE-Firmendaten, API-Keys,
        # SMTP-Passwort, TOTP-Secret, ntfy-Token.
        for expected in (
            ("positions", "iban"), ("positions", "bank_name"), ("positions", "notes"),
            ("precious_metal_items", "serial_number"), ("precious_metal_items", "storage_location"),
            ("transactions", "notes"), ("watchlist", "notes"), ("pending_orders", "notes"),
            ("properties", "address"), ("mortgages", "bank"), ("property_income", "tenant"),
            ("private_equity_holdings", "company_name"), ("private_equity_holdings", "uid_number"),
            ("user_settings", "fred_api_key"), ("user_settings", "fmp_api_key"),
            ("user_settings", "finnhub_api_key"), ("smtp_config", "password_encrypted"),
            ("ntfy_config", "access_token_encrypted"), ("users", "totp_secret"),
        ):
            assert expected in seen

    async def test_dry_run_counts_per_table_and_column_and_writes_nothing(self, db):
        seeded = await _seed(db)
        before = (await db.execute(select(Transaction.id, Transaction.notes))).all()

        report = await script.reencrypt(db, apply=False)

        assert report["applied"] is False
        assert report["null_key_total"] == 6
        cols = _by_column(report)
        assert cols["users.totp_secret"]["null_key"] == 1
        assert cols["user_settings.fmp_api_key"]["null_key"] == 1
        assert cols["user_settings.fred_api_key"] == {
            "table": "user_settings", "column": "fred_api_key",
            "checked": 1, "null_key": 0, "legacy_key": 0, "reencrypted": 0,
        }
        assert cols["smtp_config.password_encrypted"]["null_key"] == 1
        assert cols["positions.notes"]["null_key"] == 1
        assert cols["positions.iban"]["null_key"] == 0  # Klartext-Altwert: nicht Sache des Skripts
        assert cols["positions.bank_name"]["null_key"] == 0
        assert cols["transactions.notes"]["checked"] == 3  # None und "" zählen nicht
        assert cols["transactions.notes"]["null_key"] == 2
        assert all(c["reencrypted"] == 0 for c in report["columns"])

        after = (await db.execute(select(Transaction.id, Transaction.notes))).all()
        assert after == before
        pos = (await db.execute(
            select(Position).where(Position.id == seeded["position"].id).execution_options(populate_existing=True)
        )).scalars().one()
        assert auth_service.decrypt_with_key_kind(pos.notes)[1] == "null"

    async def test_apply_reencrypts_only_null_key_values(self, db, monkeypatch):
        seeded = await _seed(db)
        bank_before = seeded["position"].bank_name

        report = await script.reencrypt(db, apply=True)
        assert report["null_key_total"] == 6
        assert sum(c["reencrypted"] for c in report["columns"]) == 6

        pos = (await db.execute(
            select(Position).where(Position.id == seeded["position"].id).execution_options(populate_existing=True)
        )).scalars().one()
        assert auth_service.decrypt_with_key_kind(pos.notes) == ("geheime Notiz", "current")
        assert pos.iban == "CH93 0076 2011 6238 5295 7"
        assert pos.bank_name == bank_before  # Werte am aktuellen Schlüssel bleiben

        notes = (await db.execute(select(Transaction.notes).order_by(Transaction.created_at, Transaction.id))).scalars().all()
        plain = sorted(auth_service.decrypt_with_key_kind(n)[0] for n in notes if n)
        assert plain == ["Notiz 1", "Notiz 2", "Notiz 3"]
        assert all(auth_service.decrypt_with_key_kind(n)[1] == "current" for n in notes if n)

        # Nach dem Lauf lässt sich der Null-Schlüssel abschalten, alles bleibt lesbar.
        monkeypatch.setattr(auth_service.settings, "legacy_null_key_enabled", False)
        user = (await db.execute(
            select(User).where(User.id == seeded["user"].id).execution_options(populate_existing=True)
        )).scalars().one()
        assert auth_service.decrypt_totp_secret(user.totp_secret) == SECRET
        smtp = (await db.execute(
            select(SmtpConfig).execution_options(populate_existing=True)
        )).scalars().one()
        assert auth_service.decrypt_value(smtp.password_encrypted) == "smtp-pw"

        # Idempotent: der zweite Lauf findet nichts mehr.
        again = await script.reencrypt(db, apply=True)
        assert again["null_key_total"] == 0
        assert sum(c["reencrypted"] for c in again["columns"]) == 0

    async def test_script_works_after_the_switch_off(self, db, monkeypatch):
        """Hat der Betreiber zu früh abgeschaltet, holt das Skript die Werte trotzdem zurück."""
        await _seed(db)
        monkeypatch.setattr(auth_service.settings, "legacy_null_key_enabled", False)
        report = await script.reencrypt(db, apply=True)
        assert report["null_key_total"] == 6
        assert sum(c["reencrypted"] for c in report["columns"]) == 6

    async def test_report_prints_counts_but_no_secrets(self, db, capsys):
        await _seed(db)
        report = await script.reencrypt(db, apply=False)
        script._print_report(report)
        out = capsys.readouterr().out
        assert "transactions.notes" in out
        assert "6 Werte öffnet nur der Null-Schlüssel." in out
        assert "Dry-Run" in out
        for secret in (SECRET, "fmp-key", "smtp-pw", "geheime Notiz", "Notiz 1"):
            assert secret not in out
        assert "gAAAA" not in out  # kein Chiffrat

    async def test_report_tells_when_the_switch_off_is_safe(self, db, capsys):
        report = await script.reencrypt(db, apply=False)
        script._print_report(report)
        out = capsys.readouterr().out
        assert "Kein Wert hängt am Null-Schlüssel." in out
        assert "LEGACY_NULL_KEY_ENABLED=false" in out
