import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from dateutils import utcnow
from sqlalchemy import (
    JSON,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

# JSONB in Production (PostgreSQL), JSON-Fallback fuer SQLite-Tests.
_BUCKET_RISK_RULES_TYPE = JSON().with_variant(JSONB(), "postgresql")

from models.base import Base


class BucketKind(str, enum.Enum):
    user = "user"
    system = "system"


class BucketSystemRole(str, enum.Enum):
    liquid_default = "liquid_default"
    real_estate = "real_estate"
    private_equity = "private_equity"
    pension = "pension"


SYSTEM_BUCKET_NAMES: dict[BucketSystemRole, str] = {
    BucketSystemRole.liquid_default: "Alle Positionen",
    BucketSystemRole.real_estate: "Immobilien",
    BucketSystemRole.private_equity: "Private Equity",
    BucketSystemRole.pension: "Vorsorge",
}


class Bucket(Base):
    __tablename__ = "buckets"
    __table_args__ = (
        Index(
            "uq_bucket_user_name_active",
            "user_id",
            "name",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
            sqlite_where=text("deleted_at IS NULL"),
        ),
        Index("idx_buckets_user_kind", "user_id", "kind"),
        Index(
            "idx_buckets_user_system_role",
            "user_id",
            "system_role",
            unique=True,
            postgresql_where=text("system_role IS NOT NULL"),
            sqlite_where=text("system_role IS NOT NULL"),
        ),
        CheckConstraint(
            "(target_pct IS NULL) OR (target_chf IS NULL)",
            name="ck_buckets_target_xor",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    # native_enum=False: speichert als VARCHAR (passt zum Migration-Schema),
    # validiert die Werte aber im Python-Layer.
    kind: Mapped[BucketKind] = mapped_column(
        Enum(BucketKind, native_enum=False, length=10),
        nullable=False,
        default=BucketKind.user,
    )
    system_role: Mapped[BucketSystemRole | None] = mapped_column(
        Enum(BucketSystemRole, native_enum=False, length=20),
        nullable=True,
    )
    color: Mapped[str | None] = mapped_column(String(7))  # Hex
    benchmark: Mapped[str | None] = mapped_column(String(20))
    target_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    target_chf: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    description: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(default=0, nullable=False)
    risk_rules: Mapped[dict | None] = mapped_column(_BUCKET_RISK_RULES_TYPE)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )


class PositionBucketHistory(Base):
    __tablename__ = "position_bucket_history"
    __table_args__ = (
        Index("idx_pbh_position", "position_id", "changed_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    position_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("positions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    from_bucket_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("buckets.id", ondelete="SET NULL"), nullable=True
    )
    to_bucket_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("buckets.id", ondelete="CASCADE"), nullable=False
    )
    changed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    changed_by: Mapped[str] = mapped_column(String(20), nullable=False, default="user")
    note: Mapped[str | None] = mapped_column(Text)


class BucketSnapshot(Base):
    __tablename__ = "bucket_snapshots"
    __table_args__ = (
        UniqueConstraint("user_id", "bucket_id", "date", name="uq_bucket_snapshot"),
        Index("idx_bucket_snapshot_bucket_date", "bucket_id", "date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    bucket_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("buckets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    total_value_chf: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, default=Decimal("0")
    )
    cash_chf: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, default=Decimal("0")
    )
    net_cash_flow_chf: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, default=Decimal("0")
    )
    running_peak_chf: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, default=Decimal("0")
    )


class BucketAlertLog(Base):
    __tablename__ = "bucket_alert_log"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "bucket_id", "alert_type", "alert_date",
            name="uq_bucket_alert_log",
        ),
        Index("idx_bucket_alert_user_date", "user_id", "alert_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    bucket_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("buckets.id", ondelete="CASCADE"),
        nullable=False,
    )
    alert_type: Mapped[str] = mapped_column(String(40), nullable=False)
    alert_date: Mapped[date] = mapped_column(Date, nullable=False)
    triggered_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, nullable=False
    )
