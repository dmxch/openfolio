"""Konzentrations-Service: vollständige Sicht auf Single-Name + Sektor-Konzentration.

Phase-1.1-Erweiterung des Phase-B-`core_overlap_service`. Scope-Erweiterung:
- Single-Name: Direkt-Position-Baseline + Indirekt-via-ETFs (Phase B)
- Sektor: Aggregation über alle Direkt-Holdings + ETF-anteilig

Naming-Reset: "Core-Overlap" beschreibt nur die Phase-B-Achse. Phase 1.1
zeigt das volle Konzentrations-Bild — daher dieser Service-Name. Das alte
``core_overlap_service``-Alias-Modul wurde in v0.30.0 entfernt.

User-Scope: alle Berechnungen sind user-spezifisch (User-ETFs, User-Positions).
Score-Endpoint ist Wrapper — score_stock bleibt user-agnostisch
(Architektur-Disziplin aus Phase A).
"""
from __future__ import annotations

import logging
import math
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from constants.etf_holdings_sources import ETF_COUNTRY_DEFAULTS
from models.etf_holding import EtfHolding
from models.position import Position
from services.analysis_config import (
    CORE_OVERLAP_HYPOTHETICAL_POSITION_PCT,
    CORE_OVERLAP_MIN_WEIGHT_PCT,
    SECTOR_AGGREGATION_SUPPRESS_ETF_WEIGHT_PCT,
    SECTOR_COVERAGE_MIN_PCT,
    SECTOR_LIMIT_HARD_WARN_PCT,
    SECTOR_LIMIT_SOFT_WARN_PCT,
)

logger = logging.getLogger(__name__)


async def _get_user_etf_positions_with_values(
    db: AsyncSession, user_id: UUID, summary: dict | None = None,
) -> dict[str, dict]:
    """Returns dict[etf_ticker, {position_id, name, market_value_chf}].

    Nutzt portfolio_service als Single-Source-of-Truth für market_value_chf.
    summary (optional): bereits geladene Portfolio-Summary — spart den
    redundanten get_portfolio_summary-Aufruf (Review 2026-07-02, M20).
    """
    if summary is not None:
        portfolio = summary
    else:
        from services.portfolio_service import get_portfolio_summary
        portfolio = await get_portfolio_summary(db, user_id)
    etf_map: dict[str, dict] = {}
    for p in portfolio.get("positions", []):
        if p.get("type") == "etf" and p.get("market_value_chf") and p["market_value_chf"] > 0:
            ticker = p.get("ticker", "")
            if ticker:
                etf_map[ticker.upper()] = {
                    "name": p.get("name", ticker),
                    "market_value_chf": float(p["market_value_chf"]),
                }
    return etf_map


async def _get_user_direct_position(
    db: AsyncSession, ticker: str, user_id: UUID, summary: dict | None = None,
) -> dict | None:
    """Direkte Position des Users für einen Ticker. None wenn nicht gehalten.

    Match auf ``Position.ticker == upper(ticker) OR Position.yfinance_ticker ==
    upper(ticker)`` für Edge-Cases mit gemixten Listings (z.B. ROG.SW vs ROG).
    Nur aktive Positions mit shares > 0.
    summary (optional): bereits geladene Portfolio-Summary (Review 2026-07-02, M20).
    """
    if summary is not None:
        portfolio = summary
    else:
        from services.portfolio_service import get_portfolio_summary
        portfolio = await get_portfolio_summary(db, user_id)
    upper = ticker.upper()
    for p in portfolio.get("positions", []):
        pt = (p.get("ticker") or "").upper()
        yt = (p.get("yfinance_ticker") or "").upper()
        if (pt == upper or yt == upper) and p.get("market_value_chf", 0) > 0:
            return {
                "ticker": pt,
                "name": p.get("name", pt),
                "market_value_chf": float(p["market_value_chf"]),
                "type": p.get("type"),
            }
    return None


