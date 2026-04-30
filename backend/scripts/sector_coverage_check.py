"""Pre-Deployment Sektor-Coverage-Sweep für Phase 1.1.

Iteriere alle Tickers in `etf_holdings` + aktive `Position`-Records,
klassifiziere via 3-stufige Cascade, gib Coverage pro ETF + Liste der
Unclassified-Tickers aus. Workflow: anschauen → SECTOR_OVERRIDES in
analysis_config.py befüllen → Re-Run bis ≥95% Coverage pro ETF.

Phase 1.1 geht NICHT live mit <95% OEF-Coverage.

Aufruf (via docker compose):
  docker compose exec backend python scripts/sector_coverage_check.py
"""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

# Skript läuft aus /app im Container — Backend-Source liegt direkt da
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select, distinct

from db import sync_engine
from models.etf_holding import EtfHolding
from models.position import Position
from services.analysis_config import SECTOR_COVERAGE_MIN_PCT
from services.sector_classification_service import classify_tickers_bulk


def main() -> None:
    with sync_engine.connect() as conn:
        # 1. Alle distinct holding_tickers + Direkt-Position-Tickers sammeln
        etf_rows = conn.execute(
            select(EtfHolding.etf_ticker, EtfHolding.holding_ticker, EtfHolding.weight_pct)
        ).all()
        position_tickers = [
            row[0] for row in conn.execute(
                select(distinct(Position.ticker)).where(Position.is_active.is_(True))
            ).all() if row[0]
        ]

        all_etf_holding_tickers = list({r[1] for r in etf_rows})
        all_tickers = list(set(all_etf_holding_tickers) | set(position_tickers))

        print(f"Sektor-Coverage-Sweep")
        print(f"=" * 60)
        print(f"Total distinct tickers: {len(all_tickers)}")
        print(f"  ETF-Holdings: {len(all_etf_holding_tickers)}")
        print(f"  Direkt-Positions: {len(position_tickers)}")
        print()

        # 2. Bulk-Klassifikation
        sectors = classify_tickers_bulk(all_tickers, db_conn=conn)
        unclassified = [t for t, s in sectors.items() if s is None]

        # 3. Coverage pro ETF
        per_etf: dict[str, dict] = defaultdict(
            lambda: {"classified_weight": 0.0, "unclassified_weight": 0.0, "unclass_tickers": []}
        )
        for etf_t, hold_t, weight in etf_rows:
            entry = per_etf[etf_t]
            w = float(weight)
            if sectors.get(hold_t) is None:
                entry["unclassified_weight"] += w
                entry["unclass_tickers"].append((hold_t, w))
            else:
                entry["classified_weight"] += w

        print(f"Coverage pro ETF (Threshold ≥{SECTOR_COVERAGE_MIN_PCT:.0f}%):")
        print(f"-" * 60)
        for etf_t in sorted(per_etf.keys()):
            data = per_etf[etf_t]
            total = data["classified_weight"] + data["unclassified_weight"]
            if total <= 0:
                continue
            coverage = data["classified_weight"] / total * 100.0
            ok = "✓" if coverage >= SECTOR_COVERAGE_MIN_PCT else "✗"
            print(f"  {ok} {etf_t}: {coverage:.1f}% classified ({data['unclassified_weight']:.1f}% unclassified)")
            if coverage < SECTOR_COVERAGE_MIN_PCT and data["unclass_tickers"]:
                top = sorted(data["unclass_tickers"], key=lambda x: -x[1])[:15]
                for t, w in top:
                    print(f"      → {t}: {w:.2f}%")
        print()

        # 4. Direkt-Position-Coverage
        direct_unclass = [t for t in position_tickers if sectors.get(t) is None]
        direct_classified = len(position_tickers) - len(direct_unclass)
        if position_tickers:
            print(f"Direkt-Position-Coverage:")
            print(f"-" * 60)
            print(f"  {direct_classified}/{len(position_tickers)} klassifiziert ({direct_classified / len(position_tickers) * 100:.1f}%)")
            if direct_unclass:
                print(f"  Unclassified: {', '.join(direct_unclass)}")
            print()

        # 5. SECTOR_OVERRIDES-Vorschlag
        if unclassified:
            print(f"Vorschlag SECTOR_OVERRIDES (Top-15 nach ETF-Gewicht):")
            print(f"-" * 60)
            ticker_max_weight: dict[str, float] = {}
            for etf_t, hold_t, weight in etf_rows:
                w = float(weight)
                if hold_t in unclassified:
                    cur = ticker_max_weight.get(hold_t, 0.0)
                    if w > cur:
                        ticker_max_weight[hold_t] = w
            top_unclass = sorted(ticker_max_weight.items(), key=lambda x: -x[1])[:15]
            print("# Befüllen in analysis_config.py:SECTOR_OVERRIDES")
            for t, w in top_unclass:
                print(f'    "{t}": "?",   # max ETF-Gewicht: {w:.2f}%')
            print()

        # Final-Summary
        all_etfs_ok = all(
            (data["classified_weight"] / max(data["classified_weight"] + data["unclassified_weight"], 0.001) * 100.0)
            >= SECTOR_COVERAGE_MIN_PCT
            for data in per_etf.values()
        )
        print(f"=" * 60)
        if all_etfs_ok:
            print(f"✓ Alle ETFs ≥{SECTOR_COVERAGE_MIN_PCT:.0f}% Coverage — Phase 1.1 ready")
        else:
            print(f"✗ Coverage unter Threshold bei mindestens einem ETF — SECTOR_OVERRIDES befüllen")


if __name__ == "__main__":
    main()
