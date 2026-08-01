"""Benchmark index returns — monthly (heatmap) + exact-window (like-for-like)."""

import bisect
import logging
from datetime import date

import pandas as pd

from services import cache
from yf_patch import yf_download

logger = logging.getLogger(__name__)

CACHE_TTL = 86400  # 24h

# Sentinel + kurzes TTL fuer "Notierungswaehrung nicht ermittelbar" — siehe
# benchmark_quote_currency. Kein leerer String: der waere von "kein Cache-Eintrag"
# nicht unterscheidbar.
_CURRENCY_UNKNOWN = "__unknown__"
CURRENCY_UNKNOWN_TTL = 900  # 15 min

BENCHMARK_NAMES: dict[str, str] = {
    "^GSPC": "S&P 500",
    "^IXIC": "NASDAQ",
    "^STOXX50E": "Euro Stoxx 50",
    "^SSMI": "SMI",
    "URTH": "MSCI World",
    "MTUM": "MSCI USA Momentum",
}


def get_benchmark_name(ticker: str) -> str:
    """Anzeigename eines Benchmark-Tickers (Fallback: Ticker selbst)."""
    return BENCHMARK_NAMES.get(ticker, ticker)


def get_benchmark_monthly_returns(ticker: str = "^GSPC") -> dict:
    """Calculate monthly returns for a benchmark index — **in CHF**.

    Waehrung (seit 1.8.2026): Die Kursreihe wird vor der Monatsgruppierung mit
    dem FX-Kurs des jeweiligen Stichtags nach CHF umgerechnet
    (``_closes_in_chf``). Vorher kam die Reihe in Notierungswaehrung, wurde in
    der UI aber neben CHF-Portfolio-Monatsrenditen gestellt — dieselbe
    Waehrungsmischung wie bei ``get_benchmark_window_return`` (siehe dort).
    Fehlt Notierungswaehrung oder FX, gibt es leere Listen statt einer
    waehrungsgemischten Reihe.

    Returns:
        {"months": [{"year": 2024, "month": 1, "return_pct": 2.5}, ...],
         "annual_totals": {2024: 12.3, ...},
         "ticker": "^GSPC", "name": "S&P 500", "currency": "CHF"}
    """
    # Schluessel bewusst umbenannt (_chf): unter dem alten liegen bis zu 24 h
    # lang Reihen in Notierungswaehrung. Ohne Umbenennung liefe der Deploy
    # einen Tag lang gegen alte Zahlen im selben Feld.
    cache_key = f"benchmark_monthly_chf:{ticker}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    names = BENCHMARK_NAMES

    def _empty() -> dict:
        return {
            "months": [], "annual_totals": {}, "ticker": ticker,
            "name": names.get(ticker, ticker), "currency": "CHF",
        }

    try:
        closes = _closes_in_chf(ticker)
        if not closes:
            logger.warning(f"No benchmark data (CHF) for {ticker}")
            return _empty()

        # Group by year-month, take last close per month
        monthly = []
        by_month: dict[tuple[int, int], list[float]] = {}
        for dt, px in closes:
            by_month.setdefault((dt.year, dt.month), []).append(px)

        sorted_months = sorted(by_month.keys())
        prev_close = None
        for year, month in sorted_months:
            prices = by_month[(year, month)]
            month_close = prices[-1]  # Last trading day close
            if prev_close is not None and prev_close > 0:
                ret = (month_close / prev_close - 1) * 100
                monthly.append({"year": year, "month": month, "return_pct": round(ret, 2)})
            prev_close = month_close

        # Annual totals: compound monthly returns per year
        annual_totals: dict[int, float] = {}
        for year in set(m["year"] for m in monthly):
            compound = 1.0
            for m in monthly:
                if m["year"] == year:
                    compound *= (1 + m["return_pct"] / 100)
            annual_totals[year] = round((compound - 1) * 100, 2)

        result = {
            "months": monthly,
            "annual_totals": annual_totals,
            "ticker": ticker,
            "name": names.get(ticker, ticker),
            "currency": "CHF",
        }
        cache.set(cache_key, result, ttl=CACHE_TTL)
        return result

    except Exception as e:
        logger.warning(f"Benchmark monthly returns failed for {ticker}: {e}")
        return _empty()


