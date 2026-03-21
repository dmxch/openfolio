import uuid

from sqlalchemy import Column, ForeignKey, String, Table
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


# Association table
watchlist_item_tags = Table(
    "watchlist_item_tags",
    Base.metadata,
    Column("watchlist_item_id", UUID(as_uuid=True), ForeignKey("watchlist.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", UUID(as_uuid=True), ForeignKey("watchlist_tags.id", ondelete="CASCADE"), primary_key=True),
)


class WatchlistTag(Base):
    __tablename__ = "watchlist_tags"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(30), nullable=False)
    color: Mapped[str | None] = mapped_column(String(7))
