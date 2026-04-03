import uuid
from datetime import datetime

from dateutils import utcnow
from sqlalchemy import DateTime, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class NewsArticle(Base):
    """A news article fetched for a specific ticker."""
    __tablename__ = "news_articles"
    __table_args__ = (
        UniqueConstraint("ticker", "url", name="uq_news_ticker_url"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ticker: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    url: Mapped[str] = mapped_column(String(1000), nullable=False)
    source: Mapped[str | None] = mapped_column(String(100))
    snippet: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    ai_summary: Mapped[str | None] = mapped_column(Text)
    ai_sentiment: Mapped[str | None] = mapped_column(String(20))