async def get_concentration_for_ticker(
    db: AsyncSession, ticker: str, user_id: UUID,
) -> dict:
    """Vollständige Konzentrations-Sicht für einen Ticker.

    Returns:
      {
        "single_name": {
          "overlaps": [...],              # Phase B-Format (indirect via ETFs)
          "direct_position_chf": float | None,
          "total_indirect_chf": float,
          "total_chf": float,             # direct + indirect
          "total_pct": float | None,      # total / liquid_portfolio_chf × 100
        },
        "sector": <sector_aggregation_dict>,  # siehe get_sector_aggregation
        "portfolio": {                    # Portfolio-weiter HHI (correlation_service)
          "hhi": float,                   # 0..1, summe der quadrierten Gewichte
          "effective_n": float,           # 1/HHI
          "nominal_count": int,
          "max_weight_ticker": str | None,
          "max_weight_name": str | None,
          "max_weight_pct": float,
          "classification": "low" | "moderate" | "high" | "unknown",
        },
      }
    """
    ticker_upper = ticker.upper()

    # Summary genau EINMAL laden und an alle internen Helfer durchreichen
    # (Review 2026-07-02, M20: vorher 5× get_portfolio_summary pro Request).
    from services.portfolio_service import get_portfolio_summary
    portfolio = await get_portfolio_summary(db, user_id)

    user_etfs = await _get_user_etf_positions_with_values(db, user_id, summary=portfolio)

    # Indirect-Overlaps via ETFs (Phase-B-Logik)
    overlaps: list[dict] = []
    if user_etfs:
        rows = (
            await db.execute(
                select(
                    EtfHolding.etf_ticker,
                    EtfHolding.holding_name,
                    EtfHolding.weight_pct,
                    EtfHolding.as_of,
                ).where(
                    EtfHolding.holding_ticker == ticker_upper,
                    EtfHolding.weight_pct >= CORE_OVERLAP_MIN_WEIGHT_PCT,
                    EtfHolding.etf_ticker.in_(list(user_etfs.keys())),
                )
            )
        ).all()

        for etf_ticker, holding_name, weight_pct, as_of in rows:
            user_etf = user_etfs.get(etf_ticker)
            if user_etf is None:
                continue
            weight = float(weight_pct)
            etf_position_chf = user_etf["market_value_chf"]
            indirect_exposure_chf = etf_position_chf * weight / 100.0
            overlaps.append({
                "etf_ticker": etf_ticker,
                "etf_name": user_etf["name"],
                "weight_pct": round(weight, 2),
                "etf_position_chf": round(etf_position_chf, 2),
                "indirect_exposure_chf": round(indirect_exposure_chf, 2),
                "holdings_as_of": as_of.isoformat() if as_of else None,
            })
        overlaps.sort(key=lambda x: -x["weight_pct"])

    total_indirect_chf = sum(o["indirect_exposure_chf"] for o in overlaps)

    # Direkt-Position
    direct = await _get_user_direct_position(db, ticker, user_id, summary=portfolio)
    direct_position_chf = direct["market_value_chf"] if direct else None

    total_chf = (direct_position_chf or 0.0) + total_indirect_chf

    # Liquid-Portfolio-Total für total_pct
    liquid_total = portfolio.get("total_market_value_chf") or 0.0
    total_pct = (total_chf / liquid_total * 100.0) if liquid_total > 0 else None

    # Portfolio-weiter HHI / effective_n auf dem investierten Kapital.
    # Single Source of Truth ist correlation_service — gleiche Logik wie
    # /correlation, dadurch sind die Werte zwischen Score- und
    # Correlation-Endpoint Bit-fuer-Bit identisch.
    from services.correlation_service import _compute_portfolio_concentration
    portfolio_concentration = _compute_portfolio_concentration(
        portfolio.get("positions") or []
    )

    # Sektor-Aggregation (aus Ticker-Klassifikation abgeleitet)
    target_sector = _classify_target_sector(ticker_upper)
    hypothetical_buy_chf = (
        liquid_total * CORE_OVERLAP_HYPOTHETICAL_POSITION_PCT / 100.0
        if liquid_total > 0 else None
    )
    sector_agg = await get_sector_aggregation(
        db, user_id, target_sector,
        hypothetical_buy_chf=hypothetical_buy_chf,
        summary=portfolio,
    )

    return {
        "single_name": {
            "overlaps": overlaps,
            "direct_position_chf": round(direct_position_chf, 2) if direct_position_chf is not None else None,
            "total_indirect_chf": round(total_indirect_chf, 2),
            "total_chf": round(total_chf, 2),
            "total_pct": round(total_pct, 2) if total_pct is not None else None,
            # Hypothetischer Direktkauf-Anteil in % des Liquid-Portfolios
            # (analysis_config.CORE_OVERLAP_HYPOTHETICAL_POSITION_PCT). Frontend
            # nutzt das, um keinen Magic-Number-Wert hartzukodieren.
            "hypothetical_position_pct": float(CORE_OVERLAP_HYPOTHETICAL_POSITION_PCT),
        },
        "sector": sector_agg,
        "portfolio": portfolio_concentration,
    }


