"""Backtest-Harness fuer den Smart-Money-Screener (Block 0a Pre-Requisite).

Dieses CLI-Tool rekonstruiert historische Screener-Scores aus `ScreeningResult`-
Snapshots, berechnet Forward-Returns (30/60/90 Tage) pro Ticker und aggregiert
sie in Score-Buckets, abzueglich einer SPY-Baseline.

Aufruf:

    docker compose exec backend python -m services.screening.backtest_harness --config default

Wichtig: Beim ersten Launch (nach Block 0a Live) existiert noch keine History —
die Retention-Infrastruktur akkumuliert Snapshots erst ab jetzt. Der Harness
meldet in diesem Fall "Insufficient data" und schreibt ein CSV mit einem
Hinweis-Row statt einer Exception zu werfen. Frueheste sinnvolle Auswertung:
~90 Tage nach Block 0a Go-Live (siehe Block 0b im Scope-Dokument).

Bekannte Einschraenkungen:
- Survivorship Bias: Delistete Ticker fehlen in yfinance — ihre (oft schlechten)
  Forward-Returns fallen aus der Auswertung, der Schnitt ist nach oben verzerrt.
- Total Return via auto_adjust=True (yf_patch Wrapper Default) — Dividenden sind
  reinvestiert, Ticker- und SPY-Returns sind dadurch direkt vergleichbar.
- Forward-Return-Berechnung ist scharf geschaltet (gebuendelter Batch-Download +
  reine Compute-Funktion). Belastbar ist ein Fenster aber erst, wenn die je
  Fenster ausgewiesene Stichprobe (n_30d/n_60d/n_90d) gross genug ist — und
  statistisch aussagekraeftig erst mit Historie auf Jahres-Skala.

Siehe SCOPE_SMART_MONEY_V4.md Block 0a fuer Acceptance Criteria.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import logging
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

import pandas as pd
from sqlalchemy import func, select

from yf_patch import yf_download  # Wrapper (HEILIGE Regel 7); laedt yf_patch vor yfinance-Nutzung

from db import async_session
from models.screening import ScreeningResult, ScreeningScan

logger = logging.getLogger("backtest_harness")


# ---------------------------------------------------------------------------
# Default-Gewichte (muessen mit screening_service.py konsistent bleiben)
# ---------------------------------------------------------------------------

DEFAULT_WEIGHTS: dict[str, int] = {
    "insider_cluster": 3,
    "superinvestor": 2,
    "buyback": 2,
    "large_buy": 1,
    "congressional": 1,
    "short_trend": -1,
    "ftd": -1,
    "unusual_volume": 0,
}

SCORE_BUCKETS: list[tuple[str, Callable[[int], bool]]] = [
    ("0", lambda s: s <= 0),
    ("1-2", lambda s: 1 <= s <= 2),
    ("3-4", lambda s: 3 <= s <= 4),
    ("5-6", lambda s: 5 <= s <= 6),
    ("7+", lambda s: s >= 7),
]

FORWARD_WINDOWS = (30, 60, 90)

# Baseline-Ticker fuer den Excess-Return (SPY = US-Markt, total-return-adjustiert).
BASELINE_TICKER = "SPY"

# yfinance-Batch-Groesse: ein Download pro ~50 Ticker, max. 3 Batches parallel
# (Semaphore) — drosselt den Burst und vermeidet den Universe-wide 429-Bann
# (siehe feedback_yfinance_burst_429).
BATCH_SIZE = 50
FETCH_CONCURRENCY = 3

# yfinance drosselt universe-weite Sweeps STILL (leere DataFrames statt 429-
# Exception). Fehlende Ticker werden daher in mehreren Runden mit exponentiellem
# Backoff nachgeholt — die Drossel erholt sich ueber Zeit. Ticker, die nach allen
# Retries leer bleiben, gelten als echt nicht verfuegbar (delistet/Symbol-Tail).
MAX_FETCH_RETRIES = 3
RETRY_BASE_DELAY_S = 5.0


# ---------------------------------------------------------------------------
# Signal-Rekonstruktion
# ---------------------------------------------------------------------------

def _signal_present(signals: dict[str, Any] | None, key: str) -> bool:
    """Ein Signal gilt als aktiv, wenn der Key existiert und ein truthy Wert
    drinsteht (dict, list, true, oder numerisch > 0)."""
    if not signals or key not in signals:
        return False
    val = signals[key]
    if val is None:
        return False
    if isinstance(val, (dict, list)):
        return len(val) > 0
    return bool(val)


def reconstruct_score(signals: dict[str, Any] | None, weights: dict[str, int]) -> int:
    """Rekonstruiert den Score aus den rohen Signal-Flags mit gegebenen Gewichten.

    Cap auf [0, 10] analog zu screening_service.run_scan.
    """
    raw = 0
    for key, weight in weights.items():
        if _signal_present(signals, key):
            raw += weight
    return max(0, min(raw, 10))


# ---------------------------------------------------------------------------
# Konfig-Handling
# ---------------------------------------------------------------------------

@dataclass
class HarnessConfig:
    profile: str
    weights: dict[str, int]
    min_snapshots: int
    output: Path
    per_signal: bool = False


def build_config(args: argparse.Namespace) -> HarnessConfig:
    weights = dict(DEFAULT_WEIGHTS)
    if args.weights_override:
        try:
            override = json.loads(args.weights_override)
        except json.JSONDecodeError as e:
            raise SystemExit(f"--weights-override ist kein valides JSON: {e}")
        if not isinstance(override, dict):
            raise SystemExit("--weights-override muss ein JSON-Objekt sein")
        for key, val in override.items():
            if not isinstance(val, (int, float)):
                raise SystemExit(f"Gewicht fuer '{key}' muss numerisch sein")
            weights[key] = int(val)

    if args.output:
        output = Path(args.output)
    else:
        stamp = datetime.now().strftime("%Y%m%d")
        output = Path(f"backtest_output_{stamp}.csv")

    return HarnessConfig(
        profile=args.config,
        weights=weights,
        min_snapshots=args.min_snapshots,
        output=output,
        per_signal=getattr(args, "per_signal", False),
    )


# ---------------------------------------------------------------------------
# Forward-Return-Berechnung (reine Compute-Logik, kein I/O — voll testbar)
# ---------------------------------------------------------------------------

def _first_price_in_window(
    prices: pd.Series, start: date, end_exclusive: date | None = None
) -> float | None:
    """Close-Preis am ersten Handelstag im Fenster ``[start, end_exclusive)``.

    Erwartet eine ``pd.Series`` mit (Datetime-)Index. NaN-Werte werden
    uebersprungen. Ohne ``end_exclusive`` ist das Fenster nach oben offen
    (erster Handelstag >= ``start``). Gibt ``None`` zurueck, wenn es im Fenster
    keinen Handelstag gibt (z.B. Datenluecke oder Fenster ueber dem Serien-Ende).
    """
    if prices is None or len(prices) == 0:
        return None
    s = prices.dropna().sort_index()
    if s.empty:
        return None
    # Index defensiv auf Timestamps normalisieren (synthetische Test-Serien /
    # yfinance liefern beide DatetimeIndex, aber wir wollen robust vergleichen).
    idx = pd.to_datetime(s.index)
    mask = idx >= pd.Timestamp(start)
    if end_exclusive is not None:
        mask = mask & (idx < pd.Timestamp(end_exclusive))
    if not mask.any():
        return None
    val = s.to_numpy()[mask.argmax()]
    try:
        out = float(val)
    except (TypeError, ValueError):
        return None
    if out != out:  # NaN-Guard (sollte nach dropna nicht auftreten)
        return None
    return out


def compute_forward_return(
    prices: pd.Series,
    scan_date: date,
    days: int,
    today: date,
    entry_fallback: float | None = None,
) -> float | None:
    """Forward-Return ueber ``days`` Kalendertage ab ``scan_date``.

    - Entry = Close am ersten Handelstag im Fenster ``[scan_date, exit_target)``
      (der Entry darf nicht ueber das Exit-Datum hinausspringen). Fehlt ein
      Handelstag in diesem Fenster und ist ``entry_fallback`` gesetzt (z.B. der
      Scan-Zeitpunkt-Preis ``price_usd``), wird der Fallback als Entry genutzt;
      sonst ``None``.
    - Exit = Close am ersten Handelstag >= ``scan_date + days``.
    - Unvollstaendiges Fenster: liegt ``scan_date + days`` in der Zukunft
      (> ``today``), wird ``None`` zurueckgegeben — ein angeschnittenes Fenster
      darf NICHT als (falscher) Return durchgehen.
    - Fehlender Entry/Exit oder ``entry <= 0`` ⇒ ``None``.

    Rueckgabe ist ein Dezimalbruch (0.12 = +12 %).
    """
    exit_target = scan_date + timedelta(days=days)
    # Korrektheit: nur abgeschlossene Fenster auswerten.
    if exit_target > today:
        return None

    entry = _first_price_in_window(prices, scan_date, exit_target)
    if entry is None and entry_fallback is not None:
        entry = float(entry_fallback)
    if entry is None or entry <= 0:
        return None

    exit_price = _first_price_in_window(prices, exit_target)
    if exit_price is None:
        return None

    return exit_price / entry - 1.0


# ---------------------------------------------------------------------------
# Gebuendelter Kurs-Fetch (ein Download pro Batch, kein Per-Ticker-Massaker)
# ---------------------------------------------------------------------------

def _extract_closes(raw: pd.DataFrame | None, tickers: list[str]) -> dict[str, pd.Series]:
    """Close-Serien je Ticker aus einem yf_download-DataFrame ziehen.

    Behandelt beide Spaltenformen: Multi-Ticker liefert einen MultiIndex
    ``(Feld, Ticker)``, ein einzelner Ticker flache Spalten. Fehlende oder leere
    Ticker werden stillschweigend ausgelassen (Survivorship: delistete Ticker
    fehlen → kein Crash).
    """
    out: dict[str, pd.Series] = {}
    if raw is None or len(raw) == 0:
        return out

    cols = raw.columns
    if isinstance(cols, pd.MultiIndex):
        for t in tickers:
            if ("Close", t) in cols:
                s = raw[("Close", t)].dropna()
                if not s.empty:
                    out[t] = s.astype(float)
    else:
        # Flache Spalten ⇒ genau ein Ticker im Batch.
        if "Close" in cols and len(tickers) == 1:
            s = raw["Close"].dropna()
            if not s.empty:
                out[tickers[0]] = s.astype(float)
    return out


async def fetch_price_histories(
    tickers: list[str], start: date, end: date
) -> dict[str, pd.Series]:
    """Lade Tages-Close-Serien (total-return, auto_adjust) fuer alle Ticker.

    Buendelt die Downloads in Batches a ~``BATCH_SIZE`` Ticker und feuert max.
    ``FETCH_CONCURRENCY`` Batches parallel (Semaphore) — yfinance NUR ueber
    ``yf_download`` in ``asyncio.to_thread`` (HEILIGE Regel 7). Der Baseline-
    Ticker (SPY) wird automatisch ergaenzt.

    ``end`` ist bei yfinance exklusiv — der Aufrufer uebergibt daher ``today + 1``.
    Fehlende Ticker werden in bis zu ``MAX_FETCH_RETRIES`` Runden mit
    exponentiellem Backoff nachgeholt (yfinance drosselt still; die Drossel
    erholt sich ueber Zeit). Rueckgabe: ``{ticker: Close-Serie}`` — Ticker, die
    nach allen Retries leer bleiben, fehlen schlicht (delistet/Symbol-Tail).
    """
    unique = list(dict.fromkeys([*tickers, BASELINE_TICKER]))
    if not unique:
        return {}

    start_str = start.isoformat()
    end_str = end.isoformat()
    sem = asyncio.Semaphore(FETCH_CONCURRENCY)

    async def _fetch_batch(batch: list[str]) -> dict[str, pd.Series]:
        async with sem:
            try:
                raw = await asyncio.to_thread(
                    yf_download,
                    batch,
                    start=start_str,
                    end=end_str,
                    interval="1d",
                    auto_adjust=True,
                )
            except Exception:
                logger.exception(
                    "yf_download batch failed (%d tickers) — skipping batch", len(batch)
                )
                return {}
            return _extract_closes(raw, batch)

    price_map: dict[str, pd.Series] = {}
    pending = list(unique)

    for attempt in range(MAX_FETCH_RETRIES + 1):
        if not pending:
            break
        if attempt > 0:
            delay = RETRY_BASE_DELAY_S * (2 ** (attempt - 1))
            logger.info(
                "Kurs-Fetch Retry %d/%d fuer %d fehlende Ticker nach %.0fs Backoff",
                attempt, MAX_FETCH_RETRIES, len(pending), delay,
            )
            await asyncio.sleep(delay)

        batches = [pending[i:i + BATCH_SIZE] for i in range(0, len(pending), BATCH_SIZE)]
        results = await asyncio.gather(*[_fetch_batch(b) for b in batches])
        for partial in results:
            price_map.update(partial)
        # Nur noch echt fehlende Ticker fuer die naechste Runde behalten.
        pending = [t for t in unique if t not in price_map]

    logger.info(
        "Kurs-Fetch: %d/%d Ticker mit Serie (start=%s end=%s); %d nach Retries ohne Daten",
        len(price_map), len(unique), start_str, end_str, len(pending),
    )
    return price_map


# ---------------------------------------------------------------------------
# Haupt-Pipeline
# ---------------------------------------------------------------------------

async def load_snapshots() -> list[tuple[ScreeningResult, ScreeningScan]]:
    """Lade alle ScreeningResult-Eintraege zusammen mit ihrem Scan."""
    async with async_session() as db:
        q = (
            select(ScreeningResult, ScreeningScan)
            .join(ScreeningScan, ScreeningScan.id == ScreeningResult.scan_id)
            .where(ScreeningScan.status == "completed")
            .order_by(ScreeningScan.started_at, ScreeningResult.ticker)
        )
        rows = (await db.execute(q)).all()
        return [(r, s) for r, s in rows]


async def count_snapshots() -> int:
    async with async_session() as db:
        q = select(func.count()).select_from(ScreeningResult)
        return (await db.execute(q)).scalar() or 0


# Gemeinsamer CSV-Header — beide Writer MUESSEN konsistent bleiben. Pro Fenster
# wird die tatsaechliche Stichprobe (n_Nd = Ticker mit VOLLSTAENDIGEM Fenster)
# zusaetzlich zu n_tickers ausgewiesen, damit duenne Fenster sichtbar sind.
CSV_HEADER = [
    "score_bucket", "n_tickers",
    "n_30d", "avg_excess_return_30d", "hit_rate_30d",
    "n_60d", "avg_excess_return_60d", "hit_rate_60d",
    "n_90d", "avg_excess_return_90d", "hit_rate_90d",
]

CSV_CAVEAT = (
    "# Caveat: Survivorship Bias (delistete Ticker fehlen); nur Fenster mit "
    "ausreichend grossem n_Nd sind belastbar; statistisch aussagekraeftig erst "
    "mit Historie auf Jahres-Skala."
)


def write_insufficient_data_csv(output: Path, n_snapshots: int, min_required: int) -> None:
    """Schreibe ein CSV mit Header + einem Hinweis-Row (AC-0a-3)."""
    today = datetime.now().strftime("%Y-%m-%d")
    with output.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(CSV_HEADER)
        writer.writerow([
            f"INSUFFICIENT_DATA (have={n_snapshots}, need>={min_required}, "
            f"snapshot collection started {today}, retry in 90 days)",
            n_snapshots, "", "", "", "", "", "", "", "", "",
        ])
        writer.writerow([])
        writer.writerow([CSV_CAVEAT])


def write_bucket_csv(output: Path, bucket_stats: dict[str, dict[str, Any]]) -> None:
    """Schreibe die aggregierten Bucket-Statistiken (AC-0a-5)."""
    with output.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(CSV_HEADER)
        for bucket_name, _ in SCORE_BUCKETS:
            row = bucket_stats.get(bucket_name, {})
            writer.writerow([
                bucket_name,
                row.get("n_tickers", 0),
                row.get("n_30d", 0),
                row.get("avg_excess_return_30d", ""),
                row.get("hit_rate_30d", ""),
                row.get("n_60d", 0),
                row.get("avg_excess_return_60d", ""),
                row.get("hit_rate_60d", ""),
                row.get("n_90d", 0),
                row.get("avg_excess_return_90d", ""),
                row.get("hit_rate_90d", ""),
            ])
        writer.writerow([])
        writer.writerow([CSV_CAVEAT])


# ---------------------------------------------------------------------------
# Per-Signal-Decomposition (welches EINZELsignal treibt den Forward-Return?)
# ---------------------------------------------------------------------------

def per_signal_breakdown(
    samples: list[tuple[dict[str, Any] | None, dict[int, float]]],
    signal_keys: list[str],
) -> dict[str, dict[str, dict[int, list[float]]]]:
    """Reine Aggregation (voll testbar): teilt je Signal die Forward-Excess-Returns
    in present vs. absent. ``samples`` = Liste aus (signals_dict, {window: excess}).
    Isoliert die univariate Vorhersagekraft jedes Einzelsignals (Signale ko-okkurieren,
    daher present/absent, nicht orthogonal)."""
    stats = {
        k: {"present": {w: [] for w in FORWARD_WINDOWS},
            "absent": {w: [] for w in FORWARD_WINDOWS}}
        for k in signal_keys
    }
    for signals, excess_by_window in samples:
        for k in signal_keys:
            side = "present" if _signal_present(signals, k) else "absent"
            for window, ex in excess_by_window.items():
                stats[k][side][window].append(ex)
    return stats


def write_per_signal_csv(
    output: Path,
    ps_stats: dict[str, dict[str, dict[int, list[float]]]],
    weights: dict[str, int],
) -> None:
    """Je Signal die present/absent-Mittelwerte + Delta (present − absent) pro Fenster.
    Positives Delta = Signal-Anwesenheit korreliert mit Outperformance vs. SPY."""
    def _avg(xs: list[float]) -> float | None:
        return (sum(xs) / len(xs)) if xs else None

    header = ["signal", "weight"]
    for w in FORWARD_WINDOWS:
        header += [f"n_present_{w}d", f"avg_present_{w}d", f"n_absent_{w}d",
                   f"avg_absent_{w}d", f"delta_{w}d", f"hit_present_{w}d"]
    with output.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)

        def _delta30(k: str) -> float:
            p, a = _avg(ps_stats[k]["present"][30]), _avg(ps_stats[k]["absent"][30])
            return abs(p - a) if (p is not None and a is not None) else -1.0

        for k in sorted(ps_stats, key=_delta30, reverse=True):
            row: list[Any] = [k, weights.get(k, 0)]
            for w in FORWARD_WINDOWS:
                pres, absn = ps_stats[k]["present"][w], ps_stats[k]["absent"][w]
                ap, aa = _avg(pres), _avg(absn)
                delta = (ap - aa) if (ap is not None and aa is not None) else None
                hit = (sum(1 for x in pres if x > 0) / len(pres)) if pres else None
                row += [
                    len(pres), f"{ap:.4f}" if ap is not None else "",
                    len(absn), f"{aa:.4f}" if aa is not None else "",
                    f"{delta:.4f}" if delta is not None else "",
                    f"{hit:.4f}" if hit is not None else "",
                ]
            writer.writerow(row)
        writer.writerow([])
        writer.writerow([CSV_CAVEAT])


async def run_harness(config: HarnessConfig) -> int:
    logger.info("Harness profile=%s output=%s", config.profile, config.output)
    logger.info("Weights: %s", config.weights)

    n_snapshots = await count_snapshots()
    logger.info("ScreeningResult count: %d (min required: %d)", n_snapshots, config.min_snapshots)

    if n_snapshots < config.min_snapshots:
        today = datetime.now().strftime("%Y-%m-%d")
        logger.warning(
            "Insufficient data — snapshot collection started %s, retry in 90 days "
            "(have %d, need >= %d)",
            today, n_snapshots, config.min_snapshots,
        )
        write_insufficient_data_csv(config.output, n_snapshots, config.min_snapshots)
        logger.info("Wrote insufficient-data CSV to %s", config.output)
        return 0

    # --- Voll-Pipeline (Forward-Returns scharf) ---
    snapshots = await load_snapshots()
    logger.info("Loaded %d snapshots for full backtest", len(snapshots))

    # Schritt 1: alle benoetigten Ticker + den Datumsbereich sammeln und EINEN
    # gebuendelten Download fahren (statt pro Ticker x Fenster x 2 zu feuern).
    today = datetime.now().date()
    tickers = sorted({result.ticker for result, _ in snapshots})
    earliest_scan = min(scan.started_at for _, scan in snapshots).date()
    fetch_end = today + timedelta(days=1)  # yfinance end ist exklusiv
    price_map = await fetch_price_histories(tickers, earliest_scan, fetch_end)
    spy_series = price_map.get(BASELINE_TICKER)
    if spy_series is None:
        logger.warning(
            "Baseline-Serie (%s) fehlt — Excess-Returns nicht berechenbar; "
            "schreibe leere Bucket-Statistik", BASELINE_TICKER,
        )

    # Schritt 2: pro Snapshot den Score in einen Bucket einsortieren und den
    # SPY-Excess-Return je Fenster aus dem price_map berechnen.
    bucket_stats: dict[str, dict[str, Any]] = {
        name: {"n_tickers": 0, "returns": {w: [] for w in FORWARD_WINDOWS}}
        for name, _ in SCORE_BUCKETS
    }
    samples: list[tuple[dict[str, Any] | None, dict[int, float]]] = []  # fuer Per-Signal-Decomposition

    for result, scan in snapshots:
        score = reconstruct_score(result.signals, config.weights)
        bucket_name = next((n for n, pred in SCORE_BUCKETS if pred(score)), None)
        if bucket_name is None:
            continue
        bucket_stats[bucket_name]["n_tickers"] += 1

        ticker_series = price_map.get(result.ticker)
        if ticker_series is None or spy_series is None:
            continue
        scan_date = scan.started_at.date()

        excess_by_window: dict[int, float] = {}
        for window in FORWARD_WINDOWS:
            ticker_ret = compute_forward_return(
                ticker_series, scan_date, window, today,
                entry_fallback=result.price_usd,
            )
            spy_ret = compute_forward_return(spy_series, scan_date, window, today)
            if ticker_ret is not None and spy_ret is not None:
                ex = ticker_ret - spy_ret
                bucket_stats[bucket_name]["returns"][window].append(ex)
                excess_by_window[window] = ex
        if config.per_signal and excess_by_window:
            samples.append((result.signals, excess_by_window))

    # Aggregation: mittlerer Excess-Return + Hit-Rate + Stichprobengroesse je
    # Bucket/Fenster. n_Nd = Anzahl Ticker mit VOLLSTAENDIGEM Fenster.
    final: dict[str, dict[str, Any]] = {}
    for bucket_name, raw in bucket_stats.items():
        row: dict[str, Any] = {"n_tickers": raw["n_tickers"]}
        for window in FORWARD_WINDOWS:
            rets = raw["returns"][window]
            row[f"n_{window}d"] = len(rets)
            if rets:
                avg = sum(rets) / len(rets)
                hit = sum(1 for r in rets if r > 0) / len(rets)
                row[f"avg_excess_return_{window}d"] = f"{avg:.4f}"
                row[f"hit_rate_{window}d"] = f"{hit:.4f}"
            else:
                row[f"avg_excess_return_{window}d"] = ""
                row[f"hit_rate_{window}d"] = ""
        final[bucket_name] = row

    write_bucket_csv(config.output, final)
    logger.info("Wrote backtest CSV to %s", config.output)

    if config.per_signal:
        ps_stats = per_signal_breakdown(samples, list(config.weights.keys()))
        ps_out = config.output.with_name(f"{config.output.stem}_per_signal{config.output.suffix}")
        write_per_signal_csv(ps_out, ps_stats, config.weights)
        logger.info("Wrote per-signal CSV to %s (samples=%d)", ps_out, len(samples))

    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="backtest_harness",
        description="Backtest-Harness fuer den Smart-Money-Screener (Block 0a).",
    )
    parser.add_argument("--config", default="default", help="Profile-Name (Default: default)")
    parser.add_argument(
        "--weights-override",
        default=None,
        help='JSON-Objekt mit Gewichts-Overrides, z.B. \'{"superinvestor": 3}\'',
    )
    parser.add_argument("--output", default=None, help="Output-CSV-Pfad (Default: backtest_output_YYYYMMDD.csv)")
    parser.add_argument("--min-snapshots", type=int, default=50, help="Mindest-Anzahl Snapshots (Default: 50)")
    parser.add_argument("--per-signal", action="store_true", help="Zusaetzlich Per-Signal-Decomposition (present vs. absent je Einzelsignal) -> <output>_per_signal.csv")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    args = parse_args(argv)
    config = build_config(args)
    return asyncio.run(run_harness(config))


if __name__ == "__main__":
    sys.exit(main())
