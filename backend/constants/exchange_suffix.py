"""Mapping Issuer-Exchange-Name -> yfinance-Ticker-Suffix + Ticker-Normalisierung.

iShares-Holdings-CSVs identifizieren Bestandteile NUR ueber lokalen Boersen-Ticker
+ Exchange-Spalte (keine ISIN). Um die Holdings auf yfinance-kompatible Ticker
(fuer classify_tickers_bulk -> Sektor-Look-Through) abzubilden, wird die
Exchange-Spalte deterministisch auf ein Yahoo-Suffix gemappt.

Validiert am EIMI-Holdings-CSV (iShares Core MSCI EM IMI, 3060 Equity-Holdings):
100 % des Equity-Gewichts mappen mit dieser Tabelle auf ein Suffix.

WICHTIG: Reihenfolge = spezifisch vor generisch (z.B. "kosdaq" -> .KQ VOR
"korea" -> .KS, sonst landen KOSDAQ-Titel faelschlich auf .KS). Dasselbe gilt
fuer die US-Keywords: "Nyse Euronext - Euronext Paris" und "Nasdaq Omx Helsinki"
enthalten "nyse" bzw. "nasdaq" und muessen VOR dem US-Block treffen, sonst
landen europaeische Titel als nackte US-Ticker in etf_holdings (LVMH "MC" =
Moelis, Schneider "SU" = Suncor).
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
    # -- Industrielaender (MSCI World). Muss vor dem US-Block stehen. --
    ("swiss", ".SW"),                   # SIX Swiss Exchange
    ("paris", ".PA"),                   # Nyse Euronext - Euronext Paris
    ("amsterdam", ".AS"),
    ("brussels", ".BR"),
    ("lisbon", ".LS"),
    ("irish", ".IR"),                   # Irish Stock Exchange / Euronext Dublin
    ("dublin", ".IR"),
    ("copenhagen", ".CO"),              # Omx Nordic Exchange Copenhagen A/S
    ("helsinki", ".HE"),                # Nasdaq Omx Helsinki Ltd.
    ("stockholm", ".ST"),
    ("iceland", ".IC"),
    ("omx nordic", ".ST"),              # "Nasdaq Omx Nordic" ohne Ort = Stockholm
    ("oslo", ".OL"),
    ("madrid", ".MC"),
    ("bolsas y mercados", ".MC"),       # BME, Bolsas y Mercados Espanoles
    ("borsa italiana", ".MI"),
    ("milan", ".MI"),
    ("wiener", ".VI"),
    ("vienna", ".VI"),
    ("tel aviv", ".TA"),
    ("tokyo", ".T"),
    ("toronto", ".TO"),
    ("asx", ".AX"),                     # Asx - All Markets
    ("australia", ".AX"),
    ("new zealand", ".NZ"),
    ("singapore", ".SI"),
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


# Bloomberg 2-Buchstaben-Composite-Exchange-Code -> yfinance-Suffix. Genutzt von
# Adaptern, deren Holdings-Feed einen Bloomberg-Ticker "SYMBOL CC" traegt (Amundi
# `bbg`, teils JPMorgan). NUR eindeutige Codes; mehrdeutige weggelassen (Row faellt
# dann auf den ISIN-Key zurueck). WICHTIG: BB "SS"=Stockholm(.ST), NICHT Shanghai;
# BB "SW"/"VX"=SIX Swiss(.SW). Bei Bedarf erweitern.
BLOOMBERG_COMPOSITE_SUFFIX: dict[str, str] = {
    "US": "", "UN": "", "UW": "", "UQ": "", "UA": "", "UR": "",  # US (Composite/NYSE/Nasdaq/Amex/Arca)
    "C1": ".SS", "C2": ".SZ",                                # China A (Shanghai/Shenzhen Connect)
    "LN": ".L",                                              # London
    "GY": ".DE", "GR": ".DE", "GF": ".DE",                   # Xetra / Germany / Frankfurt
    "FP": ".PA",                                             # Euronext Paris
    "NA": ".AS",                                             # Euronext Amsterdam
    "BB": ".BR",                                             # Euronext Brussels
    "IM": ".MI",                                             # Borsa Italiana
    "SM": ".MC",                                             # Madrid (BME)
    "PL": ".LS",                                             # Euronext Lisbon
    "SW": ".SW", "VX": ".SW",                                # SIX Swiss / virt-x
    "SS": ".ST",                                             # Stockholm (NICHT Shanghai)
    "DC": ".CO",                                             # Copenhagen
    "NO": ".OL",                                             # Oslo
    "FH": ".HE",                                             # Helsinki
    "AV": ".VI",                                             # Vienna
    "SP": ".SI",                                             # Singapore
    "HK": ".HK",                                             # Hong Kong
    "JP": ".T", "JT": ".T",                                  # Tokyo
    "TT": ".TW",                                             # Taiwan
    "KP": ".KS", "KS": ".KS",                                # Korea (KOSPI)
    "KQ": ".KQ",                                             # KOSDAQ
    "AT": ".AX", "AU": ".AX",                                # Australia (ASX)
    "CT": ".TO", "CN": ".TO",                                # Canada (Toronto)
    "IS": ".NS", "IN": ".NS",                                # India (NSE)
    "IB": ".BO",                                             # India (BSE)
    "BZ": ".SA",                                             # Brazil (B3)
    "SJ": ".JO",                                             # Johannesburg
    "TB": ".BK",                                             # Thailand
    "MK": ".KL",                                             # Malaysia (Bursa)
    "IJ": ".JK",                                             # Indonesia
    "TI": ".IS",                                             # Turkey (Istanbul)
    "PW": ".WA",                                             # Poland (Warsaw)
    "MM": ".MX",                                             # Mexico
    "AB": ".AD",                                             # Abu Dhabi
    "QD": ".QA",                                             # Qatar
    "AR": ".SR",                                             # Saudi (Tadawul)
}


def bloomberg_composite_to_yf(bbg: str | None) -> str | None:
    """Bloomberg-Ticker "SYMBOL CC" (z.B. "2330 TT", "ASML NA") -> yfinance-Ticker,
    None bei unbekanntem/fehlendem Composite-Code.

    HK: numerischen Code links auf 4 Stellen mit Nullen auffuellen (yfinance-Konvention).
    """
    s = (bbg or "").strip().upper()
    if not s or " " not in s:
        return None
    sym, _, cc = s.rpartition(" ")
    sym = sym.strip()
    cc = cc.strip()
    if not sym or cc not in BLOOMBERG_COMPOSITE_SUFFIX:
        return None
    suf = BLOOMBERG_COMPOSITE_SUFFIX[cc]
    if suf == "":
        return sym
    if suf == ".HK" and sym.isdigit() and len(sym) < 4:
        sym = sym.zfill(4)
    return f"{sym}{suf}"


# Boersen, an denen Yahoo die Aktienklasse mit Bindestrich abtrennt.
_HYPHEN_CLASS_SUFFIXES = frozenset({".ST", ".CO", ".HE", ".OL", ".TO", ".L"})


def exchange_to_yf_ticker(local_ticker: str | None, exchange: str | None) -> str | None:
    """Lokaler Boersen-Ticker + Exchange -> yfinance-Ticker, oder None bei
    unbekannter Boerse / leerem Ticker.

    Normalisierung:
    - US (Suffix ""): Ticker unveraendert (gross/getrimmt).
    - Hong Kong (.HK): numerischen Code links auf 4 Stellen mit Nullen auffuellen
      ("700" -> "0700.HK"), yfinance-Konvention.
    - Abschliessender Punkt faellt weg (London "BP." -> "BP.L").
    - Aktienklassen an nordischen Boersen, in Toronto und London: Yahoo trennt
      sie mit Bindestrich, die Issuer-CSV mit Leerzeichen, Punkt oder
      Schraegstrich ("ATCO A" -> "ATCO-A.ST", "TECK.B" -> "TECK-B.TO").
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
    t = t.rstrip(".")
    if not t:
        return None
    if suf == ".HK" and t.isdigit() and len(t) < 4:
        t = t.zfill(4)
    if suf in _HYPHEN_CLASS_SUFFIXES:
        for sep in (" ", ".", "/"):
            t = t.replace(sep, "-")
    return f"{t}{suf}"
