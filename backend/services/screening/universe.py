"""Shared equity-universe resolver fuer Screening-/Quant-Pipelines.

Zentrale Helper-Funktion, die distinct(Position.ticker ∪ Watchlist.ticker)
auf US-Equities filtert. Positions: type=stock (kein ETF/Crypto/Cash/etc).
Watchlist: kein type-Filter (Watchlist hat heute keine type-Spalte — siehe
Backlog Iteration 4), nur Format-Heuristik gegen .SW/.L/.TO-Listings.

Verwender:
- services/quant/estimate_revisions_service.py
- (Iteration 2.5+) services/screening/sec_form4_service.py
"""
from __future__ import annotations

from sqlalchemy import distinct, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.position import AssetType, Position
from models.watchlist import WatchlistItem


async def resolve_equity_universe(db: AsyncSession) -> list[str]:
    """DISTINCT(Equity-Positions ∪ aktive Watchlist) ueber alle User.

    Positions: nur type=stock — alle anderen Asset-Klassen (etf, crypto,
    cash, commodity, pension, real_estate, private_equity) sind fuer
    FMP-Equity-Endpoints garantierte 404s.

    Watchlist: nur is_active=true. Kein type-Filter (Schema-Limitation),
    daher Format-Heuristik gegen `.`/`:` (Multi-Listing-Suffixe wie
    .SW/.L/.TO/.HK).
    """
    pos_q = select(distinct(Position.ticker)).where(
        Position.type == AssetType.stock
    )
    wl_q = select(distinct(WatchlistItem.ticker)).where(
        WatchlistItem.is_active.is_(True)
    )
    pos_rows = (await db.execute(pos_q)).scalars().all()
    wl_rows = (await db.execute(wl_q)).scalars().all()
    tickers = {(t or "").strip().upper() for t in pos_rows + wl_rows if t}
    return sorted(t for t in tickers if t and "." not in t and ":" not in t)
