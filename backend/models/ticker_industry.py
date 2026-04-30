"""Ticker → TradingView industry mapping (UPSERT, no history).

Daily-refreshed from the existing TradingView stock-level scan in
``services.tradingview_industries_service.fetch_stock_aggregates_by_industry``,
which already paginates through all ~12k US-stocks. We persist the
``(ticker, industry)`` pairs here so the Smart-Money screener can join
hits against the same TradingView industry taxonomy used by
``MarketIndustry`` rotation snapshots.

PK is the ticker — one row per ticker, replaced on each daily refresh.
History is intentionally not kept; if a ticker disappears (delisting),
its row eventually goes stale and is filtered by the optional
``industry_name NOT IN MarketIndustry.name`` stale-detection cron.
"""
from datetime import datetime

from dateutils import utcnow
from sqlalchemy import DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class TickerIndustry(Base):
    """One row per US-ticker, mapping to its TradingView industry display name."""

    __tablename__ = "ticker_industries"

    ticker: Mapped[str] = mapped_column(String(30), primary_key=True)
    industry_name: Mapped[str] = mapped_column(String(200), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)

    __table_args__ = (
        Index("ix_ticker_industries_industry_name", "industry_name"),
    )
