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
- Survivorship Bias: Delisted Ticker fehlen in yfinance
- Total Return via auto_adjust=True (yf_patch Wrapper Default)
- Forward-Return-Berechnung ist MVP-Stub; Vollimplementation folgt sobald
  History > min_snapshots (AC-0a-5)

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
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import func, select

import yf_patch  # noqa: F401 — must load before yfinance usage

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
    )


# ---------------------------------------------------------------------------
# Forward-Return-Berechnung
# ---------------------------------------------------------------------------

async def fetch_forward_return(ticker: str, scan_date: datetime, days: int) -> float | None:
    """Lade historische Preise via yf_patch und berechne den Return.

    TODO: Implementieren sobald History > min_snapshots — siehe AC-0a-5.
    Block 0a liefert nur das Skelett; der tatsaechliche Forward-Return wird
    in Block 0b (oder wenn genug Daten vorhanden sind) scharf geschaltet.
    Der Stub muss bis dahin NotImplementedError werfen, damit die "Insufficient
    data"-Code-Pfad nicht versehentlich uebersprungen wird.
    """
    raise NotImplementedError(
        "Forward-Return-Berechnung ist noch nicht scharf — benoetigt "
        ">= min_snapshots History. Siehe Block 0b im Scope."
    )


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


def write_insufficient_data_csv(output: Path, n_snapshots: int, min_required: int) -> None:
    """Schreibe ein CSV mit Header + einem Hinweis-Row (AC-0a-3)."""
    today = datetime.now().strftime("%Y-%m-%d")
    header = [
        "score_bucket", "n_tickers",
        "avg_excess_return_30d", "hit_rate_30d",
        "avg_excess_return_60d", "hit_rate_60d",
        "avg_excess_return_90d", "hit_rate_90d",
    ]
    with output.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerow([
            f"INSUFFICIENT_DATA (have={n_snapshots}, need>={min_required}, "
            f"snapshot collection started {today}, retry in 90 days)",
            n_snapshots, "", "", "", "", "", "",
        ])


def write_bucket_csv(output: Path, bucket_stats: dict[str, dict[str, Any]]) -> None:
    """Schreibe die aggregierten Bucket-Statistiken (AC-0a-5)."""
    header = [
        "score_bucket", "n_tickers",
        "avg_excess_return_30d", "hit_rate_30d",
        "avg_excess_return_60d", "hit_rate_60d",
        "avg_excess_return_90d", "hit_rate_90d",
    ]
    with output.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        for bucket_name, _ in SCORE_BUCKETS:
            row = bucket_stats.get(bucket_name, {})
            writer.writerow([
                bucket_name,
                row.get("n_tickers", 0),
                row.get("avg_excess_return_30d", ""),
                row.get("hit_rate_30d", ""),
                row.get("avg_excess_return_60d", ""),
                row.get("hit_rate_60d", ""),
                row.get("avg_excess_return_90d", ""),
                row.get("hit_rate_90d", ""),
            ])


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

    # --- Voll-Pipeline (wird erst scharf wenn History ausreicht) ---
    snapshots = await load_snapshots()
    logger.info("Loaded %d snapshots for full backtest", len(snapshots))

    bucket_stats: dict[str, dict[str, Any]] = {
        name: {"n_tickers": 0, "returns": {w: [] for w in FORWARD_WINDOWS}}
        for name, _ in SCORE_BUCKETS
    }

    for result, scan in snapshots:
        score = reconstruct_score(result.signals, config.weights)
        bucket_name = next((n for n, pred in SCORE_BUCKETS if pred(score)), None)
        if bucket_name is None:
            continue
        bucket_stats[bucket_name]["n_tickers"] += 1

        for window in FORWARD_WINDOWS:
            try:
                ticker_ret = await fetch_forward_return(result.ticker, scan.started_at, window)
                spy_ret = await fetch_forward_return("SPY", scan.started_at, window)
                if ticker_ret is not None and spy_ret is not None:
                    bucket_stats[bucket_name]["returns"][window].append(ticker_ret - spy_ret)
            except NotImplementedError:
                # Erwartet solange die Forward-Return-Logik noch nicht scharf ist.
                logger.warning(
                    "Forward-Return-Berechnung noch nicht implementiert — "
                    "breche Voll-Pipeline ab und schreibe insufficient-data CSV"
                )
                write_insufficient_data_csv(config.output, n_snapshots, config.min_snapshots)
                return 0

    # Aggregation: mittlerer Excess-Return + Hit-Rate pro Bucket/Fenster
    final: dict[str, dict[str, Any]] = {}
    for bucket_name, raw in bucket_stats.items():
        row: dict[str, Any] = {"n_tickers": raw["n_tickers"]}
        for window in FORWARD_WINDOWS:
            rets = raw["returns"][window]
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