def _classify_target_sector(ticker: str) -> str | None:
    """Synchroner Wrapper um sector_classification_service für Single-Ticker."""
    try:
        from services.sector_classification_service import classify_ticker_sector
        return classify_ticker_sector(ticker)
    except Exception as e:
        logger.debug(f"sector classification for {ticker} failed: {e}")
        return None


async def get_sector_aggregation(
    db: AsyncSession,
    user_id: UUID,
    target_sector: str | None,
    hypothetical_buy_chf: float | None = None,
    summary: dict | None = None,
) -> dict:
    """Sektor-Aggregation: aktueller Sektor-Anteil + hypothetischer Post-Buy-Anteil.

    summary (optional): bereits geladene Portfolio-Summary — vermeidet
    redundante get_portfolio_summary-Aufrufe (Review 2026-07-02, M20).

    Vier-Stati statt None für 2 verschiedene Fälle (Frontend kann differenzieren):
      - "no_sector": Ticker konnte nicht klassifiziert werden
      - "low_coverage": ETF mit ≥10% Portfolio-Weight hat <95% Coverage → Aggregation suppressed
      - "below_threshold": Sektor-Anteil unter Soft-Warn (25%) → kein Banner
      - "ok": Soft- oder Hard-Warn überschritten, Banner zeigen
    """
    base = {
        "status": "no_sector",
        "sector": None,
        "current_pct": None,
        "post_buy_pct": None,
        "soft_warn": False,
        "hard_warn": False,
        "coverage_warning": False,
        "affected_etfs": [],
    }

    if not target_sector:
        return base

    base["sector"] = target_sector

    from services.sector_classification_service import classify_tickers_bulk

    if summary is not None:
        portfolio = summary
    else:
        from services.portfolio_service import get_portfolio_summary
        portfolio = await get_portfolio_summary(db, user_id)
    liquid_total = portfolio.get("total_market_value_chf") or 0.0
    if liquid_total <= 0:
        return {**base, "status": "below_threshold"}

    user_etfs = await _get_user_etf_positions_with_values(db, user_id, summary=portfolio)

    # 1. Direkt-Holdings im Target-Sektor
    direct_tickers = [
        (p.get("ticker") or "").upper()
        for p in portfolio.get("positions", [])
        if p.get("type") == "stock" and p.get("market_value_chf", 0) > 0
    ]
    direct_tickers = [t for t in direct_tickers if t]

    direct_sectors = classify_tickers_bulk(direct_tickers) if direct_tickers else {}
    direct_target_chf = 0.0
    for p in portfolio.get("positions", []):
        if p.get("type") != "stock":
            continue
        pt = (p.get("ticker") or "").upper()
        mv = p.get("market_value_chf", 0) or 0
        if pt and direct_sectors.get(pt) == target_sector and mv > 0:
            direct_target_chf += mv

    # 2. Indirekt via ETFs: pro ETF Sektor-Anteil aus etf_holdings × Sektor-Klassifikation
    indirect_target_chf = 0.0
    affected_etfs: list[dict] = []
    coverage_suppression_triggered = False

    if user_etfs:
        # Alle Holdings aller User-ETFs einmal laden
        etf_rows = (
            await db.execute(
                select(
                    EtfHolding.etf_ticker,
                    EtfHolding.holding_ticker,
                    EtfHolding.weight_pct,
                    EtfHolding.holding_sector,
                ).where(EtfHolding.etf_ticker.in_(list(user_etfs.keys())))
            )
        ).all()

        # Nach ETF gruppieren. Der Issuer-native Sektor (holding_sector) wird vor
        # classify_tickers_bulk bevorzugt — letzteres kennt nur ticker_industries
        # (US-zentriert) und liefert fuer EM-/Non-US-Holdings <1% Coverage.
        by_etf: dict[str, list[tuple[str, float]]] = {}
        stored_sectors: dict[str, str] = {}
        for etf_t, hold_t, weight, hsector in etf_rows:
            by_etf.setdefault(etf_t, []).append((hold_t, float(weight)))
            if hsector:
                stored_sectors[hold_t] = hsector

        # Nur Holdings OHNE gespeicherten Sektor brauchen den DB-Klassifikator.
        all_holdings = list({h for ht_list in by_etf.values() for h, _ in ht_list})
        unstored = [h for h in all_holdings if h not in stored_sectors]
        holding_sectors = classify_tickers_bulk(unstored) if unstored else {}

        # Pro ETF: Coverage + Target-Sector-Anteil
        for etf_ticker, holdings in by_etf.items():
            etf_meta = user_etfs.get(etf_ticker)
            if not etf_meta:
                continue
            etf_position_chf = etf_meta["market_value_chf"]
            etf_portfolio_weight_pct = (etf_position_chf / liquid_total * 100.0) if liquid_total > 0 else 0

            classified_weight_sum = 0.0
            unclassified_weight_sum = 0.0
            target_weight_sum = 0.0
            for h_ticker, weight in holdings:
                sector = stored_sectors.get(h_ticker) or holding_sectors.get(h_ticker)
                if sector is None:
                    unclassified_weight_sum += weight
                else:
                    classified_weight_sum += weight
                    if sector == target_sector:
                        target_weight_sum += weight

            total_weight = classified_weight_sum + unclassified_weight_sum
            if total_weight <= 0:
                continue
            classified_pct = classified_weight_sum / total_weight * 100.0

            # Coverage-Suppression: ETF mit ≥10% Portfolio-Weight UND <95% Coverage → ganze Aggregation suppress
            if (
                etf_portfolio_weight_pct >= SECTOR_AGGREGATION_SUPPRESS_ETF_WEIGHT_PCT
                and classified_pct < SECTOR_COVERAGE_MIN_PCT
            ):
                coverage_suppression_triggered = True
                affected_etfs.append({
                    "etf_ticker": etf_ticker,
                    "classified_pct": round(classified_pct, 1),
                    "portfolio_weight_pct": round(etf_portfolio_weight_pct, 1),
                })

            # Indirekt-Beitrag: nur wenn Coverage gut ist (≥95%); sonst Beitrag = 0
            if classified_pct >= SECTOR_COVERAGE_MIN_PCT:
                indirect_target_chf += etf_position_chf * target_weight_sum / 100.0

    if coverage_suppression_triggered:
        return {
            **base,
            "status": "low_coverage",
            "coverage_warning": True,
            "affected_etfs": affected_etfs,
        }

    current_target_chf = direct_target_chf + indirect_target_chf
    current_pct = (current_target_chf / liquid_total * 100.0) if liquid_total > 0 else 0.0

    post_buy_pct: float | None = None
    if hypothetical_buy_chf is not None and hypothetical_buy_chf > 0:
        # Hypothetischer Direktkauf des aktuellen Tickers — der Ticker
        # gehört zum target_sector, also voller hypothetical_buy_chf-Beitrag
        post_buy_target_chf = current_target_chf + hypothetical_buy_chf
        post_buy_total = liquid_total + hypothetical_buy_chf
        post_buy_pct = post_buy_target_chf / post_buy_total * 100.0

    soft = current_pct >= SECTOR_LIMIT_SOFT_WARN_PCT or (
        post_buy_pct is not None and post_buy_pct >= SECTOR_LIMIT_SOFT_WARN_PCT
    )
    hard = current_pct >= SECTOR_LIMIT_HARD_WARN_PCT or (
        post_buy_pct is not None and post_buy_pct >= SECTOR_LIMIT_HARD_WARN_PCT
    )

    if not soft and not hard:
        return {
            **base,
            "status": "below_threshold",
            "current_pct": round(current_pct, 2),
            "post_buy_pct": round(post_buy_pct, 2) if post_buy_pct is not None else None,
        }

    return {
        **base,
        "status": "ok",
        "current_pct": round(current_pct, 2),
        "post_buy_pct": round(post_buy_pct, 2) if post_buy_pct is not None else None,
        "soft_warn": soft,
        "hard_warn": hard,
        "affected_etfs": affected_etfs,
    }


