"""User service: shared operations like user deletion."""

import json
import logging
import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.user import User, RefreshToken, UserSettings
from models.transaction import Transaction
from models.position import Position
from models.watchlist import WatchlistItem
from models.watchlist_tag import WatchlistTag
from models.price_alert import PriceAlert
from models.alert_preference import AlertPreference
from models.property import Property
from models.smtp_config import SmtpConfig
from models.fx_transaction import FxTransaction
from models.password_reset_token import PasswordResetToken
from models.backup_code import BackupCode
from models.precious_metal_item import PreciousMetalItem
from models.portfolio_snapshot import PortfolioSnapshot
from models.import_profile import ImportProfile
from models.etf_sector_weight import EtfSectorWeight
from models.private_equity import PrivateEquityHolding
from models.admin_audit_log import AdminAuditLog

logger = logging.getLogger(__name__)


async def _detach_audit_entries(db: AsyncSession, user_id: uuid.UUID) -> None:
    """Audit-Einträge eines Admins vom Konto lösen statt löschen (K161).

    Sonst tilgt ein Admin mit der Löschung des eigenen Kontos seine Spuren. Die
    E-Mail wandert in ``details``, damit der Eintrag ohne admin_id lesbar bleibt.
    admin_id wird hier ausdrücklich geleert und nicht dem Fremdschlüssel
    (ON DELETE SET NULL) überlassen: SQLite setzt ihn in den Tests nicht durch.
    """
    entries = (await db.execute(
        select(AdminAuditLog).where(AdminAuditLog.admin_id == user_id)
    )).scalars().all()
    if not entries:
        return
    user = await db.get(User, user_id)
    for entry in entries:
        if user is not None:
            try:
                payload = json.loads(entry.details) if entry.details else {}
            except ValueError:
                payload = {"raw": entry.details}
            if not isinstance(payload, dict):
                payload = {"value": payload}
            payload["admin_email"] = user.email
            entry.details = json.dumps(payload)
        entry.admin_id = None
    # Vor dem DELETE auf users schreiben, unabhängig von der Flush-Reihenfolge.
    await db.flush()


async def delete_user(db: AsyncSession, user_id: uuid.UUID) -> None:
    """Delete a user and all their data. Covers all user_id FK tables."""
    # Delete in dependency order (children before parents)
    await db.execute(delete(PrivateEquityHolding).where(PrivateEquityHolding.user_id == user_id))
    await _detach_audit_entries(db, user_id)
    await db.execute(delete(Transaction).where(Transaction.user_id == user_id))
    await db.execute(delete(EtfSectorWeight).where(EtfSectorWeight.user_id == user_id))
    await db.execute(delete(Position).where(Position.user_id == user_id))
    await db.execute(delete(PriceAlert).where(PriceAlert.user_id == user_id))
    await db.execute(delete(WatchlistTag).where(WatchlistTag.user_id == user_id))
    await db.execute(delete(WatchlistItem).where(WatchlistItem.user_id == user_id))
    await db.execute(delete(Property).where(Property.user_id == user_id))
    await db.execute(delete(AlertPreference).where(AlertPreference.user_id == user_id))
    await db.execute(delete(FxTransaction).where(FxTransaction.user_id == user_id))
    await db.execute(delete(SmtpConfig).where(SmtpConfig.user_id == user_id))
    await db.execute(delete(UserSettings).where(UserSettings.user_id == user_id))
    await db.execute(delete(RefreshToken).where(RefreshToken.user_id == user_id))
    await db.execute(delete(PasswordResetToken).where(PasswordResetToken.user_id == user_id))
    await db.execute(delete(BackupCode).where(BackupCode.user_id == user_id))
    await db.execute(delete(PreciousMetalItem).where(PreciousMetalItem.user_id == user_id))
    await db.execute(delete(PortfolioSnapshot).where(PortfolioSnapshot.user_id == user_id))
    await db.execute(delete(ImportProfile).where(ImportProfile.user_id == user_id))

    # Delete the user itself
    user = await db.get(User, user_id)
    if user:
        await db.delete(user)
