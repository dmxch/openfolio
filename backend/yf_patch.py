"""Patch yfinance before any other module imports it.

Must be imported at the very top of main.py, before any service imports.
Fixes:
1. Daempft die "failed to get ticker"-Logspam von yfinance (aber nur bis WARNING —
   ab yfinance 1.x kommen ueber denselben Logger die Diagnose-Signale, die man
   wirklich braucht: Rate-Limit-Treffer, curl_cffi-Fallback, "may be delisted")
2. Suppresses Pandas4Warning deprecation spam from yfinance internals
3. Provides thread-safe yf_download()/yf_ticker_attr() wrappers for use with
   asyncio.to_thread()

SESSION-HANDLING (geaendert mit dem Sprung auf yfinance 1.x):
Frueher baute jeder Wrapper eine eigene `requests.Session` mit gesetztem
User-Agent, weil Yahoo den damaligen yfinance-Default (Chrome 39) mit 429
blockte. Beides ist ab 1.x falsch:

  * yfinance 1.x spricht ueber curl_cffi und imitiert einen echten Browser bis
    auf den TLS-Fingerprint (JA3). Eine untergeschobene `requests.Session` wird
    zwar klaglos AKZEPTIERT, sendet aber ohne diesen Fingerprint — also genau mit
    der Signatur, die Yahoo blockt. Das faellt nicht auf: kein Fehler, keine
    Warnung, nur langsam veraltende Kurse.
  * Ein eigener User-Agent-Header wuerde zusaetzlich nicht mehr zur Impersonation
    passen (UA/JA3-Mismatch) und selbst als Bot-Signal wirken.
  * `session=` war ohnehin nie per-Call isoliert: YfData ist ein prozessweiter
    Singleton, jedes `session=` setzt die Session GLOBAL um. Das anschliessende
    `session.close()` hinterliess also eine geschlossene Session im Singleton —
    unter curl_cffi wirft der naechste Zugriff darauf hart.

Deshalb wird jetzt gar keine Session mehr uebergeben: yfinance verwaltet seine
eigene (impersonierende) Session. Die Thread-Sicherheit kommt weiterhin ueber
`_ticker_lock` bzw. `threads=False` — das war schon vorher der wirksame Teil.
"""
import logging
import warnings

# NICHT auf CRITICAL: yfinance 1.x meldet Rate-Limits, Session-Fallbacks und
# "symbol may be delisted" auf WARNING/ERROR. Auf CRITICAL waeren genau die
# Signale unsichtbar, an denen man eine stille Degradation erkennen wuerde.
logging.getLogger("yfinance").setLevel(logging.WARNING)

import yfinance as yf  # noqa: E402
import yfinance.data as yfdata  # noqa: E402

if hasattr(yfdata.YfData, "_instances"):
    yfdata.YfData._instances = {}

# Must be set AFTER yfinance/pandas are imported, as they register their own filters
from pandas.errors import Pandas4Warning  # noqa: E402

warnings.filterwarnings("ignore", category=Pandas4Warning)


def yf_download(tickers, **kwargs):
    """Thread-safe wrapper for yf.download().

    Forces threads=False (yfinance internal threading conflicts with the asyncio
    thread pool). Session-Handling siehe Modul-Docstring: bewusst kein `session=`.
    """
    kwargs.setdefault("progress", False)
    kwargs["threads"] = False
    return yf.download(tickers, **kwargs)


import threading  # noqa: E402

# yf.Ticker-Zugriffe (.info/.fast_info/.calendar) teilen YfData._instances
# über Threads und sind NICHT thread-safe (Cross-Ticker-Datenverschmutzung,
# dokumentiert in unusual_volume_service). Ein Lock serialisiert die Zugriffe;
# Durchsatz ist hier unkritisch, Korrektheit nicht.
_ticker_lock = threading.Lock()


def yf_ticker_attr(ticker: str, attr: str):
    """Thread-safe access to yf.Ticker(...).<attr> (info, fast_info, calendar).

    Blocking — only call via asyncio.to_thread() from async context.
    Returns the attribute value or raises whatever yfinance raises.
    """
    with _ticker_lock:
        t = yf.Ticker(ticker)
        return getattr(t, attr)


def yf_search(query: str, **kwargs):
    """Thread-safe wrapper for yf.Search(...).

    Existiert, damit die Ticker-Suche denselben Session-/Lock-Pfad nimmt wie der
    Rest — sonst laeuft sie am Wrapper vorbei auf dem globalen YfData-Singleton.
    Blocking — only call via asyncio.to_thread() from async context.
    """
    with _ticker_lock:
        return yf.Search(query, **kwargs)


def yf_earnings_dates(ticker: str, limit: int = 16):
    """Thread-safe wrapper for yf.Ticker(...).get_earnings_dates(limit=...).

    Returns a pandas DataFrame (incl. column "Reported EPS") or None on
    failure. Blocking — only call via asyncio.to_thread() from async context
    (HEILIGE Regel 7). Serialized via the shared ticker lock (yfinance ticker
    state is not thread-safe).

    Hinweis: der Scrape-Pfad rundet `limit` intern auf 25/50/100 auf und
    schneidet nicht zurueck — es koennen also mehr Zeilen kommen als angefragt.
    Braucht lxml (pandas.read_html), deshalb steht lxml explizit in
    requirements.txt und nicht mehr nur transitiv ueber yfinance.
    """
    with _ticker_lock:
        t = yf.Ticker(ticker)
        return t.get_earnings_dates(limit=limit)


def yf_quote_currency(ticker: str) -> str | None:
    """Quote currency from yfinance fast_info ('GBp' for pence-quoted LSE).

    Returns None on any failure — callers must treat None as unknown.
    """
    try:
        fi = yf_ticker_attr(ticker, "fast_info")
        cur = getattr(fi, "currency", None) or (fi.get("currency") if hasattr(fi, "get") else None)
        return str(cur) if cur else None
    except Exception:
        return None
