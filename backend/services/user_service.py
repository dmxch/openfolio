"""User service: shared operations like user deletion."""

import logging
import uuid

from sqlalchemy import delete
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


async def delete_user(db: AsyncSession, user_id: uuid.UUID) -> None:
    """Delete a user and all their data. Covers all user_id FK tables."""
    # Delete in dependency order (children before parents)
    await db.execute(delete(PrivateEquityHolding).where(PrivateEquityHolding.user_id == user_id))
    await db.execute(delete(AdminAuditLog).where(AdminAuditLog.admin_id == user_id))
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
