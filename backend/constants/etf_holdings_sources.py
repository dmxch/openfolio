"""Registry: ETF-Ticker -> iShares-Holdings-CSV-URL (keyloser .ajax-Endpoint).

Die iShares-URL traegt eine fund-spezifische numerische Product-ID + eine
domain-weite Magic-Number (uk: 1506575576011, ch: 1495092304805), die NICHT aus
Ticker/ISIN ableitbar sind — daher ein gepflegtes Mapping statt eines Templates.

Neue ETFs ergaenzen: Produktseite oeffnen (ggf. mit ?siteEntryPassthrough=true,
um das Investor-Type-Interstitial zu umgehen), den "Detailed Holdings"-CSV-Link
kopieren. Der .ajax-CSV-Endpoint selbst ist ungated (Browser-User-Agent noetig,
sonst 403 Akamai — siehe services/etf_holdings_ishares.py).

Alle URLs am 27.6.2026 live verifiziert (HTTP 200, parsbare Holdings-CSV).
"""
from __future__ import annotations

ISHARES_HOLDINGS_URLS: dict[str, str] = {
    # iShares Core MSCI EM IMI UCITS ETF (IE00BKM4GZ66) — EM, ~3100 Holdings
    "EIMI.L": (
        "https://www.ishares.com/uk/individual/en/products/264659/"
        "ishares-msci-emerging-markets-imi-ucits-etf/1506575576011.ajax"
        "?fileType=csv&fileName=EIMI_holdings&dataType=fund"
    ),
    # iShares Core MSCI World UCITS ETF (IE00B4L5Y983)
    "SWDA.L": (
        "https://www.ishares.com/uk/individual/en/products/251882/"
        "ishares-msci-world-ucits-etf-acc-fund/1506575576011.ajax"
        "?fileType=csv&fileName=SWDA_holdings&dataType=fund"
    ),
    # iShares Core SPI ETF (CH0237935652) — Schweizer Markt
    "CHSPI.SW": (
        "https://www.ishares.com/ch/individual/en/products/264107/"
        "ishares-spi-ch-fund/1495092304805.ajax"
        "?fileType=csv&fileName=CHSPI_holdings&dataType=fund"
    ),
}
