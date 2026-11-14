from datetime import date

from sqlalchemy import BigInteger, Date, Index, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class PriceCache(Base):
    __tablename__ = "price_cache"
    __table_args__ = (
        UniqueConstraint("ticker", "date", name="uq_ticker_date"),
        Index("ix_price_cache_date", "date"),
    )

    # BIGINT: jeder INSERT ... ON CONFLICT zieht einen Sequenzwert, auch ohne neue
    # Zeile. SQLite zählt nur INTEGER PRIMARY KEY automatisch hoch.
    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer(), "sqlite"), primary_key=True, autoincrement=True
    )
    # Schlüssel des Kurses: Yahoo-Symbol oder Edelmetall-Ticker, für Krypto
    # «CG:<coingecko_id>» (cache_service.crypto_price_key), nie der frei
    # wählbare Positions-Ticker. Breite 60 seit Migration 100.
    ticker: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    # 8 Nachkommastellen: FX-Paare wie JPYCHF=X (~0.0052) haben mit 4 Stellen nur
    # zwei signifikante Ziffern. 10 Vorkommastellen wie zuvor.
    open: Mapped[float | None] = mapped_column(Numeric(18, 8))
    high: Mapped[float | None] = mapped_column(Numeric(18, 8))
    low: Mapped[float | None] = mapped_column(Numeric(18, 8))
    close: Mapped[float] = mapped_column(Numeric(18, 8), nullable=False)
    volume: Mapped[int | None] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="USD")
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="yahoo")
