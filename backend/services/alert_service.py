"""Generate alerts based on portfolio rules and market conditions."""

import logging
from datetime import datetime

from services import cache
from services.sector_mapping import is_broad_etf

logger = logging.getLogger(__name__)

# --- Configurable thresholds ---
# Phase 3: keine Core/Satellite-Differenzierung mehr — Bucket-Rules sind die
# kanonische Quelle. Konstanten dienen nur noch als Fallback wenn weder
# Position-Override noch Bucket-Rules etwas spezifizieren.

# Stop-Loss Review (active-risk Tier = frueher Satellite, buy-and-hold = frueher Core)
SATELLITE_STOP_REVIEW_DISTANCE_PCT = 15.0
SATELLITE_STOP_REVIEW_MAX_DAYS = 14
CORE_STOP_REVIEW_DISTANCE_PCT = 30.0
CORE_STOP_REVIEW_MAX_DAYS = 90

# Position limits (% of liquid portfolio) — Default-Fallback je Asset-Type
CORE_STOCK_MAX_PCT = 10.0
CORE_ETF_MAX_PCT = 15.0
COMMODITY_HEDGE_MAX_PCT = 15.0
SECTOR_MAX_PCT = 25.0

# Loss thresholds (fallback when no stop-loss set)
SATELLITE_LOSS_WARNING_PCT = -15.0
CORE_LOSS_WARNING_PCT = -25.0

# Stop proximity
STOP_PROXIMITY_WARNING_PCT = 3.0


def _get_position_limit(p: dict, buckets_map: dict | None = None) -> tuple[float, str]:
    """Return (max_pct, label) for a position.

    Phase 3 Resolution: Position-Override > Bucket-Override > Default.
    Default haengt am asset_type — keine Core/Satellite-Differenzierung mehr.
    """
    # Position-Level Override hat hoechsten Vorrang
    pos_rules = p.get("risk_rules") or {}
    pos_limit = pos_rules.get("max_position_pct")
    if pos_limit is not None:
        return float(pos_limit), f"Position-Override {p.get('ticker', '')}"

    bid = p.get("bucket_id")
    if buckets_map and bid and bid in buckets_map:
        rules = buckets_map[bid].get("risk_rules") or {}
        bucket_limit = rules.get("max_position_pct")
        if bucket_limit is not None:
            return float(bucket_limit), f"Bucket {buckets_map[bid]['name']}"

    asset_type = p.get("type", "")
    if asset_type in ("crypto", "commodity"):
        return COMMODITY_HEDGE_MAX_PCT, "Rohstoff/Hedge"
    if asset_type == "etf":
        return CORE_ETF_MAX_PCT, "ETF"
    # stock
    return CORE_STOCK_MAX_PCT, "Aktie"


def _bucket_loss_pct(p: dict, buckets_map: dict | None, default: float) -> float:
    """Return loss threshold for a position.

    Resolution: Position-Override > Bucket-Override > default.
    """
    pos_rules = p.get("risk_rules") or {}
    v = pos_rules.get("alert_loss_pct")
    if v is not None:
        return float(v)

    bid = p.get("bucket_id")
    if buckets_map and bid and bid in buckets_map:
        rules = buckets_map[bid].get("risk_rules") or {}
        v = rules.get("alert_loss_pct")
        if v is not None:
            return float(v)
    return default


def _is_active_risk(p: dict, buckets_map: dict | None) -> bool:
    """True wenn die Position einem 'aktiven' Risk-Tier zugeordnet ist
    (frueher: position_type='satellite').

    Heuristik: Bucket hat stop_loss_method_default oder stop_loss_default_pct
    in risk_rules. Position-Override hat Vorrang. Phase-3-Ersatz fuer
    position_type-basierte Severity-Differenzierung in Alerts.
    """
    pos_rules = p.get("risk_rules") or {}
    if pos_rules.get("stop_loss_method_default") or pos_rules.get("stop_loss_default_pct") is not None:
        return True
    bid = p.get("bucket_id")
    if buckets_map and bid and bid in buckets_map:
        rules = buckets_map[bid].get("risk_rules") or {}
        if rules.get("stop_loss_method_default") or rules.get("stop_loss_default_pct") is not None:
            return True
    return False


