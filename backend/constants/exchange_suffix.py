"""Mapping Issuer-Exchange-Name -> yfinance-Ticker-Suffix + Ticker-Normalisierung.

iShares-Holdings-CSVs identifizieren Bestandteile NUR ueber lokalen Boersen-Ticker
+ Exchange-Spalte (keine ISIN). Um die Holdings auf yfinance-kompatible Ticker
(fuer classify_tickers_bulk -> Sektor-Look-Through) abzubilden, wird die
Exchange-Spalte deterministisch auf ein Yahoo-Suffix gemappt.

Validiert am EIMI-Holdings-CSV (iShares Core MSCI EM IMI, 3060 Equity-Holdings):
100 % des Equity-Gewichts mappen mit dieser Tabelle auf ein Suffix.

WICHTIG: Reihenfolge = spezifisch vor generisch (z.B. "kosdaq" -> .KQ VOR
"korea" -> .KS, sonst landen KOSDAQ-Titel faelschlich auf .KS).
"""
from __future__ import annotations

# (Substring-Keyword in lowercase, Yahoo-Suffix). "" = US-Listing (kein Suffix).
EXCHANGE_SUFFIX: list[tuple[str, str]] = [
    # -- spezifisch zuerst --
    ("kosdaq", ".KQ"),
    ("gretai", ".TWO"),                 # Taipei Exchange / OTC (Alt-Name)
    ("taipei", ".TWO"),
    ("korea exchange (kosdaq)", ".KQ"),
    # -- Hauptboersen --
    ("taiwan", ".TW"),
    ("hong kong", ".HK"),
    ("korea", ".KS"),
    ("national stock exchange of india", ".NS"),
    ("bombay", ".BO"),
    ("bse ltd", ".BO"),
    ("shanghai", ".SS"),
    ("shenzhen", ".SZ"),
    ("xbsp", ".SA"),                    # B3 Brasilien (MIC-Code)
    ("sao paulo", ".SA"),
    ("b3", ".SA"),
    ("brazil", ".SA"),
    ("johannesburg", ".JO"),
    ("saudi", ".SR"),
    ("tadawul", ".SR"),
    ("mexic", ".MX"),
    ("thailand", ".BK"),
    ("bursa malaysia", ".KL"),
    ("malaysia", ".KL"),
    ("indonesia", ".JK"),
    ("istanbul", ".IS"),
    ("turkey", ".IS"),
    ("warsaw", ".WA"),
    ("poland", ".WA"),
    ("philippine", ".PS"),
    ("qatar", ".QA"),
    ("abu dhabi", ".AD"),
    ("dubai", ".DU"),
    ("kuwait", ".KW"),
    ("athens", ".AT"),
    ("greece", ".AT"),
    ("santiago", ".SN"),
    ("chile", ".SN"),
    ("budapest", ".BD"),
    ("prague", ".PR"),
    ("egyptian", ".CA"),
    ("egypt", ".CA"),
    ("colombia", ".CL"),
    ("xetra", ".DE"),
    ("frankfurt", ".DE"),
    ("london", ".L"),
    # -- US / ADR (kein Suffix) --
    ("nasdaq", ""),
    ("new york", ""),
    ("nyse", ""),
    ("cboe", ""),
    ("bats", ""),
    ("arca", ""),
    ("united states", ""),
]


def exchange_to_suffix(exchange: str | None) -> str | None:
    """Yahoo-Suffix fuer einen Exchange-Namen. None = unbekannte Boerse."""
    e = (exchange or "").strip().lower()
    if not e:
        return None
    for kw, suf in EXCHANGE_SUFFIX:
        if kw in e:
            return suf
    return None


def exchange_to_yf_ticker(local_ticker: str | None, exchange: str | None) -> str | None:
    """Lokaler Boersen-Ticker + Exchange -> yfinance-Ticker, oder None bei
    unbekannter Boerse / leerem Ticker.

    Normalisierung:
    - US (Suffix ""): Ticker unveraendert (gross/getrimmt).
    - Hong Kong (.HK): numerischen Code links auf 4 Stellen mit Nullen auffuellen
      ("700" -> "0700.HK"), yfinance-Konvention.
    - sonst: Ticker + Suffix.
    """
    t = (local_ticker or "").strip().upper()
    if not t:
        return None
    suf = exchange_to_suffix(exchange)
    if suf is None:
        return None
    if suf == "":
        return t
    if suf == ".HK" and t.isdigit() and len(t) < 4:
        t = t.zfill(4)
    return f"{t}{suf}"