def _get_benchmark_closes(ticker: str) -> list[tuple[date, float]] | None:
    """Taegliche Schlusskurse eines Index als (date, close)-Liste, aufsteigend.

    Gecacht pro Ticker (nicht pro Fenster), damit ein einziger 5y-Download alle
    Fenster-Returns eines Tages bedient — sonst churnt der Cache, weil das
    Fenster-Ende (heute) taeglich weiterwandert und jeder Tag einen Miss + neuen
    Download je aktivem Bucket ausloeste.
    """
    cache_key = f"benchmark_closes:{ticker}"
    cached = cache.get(cache_key)
    if cached is not None:
        return [(date.fromisoformat(d), c) for d, c in cached]

    # Kalter Cache: nur EIN Thread laedt, die uebrigen warten auf sein Ergebnis.
    # Ohne das loest ein Dashboard-Aufruf pro Bucket einen eigenen Download
    # derselben Reihe aus — seit die Waehrungsumrechnung zusaetzlich die
    # FX-Reihen zieht, teilen sich noch mehr Aufrufer dieselben Keys
    # (USDCHF=X fuer vier der sechs Benchmarks). Parallele yfinance-Bursts sind
    # die dokumentierte Ursache stundenlanger IP-Sperren.
    with cache.single_flight(cache_key) as leader:
        # Double-Check in BEIDEN Zweigen: zwischen dem Cache-Read oben und dem
        # Eintritt hier kann ein anderer Leader komplett fertig geworden sein
        # (inkl. Cache-Write). Ohne den Re-Check laedt der frisch gewaehlte
        # Leader eine Reihe, die schon dasteht.
        cached = cache.get(cache_key)
        if cached is not None:
            return [(date.fromisoformat(d), c) for d, c in cached]
        if not leader:
            # Leader ist gescheitert — nicht hinterherlaufen, sonst rennt bei
            # dauerhaftem Fehler doch wieder jeder Thread ins offene Messer.
            # Der Fehlschlag wird bewusst NICHT negativ gecacht: der naechste
            # nicht-gleichzeitige Request versucht es erneut.
            return None
        return _download_benchmark_closes(ticker, cache_key)


def _download_benchmark_closes(
    ticker: str, cache_key: str
) -> list[tuple[date, float]] | None:
    """Eigentlicher Download + Cache-Write. Laeuft nur im Leader-Thread."""
    try:
        data = yf_download(ticker, period="5y", progress=False)
        if data is None or data.empty:
            return None
        close_raw = data["Close"]
        if hasattr(close_raw, "columns"):
            close_raw = close_raw.iloc[:, 0] if len(close_raw.columns) == 1 else close_raw[ticker]
        close = close_raw.dropna()
        if close.empty:
            return None
        # Index auf tz-naive Tagesstempel normalisieren (tz-aware vs. naive).
        idx = pd.to_datetime(close.index)
        if getattr(idx, "tz", None) is not None:
            idx = idx.tz_localize(None)
        series = sorted((ts.date(), float(v)) for ts, v in zip(idx, close.to_numpy()))
        cache.set(cache_key, [[d.isoformat(), c] for d, c in series], ttl=CACHE_TTL)
        return series
    except Exception as e:
        logger.warning(f"Benchmark close series failed for {ticker}: {e}")
        return None


def _last_close_on_or_before(series: list[tuple[date, float]], d: date) -> float | None:
    """Letzter Close mit Datum <= d (series aufsteigend sortiert)."""
    i = bisect.bisect_right(series, d, key=lambda s: s[0])
    return series[i - 1][1] if i > 0 else None


def benchmark_quote_currency(ticker: str) -> str | None:
    """Notierungswaehrung eines Benchmark-Tickers (24h gecacht, aendert sich nie).

    NIE aus dem Suffix raten — das Suffix sagt nichts ueber die Waehrung (siehe
    ``yf_quote_currency`` / GBX-Regel). ``None`` = unbekannt; der Caller muss
    dann lieber **gar keine** Zahl liefern als eine waehrungsgemischte.

    Auch **Fehlschlaege** werden gecacht (kurzes TTL). ``yf_quote_currency``
    geht ueber den info/quote-Endpunkt und haelt dabei den globalen Ticker-Lock:
    ist der Endpunkt gerade 429-gebannt (waehrend chart/ weiterlaeuft), wuerde
    sonst *jeder* Request erneut in denselben Timeout laufen — serialisiert, mit
    Latenz mal Anzahl Buckets. Ein Negativ-Cache begrenzt das auf einen Versuch
    pro Fenster, ohne die Erholung nennenswert zu verzoegern.
    """
    cache_key = f"benchmark_currency:{ticker}"
    cached = cache.get(cache_key)
    if cached:
        return None if cached == _CURRENCY_UNKNOWN else cached
    from yf_patch import yf_quote_currency
    cur = yf_quote_currency(ticker)
    if cur:
        # yfinance liefert Pence mal als "GBp", mal als "GBX" — auf eine Form
        # normalisieren, sonst laeuft _series_in_chf auf "GBXCHF=X" ins Leere
        # (spiegelt cache_service._quote_currency).
        if cur.upper() == "GBX":
            cur = "GBp"
        cache.set(cache_key, cur, ttl=CACHE_TTL)
        return cur
    cache.set(cache_key, _CURRENCY_UNKNOWN, ttl=CURRENCY_UNKNOWN_TTL)
    return None