# --- Watchlist-Bulk-Lookup (Phase-B-API, kein Alias) -------------------------


async def get_overlap_max_weight_for_tickers(
    db: AsyncSession, tickers: list[str], user_id: UUID,
) -> dict[str, float]:
    """Bulk-Lookup für Watchlist: ticker → max weight_pct über User-ETFs.

    Funktion bleibt bewusst mit ``overlap``-Begriff im Namen — die Watchlist-
    Spalte zeigt nur den ETF-Overlap-Aspekt (max-Gewicht über User-ETFs),
    nicht das volle Konzentrations-Bild. Bewusste Achsen-Trennung.
    """
    if not tickers:
        return {}

    user_etfs = await _get_user_etf_positions_with_values(db, user_id)
    if not user_etfs:
        return {}

    upper_tickers = [t.upper() for t in tickers if t]
    if not upper_tickers:
        return {}

    rows = (
        await db.execute(
            select(
                EtfHolding.holding_ticker,
                EtfHolding.weight_pct,
            ).where(
                EtfHolding.holding_ticker.in_(upper_tickers),
                EtfHolding.weight_pct >= CORE_OVERLAP_MIN_WEIGHT_PCT,
                EtfHolding.etf_ticker.in_(list(user_etfs.keys())),
            )
        )
    ).all()

    max_weights: dict[str, float] = {}
    for holding_ticker, weight_pct in rows:
        weight = float(weight_pct)
        cur = max_weights.get(holding_ticker)
        if cur is None or weight > cur:
            max_weights[holding_ticker] = round(weight, 2)
    return max_weights


