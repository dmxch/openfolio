import uuid
from datetime import datetime

from dateutils import utcnow
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class ImportBucketRule(Base):
    """Auto-Mapping-Regel fuer Bucket-Zuordnung bei CSV-Imports.

    Erste passende Regel (nach priority asc) gewinnt — wenn weder source noch
    ticker_pattern matcht, faellt der Import auf liquid_default oder den im
    Import-Wizard gewaehlten Bucket zurueck.
    """

    __tablename__ = "import_bucket_rules"
    __table_args__ = (
        CheckConstraint(
            "source IS NOT NULL OR ticker_pattern IS NOT NULL",
            name="ck_import_bucket_rules_at_least_one_filter",
        ),
        Index("idx_import_bucket_rules_user_priority", "user_id", "priority"),
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
    source: Mapped[str | None] = mapped_column(String(40))
    ticker_pattern: Mapped[str | None] = mapped_column(String(60))
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, nullable=False
    )
