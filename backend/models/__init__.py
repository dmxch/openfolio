from models.base import Base
from models.position import Position
from models.transaction import Transaction
from models.price_cache import PriceCache
from models.watchlist import WatchlistItem
from models.property import Property, Mortgage, PropertyExpense, PropertyIncome
from models.user import User, RefreshToken, UserSettings
from models.etf_sector_weight import EtfSectorWeight
from models.alert_preference import AlertPreference
from models.smtp_config import SmtpConfig
from models.macro_indicator_cache import MacroIndicatorCache
from models.password_reset_token import PasswordResetToken
from models.app_setting import AppSetting, InviteCode
from models.backup_code import BackupCode
from models.import_profile import ImportProfile
from models.precious_metal_item import PreciousMetalItem
from models.precious_metal_expense import PreciousMetalExpense, PreciousMetalExpenseCategory
from models.app_config import AppConfig
from models.admin_audit_log import AdminAuditLog
from models.price_alert import PriceAlert
from models.watchlist_tag import WatchlistTag
from models.fx_transaction import FxTransaction
from models.portfolio_snapshot import PortfolioSnapshot
from models.screening import ScreeningScan, ScreeningResult
from models.api_token import ApiToken
from models.macro_cot import MacroCotSnapshot
from models.fund_holdings import FundHoldingsSnapshot
from models.market_industry import MarketIndustry
from models.ticker_industry import TickerIndustry
from models.etf_holding import EtfHolding
from models.pending_dividend import PendingDividend
from models.api_write_log import ApiWriteLog
from models.ntfy_config import NtfyConfig
from models.pending_order import PendingOrder
from models.bucket import (
    Bucket,
    BucketKind,
    BucketSystemRole,
    BucketSnapshot,
    BucketAlertLog,
    PositionBucketHistory,
    SYSTEM_BUCKET_NAMES,
)
from models.import_bucket_rule import ImportBucketRule
from models.form4_transaction import Form4Transaction
from models.estimate_revision import EstimateRevision
from models.report import Report
# WICHTIG: Jedes Model-Modul MUSS hier importiert sein, sonst fehlt die
# Tabelle in Base.metadata → alembic autogenerate generiert DROP TABLE
# und create_all-basierte Setups (seed, Tests) bauen sie nicht
# (Review 2026-06-10, H4 — private_equity fehlte).
from models.private_equity import (
    PrivateEquityHolding,
    PrivateEquityValuation,
    PrivateEquityDividend,
)

__all__ = [
    "Base", "Position", "Transaction", "PriceCache", "WatchlistItem",
    "Property", "Mortgage", "PropertyExpense", "PropertyIncome",
    "User", "RefreshToken", "UserSettings", "EtfSectorWeight",
    "AlertPreference", "SmtpConfig", "MacroIndicatorCache",
    "PasswordResetToken", "AppSetting", "InviteCode", "BackupCode",
    "ImportProfile", "PreciousMetalItem", "PreciousMetalExpense",
    "PreciousMetalExpenseCategory", "AppConfig", "AdminAuditLog",
    "PriceAlert", "WatchlistTag", "FxTransaction", "PortfolioSnapshot",
    "ScreeningScan", "ScreeningResult", "ApiToken",
    "MacroCotSnapshot", "FundHoldingsSnapshot", "MarketIndustry",
    "TickerIndustry", "EtfHolding", "PendingDividend", "ApiWriteLog",
    "NtfyConfig", "PendingOrder",
    "Bucket", "BucketKind", "BucketSystemRole", "BucketSnapshot",
    "BucketAlertLog", "PositionBucketHistory", "SYSTEM_BUCKET_NAMES",
    "ImportBucketRule",
    "Form4Transaction", "EstimateRevision", "Report",
    "PrivateEquityHolding", "PrivateEquityValuation", "PrivateEquityDividend",
]