async def get_country_lookthrough(db: AsyncSession, user_id: UUID) -> dict:
    """Geografische Verteilung der ETF-Holdings (Look-Through).

    Verteilt den CHF-Wert jeder ETF-Position ueber die Laender ihrer Holdings
    (etf_holdings.holding_country, Issuer-nativ). Direkt-Aktien sind bewusst NICHT
    enthalten — dies ist die ETF-Durchsicht ("wo stecke ich durch meine ETFs").
    Ehrlicher Coverage-Header: pro ETF resolution_pct + Quelle-Stichtag; ETFs ohne
    Look-Through werden separat ausgewiesen statt still ignoriert.
    """
    base = {"has_data": False, "total_lookthrough_chf": 0.0,
            "countries": [], "etfs": [], "etfs_without_data": []}
    user_etfs = await _get_user_etf_positions_with_values(db, user_id)
    if not user_etfs:
        return base

    rows = (
        await db.execute(
            select(
                EtfHolding.etf_ticker,
                EtfHolding.holding_country,
                EtfHolding.weight_pct,
                EtfHolding.as_of,
            ).where(EtfHolding.etf_ticker.in_(list(user_etfs.keys())))
        )
    ).all()

    by_etf: dict[str, list[tuple[str | None, float]]] = {}
    etf_as_of: dict[str, object] = {}
    for etf_t, country, weight, as_of in rows:
        w = float(weight)
        # Defensiv: eine (historisch, vor den Source-Guards) persistierte NaN/Inf-Row
        # wuerde sonst total_w/covered_w vergiften und den Endpoint auf 500 kippen
        # (Starlette serialisiert mit allow_nan=False). Belt-and-suspenders zum
        # Source-Guard in make_holding_row / _parse_fmp_holding.
        if not math.isfinite(w):
            continue
        by_etf.setdefault(etf_t, []).append((country, w))
        if as_of is not None:
            etf_as_of[etf_t] = as_of

    country_chf: dict[str, float] = {}
    etf_meta: list[dict] = []
    etfs_without: list[str] = []
    total_lt_chf = 0.0

    for etf_ticker, meta in user_etfs.items():
        holdings = by_etf.get(etf_ticker)
        etf_value = meta["market_value_chf"]
        total_w = sum(w for _, w in holdings) if holdings else 0.0
        covered_w = sum(w for c, w in holdings if c) if holdings else 0.0

        # Keine verwertbare Laender-Coverage (kein Holdings-CSV ODER Holdings ohne
        # Country-Feld, z.B. OEF via FMP)? Bekannter, eindeutiger Geo-Default →
        # ganzer ETF-Wert auf das Default-Land, sonst faellt der ETF-Wert ganz raus.
        if covered_w <= 0:
            default_country = ETF_COUNTRY_DEFAULTS.get(etf_ticker)
            if default_country:
                country_chf[default_country] = country_chf.get(default_country, 0.0) + etf_value
                total_lt_chf += etf_value
                etf_meta.append({
                    "ticker": etf_ticker,
                    "name": meta["name"],
                    "coverage_pct": 100.0,
                    "as_of": None,
                    "source": "default",
                })
            else:
                etfs_without.append(etf_ticker)
            continue

        for country, weight in holdings:
            if country:
                country_chf[country] = country_chf.get(country, 0.0) + etf_value * weight / 100.0
        total_lt_chf += etf_value * covered_w / 100.0
        as_of = etf_as_of.get(etf_ticker)
        etf_meta.append({
            "ticker": etf_ticker,
            "name": meta["name"],
            "coverage_pct": round(covered_w / total_w * 100.0, 1),
            "as_of": as_of.isoformat() if hasattr(as_of, "isoformat") else None,
            "source": "holdings",
        })

    if total_lt_chf <= 0:
        return {**base, "etfs_without_data": etfs_without}

    countries = sorted(
        ({"country": c, "value_chf": round(v, 2), "pct": round(v / total_lt_chf * 100.0, 2)}
         for c, v in country_chf.items()),
        key=lambda x: x["value_chf"], reverse=True,
    )
    return {
        "has_data": True,
        "total_lookthrough_chf": round(total_lt_chf, 2),
        "countries": countries,
        "etfs": sorted(etf_meta, key=lambda x: x["ticker"]),
        "etfs_without_data": etfs_without,
    }
