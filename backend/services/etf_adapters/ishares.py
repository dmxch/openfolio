"""iShares-Adapter — delegiert an den bestehenden keylosen CSV-Fetcher.

Matcht ETFs, deren Ticker in der gepflegten iShares-URL-Registry steht
(constants.etf_holdings_sources.ISHARES_HOLDINGS_URLS). Die Row-Erzeugung liegt
unveraendert in services.etf_holdings_ishares (parse_ishares_csv), damit die
bestehenden Tests + Live-Verhalten (SWDA/EIMI/CHSPI) exakt gleich bleiben.
"""
from __future__ import annotations

from constants.etf_holdings_sources import ISHARES_HOLDINGS_URLS
from services.etf_adapters.base import EtfAdapter, EtfRef, register
from services.etf_holdings_ishares import fetch_ishares_holdings


class IsharesAdapter(EtfAdapter):
    name = "iShares"

    def matches(self, ref: EtfRef) -> bool:
        return ref.ticker in ISHARES_HOLDINGS_URLS

    async def fetch(self, ref: EtfRef) -> list[dict] | None:
        return await fetch_ishares_holdings(ref.ticker)


register(IsharesAdapter())