def generate_alerts(
    positions: list[dict],
    market_climate: dict | None,
    user_prefs: dict | None = None,
    watchlist_tickers: list[dict] | None = None,
    buckets_map: dict | None = None,
) -> list[dict]:
    alerts = []
    total_value = sum(p["market_value_chf"] for p in positions) if positions else 0

    if not positions or total_value == 0:
        return alerts

    prefs = user_prefs or {}
    def _enabled(category: str) -> bool:
        key = f"alert_{category}"
        return prefs.get(key, True)

    # Override thresholds from user prefs
    satellite_loss_pct = prefs.get("alert_satellite_loss_pct", SATELLITE_LOSS_WARNING_PCT)
    core_loss_pct = prefs.get("alert_core_loss_pct", CORE_LOSS_WARNING_PCT)
    stop_prox_pct = prefs.get("alert_stop_proximity_pct", STOP_PROXIMITY_WARNING_PCT)

    # --- 1. Position limits (differentiated by type, bucket-override) ---
    for p in positions:
        if p.get("type") in ("cash", "pension"):
            continue
        if p.get("shares", 0) <= 0:
            continue
        pct = p["market_value_chf"] / total_value * 100
        limit, label = _get_position_limit(p, buckets_map)
        if pct > limit:
            alerts.append({
                "type": "warning",
                "category": "position_limit",
                "title": f"Positions-Limit: {p['name']}",
                "message": f"{p['ticker']} bei {pct:.1f}% des liquiden Vermögens (Max: {limit:.0f}% für {label})",
                "ticker": p.get("ticker"),
                "severity": "high" if pct > limit + 5 else "medium",
            })

    # --- 2. Sector limits (global + per-bucket via buckets_map) ---
    sector_values = {}
    for p in positions:
        if p.get("type") in ("cash", "pension"):
            continue
        sector = p.get("sector") or "Other"
        sector_values[sector] = sector_values.get(sector, 0) + p["market_value_chf"]
    for sector, value in sector_values.items():
        pct = value / total_value * 100
        if pct > SECTOR_MAX_PCT:
            alerts.append({
                "type": "warning",
                "category": "sector_limit",
                "title": f"Sektor-Limit: {sector}",
                "message": f"{sector} bei {pct:.1f}% (Max: {SECTOR_MAX_PCT:.0f}%)",
                "severity": "high" if pct > 30 else "medium",
            })

    # Per-Bucket Sector-Aggregation (nur wenn Bucket eigene max_sector_pct setzt)
    if buckets_map:
        # group positions by bucket
        by_bucket_sector: dict[str, dict[str, float]] = {}
        by_bucket_total: dict[str, float] = {}
        for p in positions:
            if p.get("type") in ("cash", "pension"):
                continue
            bid = p.get("bucket_id")
            if not bid or bid not in buckets_map:
                continue
            sector = p.get("sector") or "Other"
            by_bucket_sector.setdefault(bid, {})[sector] = (
                by_bucket_sector.get(bid, {}).get(sector, 0) + p["market_value_chf"]
            )
            by_bucket_total[bid] = by_bucket_total.get(bid, 0) + p["market_value_chf"]
        for bid, sectors in by_bucket_sector.items():
            bucket = buckets_map[bid]
            rules = bucket.get("risk_rules") or {}
            sec_limit = rules.get("max_sector_pct")
            if sec_limit is None:
                continue
            bucket_total = by_bucket_total.get(bid, 0)
            if bucket_total <= 0:
                continue
            for sector, value in sectors.items():
                pct = value / bucket_total * 100
                if pct > float(sec_limit):
                    alerts.append({
                        "type": "warning",
                        "category": "sector_limit",
                        "title": f"Sektor-Limit in Bucket {bucket['name']}: {sector}",
                        "message": f"{sector} bei {pct:.1f}% des Buckets (Max: {sec_limit:.0f}%)",
                        "severity": "high" if pct > float(sec_limit) + 5 else "medium",
                    })

    # --- 3. Unter 150-DMA (Schwur 1) — differenziert nach Risk-Tier (Phase 3) ---
    for p in positions:
        if p.get("type") in ("cash", "pension"):
            continue
        if p.get("shares", 0) <= 0:
            continue
        if p.get("ma_status") == "KRITISCH":
            active_risk = _is_active_risk(p, buckets_map)
            if active_risk:
                alerts.append({
                    "type": "danger",
                    "category": "ma_critical",
                    "title": f"Unter 150-DMA: {p['name']}",
                    "message": f"{p['ticker']} — Verkaufskriterien erreicht",
                    "ticker": p.get("ticker"),
                    "severity": "critical",
                })
            else:
                alerts.append({
                    "type": "warning",
                    "category": "ma_critical",
                    "title": f"Unter 150-DMA: {p['name']}",
                    "message": f"{p['ticker']} — Fundamental-Check empfohlen. These noch intakt?",
                    "ticker": p.get("ticker"),
                    "severity": "warning",
                })

    # --- 4. Unter 50-DMA (Phase 3: differenziert nach Risk-Tier) ---
    for p in positions:
        if p.get("type") in ("cash", "pension"):
            continue
        if p.get("shares", 0) <= 0:
            continue
        if p.get("ma_status") == "WARNUNG":
            active_risk = _is_active_risk(p, buckets_map)
            if active_risk:
                alerts.append({
                    "type": "warning",
                    "category": "ma_warning",
                    "title": f"Unter 50-DMA: {p['name']}",
                    "message": f"{p['ticker']} unter der Trader Line — Stop-Loss überprüfen empfohlen",
                    "ticker": p.get("ticker"),
                    "severity": "medium",
                })
            else:
                alerts.append({
                    "type": "info",
                    "category": "ma_warning",
                    "title": f"Unter 50-DMA: {p['name']}",
                    "message": f"{p['ticker']} — Beobachten (kein Verkaufstrigger im aktuellen Bucket)",
                    "ticker": p.get("ticker"),
                    "severity": "info",
                })

    # --- 5. Market climate bearish ---
    if market_climate:
        status = market_climate.get("status", "")
        if status == "bearish":
            alerts.append({
                "type": "danger",
                "category": "market",
                "title": "Marktklima: BEARISCH",
                "message": "Marktumfeld negativ — erhöhte Vorsicht empfohlen.",
                "severity": "high",
            })

    # --- 6. VIX regime alerts ---
    if market_climate:
        vix_regime = market_climate.get("vix_regime")
        vix_data = market_climate.get("vix")
        vix_val = vix_data["value"] if vix_data and vix_data.get("value") else None
        if vix_regime == "risk_off" and vix_val:
            alerts.append({
                "type": "danger",
                "category": "vix",
                "title": f"VIX bei {vix_val:.1f} — RISK OFF",
                "message": "Marktumfeld kritisch — erhöhte Vorsicht empfohlen.",
                "severity": "critical",
            })
        elif vix_regime == "caution" and vix_val:
            alerts.append({
                "type": "warning",
                "category": "vix",
                "title": f"VIX bei {vix_val:.1f} — VORSICHT",
                "message": "Erhöhte Volatilität — Positionen überprüfen.",
                "severity": "medium",
            })

    # --- 6b. Macro environment alerts ---
    try:
        from services.macro_indicators_service import get_cached_indicators
        from services.macro_gate_service import calculate_macro_gate
        macro_data = get_cached_indicators()
        if macro_data:
            overall = macro_data.get("overall_status")
            if overall == "red":
                alerts.append({
                    "type": "danger",
                    "category": "market",
                    "title": "Marktumfeld: Risk Off",
                    "message": f"Marktumfeld kritisch — {macro_data.get('red_count', 0)} Indikatoren rot, {macro_data.get('yellow_count', 0)} gelb",
                    "severity": "high",
                })
            elif overall == "yellow":
                alerts.append({
                    "type": "warning",
                    "category": "market",
                    "title": "Marktumfeld: Vorsicht",
                    "message": f"{macro_data.get('yellow_count', 0)} Indikatoren gelb, {macro_data.get('red_count', 0)} rot",
                    "severity": "medium",
                })

            # Individual regime alerts
            for ind in macro_data.get("indicators", []):
                if ind["name"] == "vix" and ind.get("status") == "red" and ind.get("value"):
                    alerts.append({
                        "type": "danger",
                        "category": "vix",
                        "title": f"VIX bei {ind['value']:.1f} — Panik-Level",
                        "message": "Extremes Angstlevel im Markt",
                        "severity": "critical",
                    })
                elif ind["name"] == "yield_curve" and ind.get("status") == "red":
                    alerts.append({
                        "type": "warning",
                        "category": "market",
                        "title": "Zinsstruktur invertiert",
                        "message": "Historisches Rezessionssignal — Risiko erhöht",
                        "severity": "medium",
                    })
                elif ind["name"] == "shiller_pe" and ind.get("status") == "red" and ind.get("value"):
                    alerts.append({
                        "type": "warning",
                        "category": "market",
                        "title": f"Shiller PE bei {ind['value']:.1f}",
                        "message": "Markt historisch stark überbewertet",
                        "severity": "medium",
                    })

            # Gate status alert
            gate = calculate_macro_gate()
            if not gate.get("passed"):
                alerts.append({
                    "type": "warning",
                    "category": "market",
                    "title": f"Makro-Gate nicht bestanden ({gate['score']}/{gate['max_score']})",
                    "message": "Makro-Kriterien nicht erfüllt — erhöhte Vorsicht empfohlen",
                    "severity": "high",
                })
    except Exception as e:
        logger.warning(f"Macro alerts failed: {e}")

    # --- 7. Stop proximity + large losses (stop-based or fallback) ---
    for p in positions:
        if p.get("type") in ("cash", "pension"):
            continue
        if p.get("shares", 0) <= 0:
            continue

        sl = p.get("stop_loss_price")
        cp = p.get("current_price")

        if sl and cp and sl > 0:
            # Stop-based alerts
            if cp <= sl:
                alerts.append({
                    "type": "danger",
                    "category": "stop_reached",
                    "title": f"{p['name']}: Stop-Loss erreicht!",
                    "message": f"{p['ticker']} Kurs {cp:.2f} <= Stop {sl:.2f} — Verkaufskriterien erreicht",
                    "ticker": p.get("ticker"),
                    "severity": "critical",
                })
            else:
                dist_pct = (cp - sl) / cp * 100
                if dist_pct < stop_prox_pct:
                    alerts.append({
                        "type": "warning",
                        "category": "stop_proximity",
                        "title": f"{p['name']}: Kurs nähert sich dem Stop-Loss",
                        "message": f"{p['ticker']} nur noch {dist_pct:.1f}% über Stop ({sl:.2f})",
                        "ticker": p.get("ticker"),
                        "severity": "high",
                    })
        elif sl is None:
            # Fallback: no stop-loss set — use percentage-based loss alerts
            # Phase 3: Bucket-Rules statt position_type-Differenzierung
            pnl_pct = p.get("pnl_pct", 0)
            default_loss = satellite_loss_pct if _is_active_risk(p, buckets_map) else core_loss_pct
            threshold = _bucket_loss_pct(p, buckets_map, default_loss)
            if pnl_pct < threshold:
                alerts.append({
                    "type": "warning",
                    "category": "loss",
                    "title": f"Grosser Verlust: {p['name']}",
                    "message": f"{p['ticker']} bei {pnl_pct:.1f}% — Kein Stop-Loss gesetzt!",
                    "ticker": p.get("ticker"),
                    "severity": "high",
                })

    # --- 8. Stop-Loss: not set (Phase 3: nur fuer Active-Risk-Buckets, frueher Satellite) ---
    for p in positions:
        if p.get("type") in ("cash", "pension", "crypto", "commodity"):
            continue
        if p.get("shares", 0) <= 0:
            continue
        if p.get("stop_loss_price") is None:
            if not _is_active_risk(p, buckets_map):
                # Buy-and-hold-Buckets ohne Stop-Loss-Vorschlag = kein Pflicht-Alert
                continue
            alerts.append({
                "type": "danger",
                "category": "stop_loss_missing",
                "title": f"Kein Stop-Loss: {p['name']}",
                "message": f"{p['ticker']} hat keinen Stop-Loss gesetzt. Regel: Immer gleichzeitig mit dem Kauf setzen.",
                "ticker": p.get("ticker"),
                "severity": "critical",
            })

    # --- 9. Stop-Loss: not confirmed at broker ---
    for p in positions:
        if p.get("type") in ("cash", "pension"):
            continue
        if p.get("shares", 0) <= 0:
            continue
        if p.get("stop_loss_price") is not None and not p.get("stop_loss_confirmed_at_broker"):
            alerts.append({
                "type": "danger",
                "category": "stop_loss_unconfirmed",
                "title": f"Stop nicht bestätigt: {p['name']}",
                "message": f"{p['ticker']} Stop-Loss nicht bei Broker bestätigt",
                "ticker": p.get("ticker"),
                "severity": "critical",
            })

    # --- 10. Stop-Loss review (Phase 3: differenziert nach Risk-Tier) ---
    for p in positions:
        if p.get("type") in ("cash", "pension", "crypto", "commodity"):
            continue
        if p.get("shares", 0) <= 0:
            continue
        sl = p.get("stop_loss_price")
        cp = p.get("current_price")
        active_risk = _is_active_risk(p, buckets_map)

        dist = None
        if sl and cp and sl > 0:
            dist = (cp - sl) / sl * 100
            dist_threshold = SATELLITE_STOP_REVIEW_DISTANCE_PCT if active_risk else CORE_STOP_REVIEW_DISTANCE_PCT
            if dist > dist_threshold:
                alerts.append({
                    "type": "warning",
                    "category": "stop_loss_review",
                    "title": (f"Stop-Loss nachziehen: {p['name']}" if active_risk
                              else f"Buy-and-hold-Stop pruefen: {p['name']}"),
                    "message": f"{p['ticker']} Abstand zum Stop {dist:.1f}% — "
                               f"{'nachziehen empfohlen' if active_risk else 'quartalsweise pruefen'}",
                    "ticker": p.get("ticker"),
                    "severity": "medium",
                })

        # Days since update check
        updated_at = p.get("stop_loss_updated_at")
        if sl and updated_at:
            try:
                if isinstance(updated_at, str):
                    updated_at = datetime.fromisoformat(updated_at)
                days = (datetime.now() - updated_at).days
                days_threshold = SATELLITE_STOP_REVIEW_MAX_DAYS if active_risk else CORE_STOP_REVIEW_MAX_DAYS
                if days > days_threshold:
                    dist_str = f" — Abstand {dist:.1f}%" if dist is not None else ""
                    alerts.append({
                        "type": "warning",
                        "category": "stop_loss_age",
                        "title": (f"{p['ticker']}: Stop-Loss pruefen" if active_risk
                                  else f"{p['ticker']}: Buy-and-hold-Stop quartalsweise pruefen"),
                        "message": f"Letzte Aktualisierung vor {days} Tagen{dist_str}",
                        "ticker": p.get("ticker"),
                        "severity": "medium",
                    })
            except (ValueError, TypeError) as e:
                logger.debug(f"Could not parse stop-loss date for {p.get('ticker')}: {e}")

    # --- 11. Bucket-Zuordnung fehlt (Phase 3: position_type_missing -> bucket_missing) ---
    # Entfaellt komplett, weil bucket_id NOT NULL ist seit Migration 064.
    # Jede liquide Position hat einen Bucket (mindestens liquid_default).

    # --- 12. Bucket-Allokation-Warnungen (Phase 3: Per-Bucket target_pct) ---
    # Allokations-Drift-Warnungen werden ueber bucket.target_pct ausgewertet,
    # nicht mehr ueber globale 70/30-Core/Satellite-Ratios.
    if buckets_map:
        tradable = [p for p in positions if p.get("type") in ("stock", "etf") and p.get("shares", 0) > 0]
        tradable_total = sum(p["market_value_chf"] for p in tradable) if tradable else 0
        if tradable_total > 0:
            by_bucket: dict = {}
            for p in tradable:
                bid = p.get("bucket_id")
                if bid and bid in buckets_map:
                    by_bucket[bid] = by_bucket.get(bid, 0) + p["market_value_chf"]
            for bid, value in by_bucket.items():
                bucket = buckets_map[bid]
                # target_pct nur fuer user-Buckets relevant
                if bucket.get("kind") != "user":
                    continue
                target = bucket.get("target_pct")
                if target is None:
                    continue
                actual_pct = value / tradable_total * 100
                drift = actual_pct - float(target)
                # Drift > 10 Prozentpunkte: Warnung
                if abs(drift) > 10:
                    direction = "uebergewichtet" if drift > 0 else "untergewichtet"
                    alerts.append({
                        "type": "warning",
                        "category": "allocation",
                        "title": f"Bucket {bucket['name']} {direction}",
                        "message": f"Bucket bei {actual_pct:.0f}% statt Ziel {float(target):.0f}% (Drift {drift:+.0f} Prozentpunkte)",
                        "severity": "medium",
                    })

    # --- 13. Earnings date warning ---
    for p in positions:
        if p.get("type") not in ("stock", "etf"):
            continue
        if p.get("shares", 0) <= 0:
            continue
        ed = p.get("next_earnings_date")
        if not ed:
            continue
        try:
            if isinstance(ed, str):
                ed = datetime.fromisoformat(ed)
            days_until = (ed - datetime.now()).days
            if days_until < 0:
                continue
            active_risk = _is_active_risk(p, buckets_map)
            if active_risk and days_until <= 7:
                # Active-Risk-Bucket: 7-Tage-Regel — KEIN Kauf, Stop pruefen
                alerts.append({
                    "type": "warning",
                    "category": "earnings",
                    "title": f"⚠️ Earnings in {days_until}T: {p['name']}",
                    "message": f"{p['ticker']} meldet am {ed.strftime('%d.%m.%Y')} — Kein Kauf, Stop-Loss pruefen",
                    "ticker": p.get("ticker"),
                    "severity": "high" if days_until <= 3 else "medium",
                })
            elif not active_risk and days_until <= 14:
                # Buy-and-hold-Bucket: 14-Tage-Reminder — Fundamentals pruefen
                alerts.append({
                    "type": "info",
                    "category": "earnings",
                    "title": f"Earnings in {days_until}T: {p['name']}",
                    "message": f"{p['ticker']} meldet am {ed.strftime('%d.%m.%Y')} — Earnings-Checkliste durchgehen",
                    "ticker": p.get("ticker"),
                    "severity": "medium" if days_until <= 7 else "info",
                })
            elif days_until <= 7:
                # Untyped positions: generic warning
                alerts.append({
                    "type": "info",
                    "category": "earnings",
                    "title": f"Earnings in {days_until}T: {p['name']}",
                    "message": f"{p['ticker']} meldet am {ed.strftime('%d.%m.%Y')}",
                    "ticker": p.get("ticker"),
                    "severity": "info",
                })
        except (ValueError, TypeError) as e:
            logger.debug(f"Could not parse earnings date for {p.get('ticker')}: {e}")

    # --- 14. Multi-Sector ETF sector weights not configured ---
    for p in positions:
        if not p.get("is_multi_sector"):
            continue
        if p.get("shares", 0) <= 0:
            continue
        if not p.get("has_sector_weights"):
            alerts.append({
                "type": "info",
                "category": "etf_sector_missing",
                "title": f"{p['ticker']}: Sektorverteilung nicht gepflegt",
                "message": f"{p['ticker']} wird in Sektor-Allokation nicht aufgeschlüsselt",
                "ticker": p.get("ticker"),
                "severity": "info",
            })

    # --- 14b. Industry not assigned ---
    for p in positions:
        if p.get("type") in ("cash", "pension", "crypto", "commodity"):
            continue
        if p.get("shares", 0) <= 0:
            continue
        if not p.get("industry"):
            alerts.append({
                "type": "info",
                "category": "industry_missing",
                "title": f"{p['ticker']}: Branche nicht zugewiesen",
                "message": f"Für korrekte Sektor-Allokation bitte Branche zuweisen",
                "ticker": p.get("ticker"),
                "severity": "info",
            })

    # --- 15. Currency mismatch detection ---
    currency_mismatches = cache.get("currency_mismatches") or []
    for mm in currency_mismatches:
        alerts.append({
            "type": "danger",
            "category": "currency_mismatch",
            "title": f"{mm['ticker']}: Währungskonflikt",
            "message": (
                f"Position ist in {mm['pos_currency']}, aber {mm['yf_ticker']} liefert Preise in "
                f"{mm['yf_currency']}. Falscher Ticker? Versuche z.B. {mm['ticker']}.TO für TSX."
            ),
            "ticker": mm["ticker"],
            "severity": "critical",
        })

    # --- 16. Stale price data ---
    stale_tickers = [p["ticker"] for p in positions if p.get("is_stale")]
    if stale_tickers:
        alerts.append({
            "type": "danger",
            "category": "data_quality",
            "title": "Veraltete Kursdaten",
            "message": f"Kein aktueller Kurs für: {', '.join(stale_tickers)}. Angezeigte Werte sind möglicherweise falsch.",
            "severity": "critical",
        })

    # --- 17. ETF unter 200-DMA — Kaufkriterien erfüllt (Broad Index Whitelist) ---
    seen_etf_200dma: set[str] = set()
    for p in positions:
        if p.get("type") not in ("etf", "stock"):
            continue
        if p.get("shares", 0) <= 0:
            continue
        ticker = p.get("ticker", "")
        if not is_broad_etf(ticker):
            continue
        ma_detail = p.get("ma_detail") or {}
        if ma_detail.get("above_ma200") is False:
            seen_etf_200dma.add(ticker)
            alerts.append({
                "type": "positive",
                "category": "etf_200dma_buy",
                "title": f"ETF unter 200-DMA: {p.get('name', ticker)}",
                "message": f"{ticker} handelt unter der 200-Tage-Linie — Kaufkriterien gemäss Strategie erfüllt",
                "ticker": ticker,
                "severity": "positive",
            })

    # Also check watchlist tickers for broad ETFs under 200-DMA
    for wt in (watchlist_tickers or []):
        ticker = wt.get("ticker", "")
        if ticker in seen_etf_200dma:
            continue
        if not is_broad_etf(ticker):
            continue
        ma_detail = wt.get("ma_detail") or {}
        if ma_detail.get("above_ma200") is False:
            seen_etf_200dma.add(ticker)
            alerts.append({
                "type": "positive",
                "category": "etf_200dma_buy",
                "title": f"ETF unter 200-DMA: {wt.get('name', ticker)}",
                "message": f"{ticker} (Watchlist) handelt unter der 200-Tage-Linie — Kaufkriterien gemäss Strategie erfüllt",
                "ticker": ticker,
                "severity": "positive",
            })

    # --- Filter by user preferences ---
    category_toggle = {
        "position_limit": "position_limit",
        "sector_limit": "sector_limit",
        "ma_critical": "ma_critical",
        "ma_warning": "ma_warning",
        "market": "market_climate",
        "vix": "vix",
        "stop_reached": "stop_proximity",
        "stop_proximity": "stop_proximity",
        "loss": "loss",
        "stop_loss_missing": "stop_missing",
        "stop_loss_unconfirmed": "stop_unconfirmed",
        "stop_loss_review": "stop_review",
        "stop_loss_age": "stop_review",
        "allocation": "allocation",
        "earnings": "earnings",
        "industry_missing": "industry_missing",
        "etf_200dma_buy": "etf_200dma_buy",
        "currency_mismatch": None,  # always show
        "data_quality": None,  # always show
    }
    alerts = [a for a in alerts if category_toggle.get(a["category"]) is None or _enabled(category_toggle[a["category"]])]

    # --- Sort by severity ---
    severity_order = {"critical": 0, "high": 1, "medium": 2, "info": 3, "positive": 4}
    alerts.sort(key=lambda a: severity_order.get(a["severity"], 4))
    return alerts
