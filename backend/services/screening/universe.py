"""Shared equity-universe resolver fuer Screening-/Quant-Pipelines.

Zentrale Helper-Funktion, die distinct(Position.ticker ∪ Watchlist.ticker)
auf US-Equities filtert. Positions: type=stock (kein ETF/Crypto/Cash/etc).
Watchlist: type IS NULL OR type=stock (NULL = unbekannt, vermutlich Equity),
plus Format-Heuristik gegen .SW/.L/.TO-Listings und Crypto-Pair-Suffixe.

Verwender:
- services/quant/estimate_revisions_service.py
- services/screening/sec_form4_service.py
"""
from __future__ import annotations

from sqlalchemy import distinct, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.position import AssetType, Position
from models.watchlist import WatchlistItem

# Crypto-Quote-Pairs (CoinGecko-/yfinance-Stil: BTC-USD, ETH-EUR, SOL-USDT).
# Achtung: NUR diese Fiat-/Stablecoin-Suffixe filtern — US-Aktien wie BRK-B,
# BF-B (Berkshire/Brown-Forman B-Shares) haben ebenfalls einen Bindestrich
# und muessen drinbleiben.
_CRYPTO_QUOTE_SUFFIXES = ("-USD", "-EUR", "-GBP", "-USDT", "-USDC", "-BTC", "-ETH")


def classify_ticker_format(ticker: str) -> AssetType | None:
    """Leichtgewichtige Format-Klassifikation (kein Netzwerk).

    Erkennt heute nur Crypto-Quote-Pairs zuverlaessig. Alles andere bleibt
    NULL (unbekannt) — eine echte ETF-/Stock-Unterscheidung braucht einen
    Provider-Lookup (yfinance quoteType / FMP profile) und ist separater Scope.
    """
    t = (ticker or "").strip().upper()
    if not t:
        return None
    if any(t.endswith(suf) for suf in _CRYPTO_QUOTE_SUFFIXES):
        return AssetType.crypto
    return None


def _is_equity_format(t: str) -> bool:
    """True wenn der Ticker wie ein US-Equity-Symbol aussieht.

    Drop: Multi-Listing-Suffixe (. / :) und Crypto-Quote-Pairs. Faengt auch
    Legacy-Watchlist-Rows mit type=NULL, die in Wahrheit Crypto sind.
    """
    if not t:
        return False
    if "." in t or ":" in t:
        return False
    if any(t.endswith(suf) for suf in _CRYPTO_QUOTE_SUFFIXES):
        return False
    return True


async def resolve_equity_universe(db: AsyncSession) -> list[str]:
    """DISTINCT(Equity-Positions ∪ aktive Watchlist) ueber alle User.

    Positions: nur type=stock — alle anderen Asset-Klassen (etf, crypto,
    cash, commodity, pension, real_estate, private_equity) sind fuer
    FMP-Equity-Endpoints garantierte 404s.

    Watchlist: is_active=true UND (type IS NULL OR type=stock). Explizit als
    crypto/etf/… getaggte Eintraege fallen raus; NULL (unbekannt) bleibt drin
    und wird vom Format-Filter als Backstop geprueft.
    """
    pos_q = select(distinct(Position.ticker)).where(
        Position.type == AssetType.stock
    )
    wl_q = select(distinct(WatchlistItem.ticker)).where(
        WatchlistItem.is_active.is_(True),
        or_(WatchlistItem.type.is_(None), WatchlistItem.type == AssetType.stock),
    )
    pos_rows = (await db.execute(pos_q)).scalars().all()
    wl_rows = (await db.execute(wl_q)).scalars().all()
    tickers = {(t or "").strip().upper() for t in pos_rows + wl_rows if t}
    return sorted(t for t in tickers if _is_equity_format(t))