def _series_in_chf(
    series: list[tuple[date, float]], currency: str
) -> list[tuple[date, float]] | None:
    """Ganze ``(date, price)``-Reihe nach CHF, FX je Stichtag.

    GBp (Pence-Notierung) wird auf GBP normalisiert — Faktor 100, nicht aus dem
    Suffix geraten. Die FX-Reihe kommt ueber dieselbe gecachte Download-Funktion
    wie die Kursreihe (ein Download pro Waehrung und Tag) und wird mit demselben
    "letzter Kurs am-oder-vor"-Anker gelesen, damit Kurs- und FX-Seite nicht
    gegeneinander verrutschen.

    Tage ohne FX-Kurs (typisch: Reihenanfang, wenn die FX-Historie kuerzer ist)
    fallen raus statt in Fremdwaehrung stehenzubleiben. ``None``, wenn gar kein
    FX beschaffbar ist — der Caller liefert dann lieber keine Zahl als eine
    waehrungsgemischte.
    """
    if currency == "GBp":
        series = [(d, p / 100) for d, p in series]
        currency = "GBP"
    if currency == "CHF":
        return series
    fx_series = _get_benchmark_closes(f"{currency}CHF=X")
    if not fx_series:
        return None
    out: list[tuple[date, float]] = []
    for d, p in series:
        fx = _last_close_on_or_before(fx_series, d)
        if fx and fx > 0:
            out.append((d, p * fx))
    return out or None


def _closes_in_chf(ticker: str) -> list[tuple[date, float]] | None:
    """Kursreihe eines Benchmarks in CHF — gemeinsamer Pfad beider Konsumenten.

    ``None``, wenn Reihe, Notierungswaehrung oder FX fehlen. Eine fehlende Zahl
    ist sichtbar, eine still waehrungsgemischte nicht.
    """
    series = _get_benchmark_closes(ticker)
    if not series:
        return None
    currency = benchmark_quote_currency(ticker)
    if currency is None:
        logger.warning(
            "Benchmark %s: Notierungswaehrung unbekannt — keine Rendite "
            "(statt einer waehrungsgemischten Zahl)", ticker,
        )
        return None
    chf = _series_in_chf(series, currency)
    if chf is None:
        logger.warning("Benchmark %s: kein FX-Kurs %s→CHF", ticker, currency)
    return chf


def get_benchmark_window_return(ticker: str, start: date, end: date) -> float | None:
    """Exakte Preis-Rendite (%) eines Benchmark-Index ueber [start, end], **in CHF**.

    Nutzt den letzten Close am-oder-vor jedem Rand-Datum, damit das Fenster zur
    tatsaechlichen Snapshot-Spanne eines Buckets passt (like-for-like) statt zur
    Monats-Granularitaet von get_benchmark_monthly_returns. None, wenn fuer das
    Fenster keine Daten verfuegbar sind.

    **Waehrung (seit 1.8.2026):** Beide Rand-Kurse werden mit dem FX-Kurs ihres
    eigenen Stichtags nach CHF umgerechnet, der Return enthaelt also den
    Waehrungseffekt. Vorher lieferte die Funktion die Rendite in Notierungs-
    waehrung — der Konsument (``compare_to_benchmark.delta_pct``) subtrahierte
    das von einem CHF-Bucket-Return und mischte damit zwei Waehrungen. Prod
    16.05.-30.06.2026 (USD/CHF +2.99 %): Satellite-Delta +2.06 pp gemeldet,
    waehrungskonsistent **-1.38 pp** — Vorzeichen gekippt; Core +3.38 → +0.33 pp.

    Ist die Notierungswaehrung unbekannt oder kein FX-Kurs beschaffbar, gibt es
    ``None`` statt einer gemischten Zahl — eine fehlende Zahl ist sichtbar, eine
    still falsche nicht.
    """
    series = _closes_in_chf(ticker)
    if not series:
        return None
    base_px = _last_close_on_or_before(series, start)
    last_px = _last_close_on_or_before(series, end)
    if base_px is None or last_px is None or base_px <= 0:
        return None
    return round((last_px / base_px - 1) * 100, 2)
