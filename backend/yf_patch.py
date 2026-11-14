"""Patch yfinance before any other module imports it.

Must be imported at the very top of main.py, before any service imports.
Fixes:
1. Daempft die "failed to get ticker"-Logspam von yfinance (aber nur bis WARNING —
   ab yfinance 1.x kommen ueber denselben Logger die Diagnose-Signale, die man
   wirklich braucht: Rate-Limit-Treffer, curl_cffi-Fallback, "may be delisted")
2. Suppresses Pandas4Warning deprecation spam from yfinance internals
3. Provides thread-safe yf_download()/yf_ticker_attr() wrappers for use with
   asyncio.to_thread() bzw. yf_to_thread() (eigener kleiner Thread-Pool fuer
   die Ticker-Abrufe, die ueber `_ticker_lock` serialisiert sind)
4. Prueft jedes Symbol gegen MARKET_TICKER_PATTERN, bevor es an Yahoo geht

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
import asyncio
import contextlib
import contextvars
import functools
import logging
import threading
import warnings
from collections.abc import Callable, Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor
from typing import Any

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

import pandas as pd  # noqa: E402

from api.validation import is_market_ticker  # noqa: E402

logger = logging.getLogger(__name__)


def _valid_symbols(tickers: str | Iterable[str], caller: str) -> list[str]:
    """Symbole einzeln gegen MARKET_TICKER_PATTERN pruefen, Rest verwerfen.

    yfinance trennt eine Zeichenkette an Komma und Leerzeichen: ein einziger
    Wert wie "A,B,C,…" wird so zu hunderten sequenziellen Yahoo-Abrufen. Der
    Wrapper kann eine vom Code verbundene Zeichenkette nicht von einer
    Nutzereingabe unterscheiden. Deshalb gilt: eine Zeichenkette ist genau EIN
    Symbol, ein Listenelement ebenso. Mehrere Symbole kommen als Liste. Ein Wert
    mit Komma oder Leerzeichen faellt hier durch die Pruefung, statt
    aufgefaechert zu werden.
    """
    candidates = [tickers] if isinstance(tickers, str) else list(tickers)
    valid = [c for c in candidates if is_market_ticker(c)]
    if len(valid) != len(candidates):
        example = next(c for c in candidates if not is_market_ticker(c))
        # Gekuerzt und per %r: der Wert kann aus einem Request stammen.
        logger.warning(
            "%s: dropped %d invalid ticker symbol(s), e.g. %r",
            caller, len(candidates) - len(valid), str(example)[:40],
        )
    return list(dict.fromkeys(valid))


def _require_symbol(ticker: str) -> str:
    if not is_market_ticker(ticker):
        raise ValueError("invalid ticker symbol")
    return ticker


# Kursspalten, die yfinance fuer ein gescheitertes Symbol liefert (utils.empty_df).
_EMPTY_PRICE_FIELDS = ("Open", "High", "Low", "Close", "Adj Close", "Volume")


def _empty_download(candidates: list, kwargs: dict[str, Any]) -> pd.DataFrame:
    """Leerer Frame in der Form, die yf.download fuer gescheiterte Symbole liefert.

    Keine Zeilen, aber die Kursspalten je angefragtem Symbol. Ein Frame ganz
    ohne Spalten ist fuer Aufrufer etwas anderes als ein Symbol ohne Kurse: die
    Reihenbauer in history_service und snapshot_service brechen bei genau einem
    Symbol ohne Close-Spalte ab, statt mit leerer Kursreihe weiterzulaufen.

    Die Symbole stehen wie bei yfinance in Grossbuchstaben in den Spalten,
    ``group_by`` und ``multi_level_index`` wirken wie dort.
    """
    labels = list(dict.fromkeys(c.upper() for c in candidates if isinstance(c, str)))
    if not labels:
        return pd.DataFrame()
    by_ticker = kwargs.get("group_by", "column") != "column"
    data = pd.DataFrame(
        index=pd.DatetimeIndex([]),
        columns=pd.MultiIndex.from_product(
            [labels, _EMPTY_PRICE_FIELDS], names=["Ticker", "Price"]
        ),
        dtype="float64",
    )
    if not by_ticker:
        data.columns = data.columns.swaplevel(0, 1)
        data = data.sort_index(level=0, axis=1)
    if not kwargs.get("multi_level_index", True) and len(labels) == 1:
        data = data.droplevel(0 if by_ticker else 1, axis=1).rename_axis(None, axis=1)
    return data


def yf_download(tickers: str | Iterable[str], **kwargs):
    """Thread-safe wrapper for yf.download().

    Forces threads=False (yfinance internal threading conflicts with the asyncio
    thread pool). Session-Handling siehe Modul-Docstring: bewusst kein `session=`.

    Nimmt eine Liste von Symbolen oder eine Zeichenkette mit genau EINEM Symbol.
    Eine Zeichenkette wird nicht an Komma oder Leerzeichen geteilt: "A B" und
    "A,B" sind ungueltig. Ungueltige Symbole werden mit einer Warnung verworfen
    (siehe ``_valid_symbols``); yfinance bekommt immer eine Liste. Bleibt kein
    Symbol uebrig, wird Yahoo nicht gefragt. Zurueck kommt dann ein leerer
    DataFrame wie fuer ein Symbol ohne Kurse (siehe ``_empty_download``).
    """
    candidates = [tickers] if isinstance(tickers, str) else list(tickers)
    symbols = _valid_symbols(candidates, "yf_download")
    if not symbols:
        return _empty_download(candidates, kwargs)
    kwargs.setdefault("progress", False)
    kwargs["threads"] = False
    return yf.download(symbols, **kwargs)


# yf.Ticker-Zugriffe (.info/.fast_info/.calendar) teilen YfData._instances
# über Threads und sind NICHT thread-safe (Cross-Ticker-Datenverschmutzung,
# dokumentiert in unusual_volume_service). Ein Lock serialisiert die Zugriffe;
# Durchsatz ist hier unkritisch, Korrektheit nicht.
_ticker_lock = threading.Lock()

# Das Lock bleibt waehrend des Netzabrufs gehalten (yfinance-Timeout 30 s). Ohne
# Frist stapeln sich Wartende und belegen je einen Thread des Default-Executors,
# den auch Portfolio-Summary, Kurse und FX brauchen. Nach der Frist wirft der
# Aufruf YfTickerLockTimeout — fuer den Aufrufer ein fehlgeschlagener Abruf wie
# jeder andere Yahoo-Fehler.
_TICKER_LOCK_TIMEOUT_S = 20.0

# Eigener kleiner Pool fuer die serialisierten Ticker-Abrufe (yf_to_thread): ein
# Thread haelt das Lock, hoechstens zwei warten daran. Weitere Abrufe stehen in
# der Queue des Pools und belegen keinen Thread.
_ticker_executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="yf-ticker")


class YfTickerLockTimeout(TimeoutError):
    """Das Ticker-Lock war innerhalb von _TICKER_LOCK_TIMEOUT_S nicht frei."""


@contextlib.contextmanager
def _ticker_locked() -> Iterator[None]:
    if not _ticker_lock.acquire(timeout=_TICKER_LOCK_TIMEOUT_S):
        raise YfTickerLockTimeout(
            f"yfinance ticker lock busy for more than {_TICKER_LOCK_TIMEOUT_S:.0f}s"
        )
    try:
        yield
    finally:
        _ticker_lock.release()


async def yf_to_thread(func: Callable[..., Any], /, *args: Any, **kwargs: Any) -> Any:
    """Wie ``asyncio.to_thread``, aber im eigenen Pool fuer Ticker-Abrufe.

    Fuer alles, was am Ticker-Lock haengt (``yf_ticker_attr``, ``yf_fast_info``,
    ``yf_search``, ``yf_earnings_dates``, ``yf_quote_currency``). Der
    Default-Executor bleibt so fuer Cache- und DB-Arbeit frei.
    """
    loop = asyncio.get_running_loop()
    ctx = contextvars.copy_context()
    return await loop.run_in_executor(
        _ticker_executor, functools.partial(ctx.run, func, *args, **kwargs)
    )


def yf_ticker_attr(ticker: str, attr: str):
    """Thread-safe access to yf.Ticker(...).<attr> (info, calendar, dividends).

    Blocking — only call via yf_to_thread() from async context.
    Returns the attribute value or raises whatever yfinance raises. Raises
    ValueError for an invalid symbol and YfTickerLockTimeout when the lock
    stays busy.

    Nicht fuer ``fast_info``: das Objekt laedt erst beim Feldzugriff, also nach
    Freigabe des Locks. Dafuer gibt es ``yf_fast_info``.
    """
    _require_symbol(ticker)
    with _ticker_locked():
        t = yf.Ticker(ticker)
        return getattr(t, attr)


def yf_fast_info(ticker: str, fields: Iterable[str]) -> dict[str, Any]:
    """Liest ``fields`` aus yf.Ticker(...).fast_info, solange das Lock gehalten ist.

    fast_info ist traege: jede Property loest beim ersten Zugriff ihren eigenen
    Yahoo-Abruf aus. Wer das Objekt aus ``yf_ticker_attr`` herausreicht, liest
    die Felder nach Freigabe des Locks — unserialisiert. Hier passieren die
    Abrufe unter dem Lock, zurueck kommt ein einfaches dict.

    Ein Feld, das fast_info nicht kennt, ist ``None``. Blocking; wirft, was
    yfinance wirft, dazu ValueError und YfTickerLockTimeout wie
    ``yf_ticker_attr``.
    """
    _require_symbol(ticker)
    with _ticker_locked():
        fast_info = yf.Ticker(ticker).fast_info
        return {field: getattr(fast_info, field, None) for field in fields}


def yf_search(query: str, **kwargs):
    """Thread-safe wrapper for yf.Search(...).

    Existiert, damit die Ticker-Suche denselben Session-/Lock-Pfad nimmt wie der
    Rest — sonst laeuft sie am Wrapper vorbei auf dem globalen YfData-Singleton.
    Blocking — only call via yf_to_thread() from async context. ``query`` ist
    Freitext und wird nicht als Symbol geprueft.
    """
    with _ticker_locked():
        return yf.Search(query, **kwargs)


def yf_earnings_dates(ticker: str, limit: int = 16):
    """Thread-safe wrapper for yf.Ticker(...).get_earnings_dates(limit=...).

    Returns a pandas DataFrame (incl. column "Reported EPS") or None on
    failure. Blocking — only call via yf_to_thread() from async context
    (HEILIGE Regel 7). Serialized via the shared ticker lock (yfinance ticker
    state is not thread-safe).

    Hinweis: der Scrape-Pfad rundet `limit` intern auf 25/50/100 auf und
    schneidet nicht zurueck — es koennen also mehr Zeilen kommen als angefragt.
    Braucht lxml (pandas.read_html), deshalb steht lxml explizit in
    requirements.txt und nicht mehr nur transitiv ueber yfinance.
    """
    _require_symbol(ticker)
    with _ticker_locked():
        t = yf.Ticker(ticker)
        return t.get_earnings_dates(limit=limit)


def yf_quote_currency(ticker: str) -> str | None:
    """Quote currency from yfinance fast_info ('GBp' for pence-quoted LSE).

    Returns None on any failure — callers must treat None as unknown.
    """
    try:
        cur = yf_fast_info(ticker, ("currency",))["currency"]
        return str(cur) if cur else None
    except Exception:
        return None
