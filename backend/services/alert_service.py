"""Generate alerts based on portfolio rules and market conditions."""

import logging
from datetime import datetime

from services import cache
from services.sector_mapping import is_broad_etf

logger = logging.getLogger(__name__)

# --- Configurable thresholds ---

# Stop-Loss Review
SATELLITE_STOP_REVIEW_DISTANCE_PCT = 15.0
SATELLITE_STOP_REVIEW_MAX_DAYS = 14
CORE_STOP_REVIEW_DISTANCE_PCT = 30.0
CORE_STOP_REVIEW_MAX_DAYS = 90

# Position limits (% of liquid portfolio)
CORE_STOCK_MAX_PCT = 10.0
SATELLITE_STOCK_MAX_PCT = 5.0
CORE_ETF_MAX_PCT = 15.0
SATELLITE_ETF_MAX_PCT = 10.0
COMMODITY_HEDGE_MAX_PCT = 15.0
SECTOR_MAX_PCT = 25.0

# Loss thresholds (fallback when no stop-loss set)
SATELLITE_LOSS_WARNING_PCT = -15.0
CORE_LOSS_WARNING_PCT = -25.0

# Stop proximity
STOP_PROXIMITY_WARNING_PCT = 3.0


def _get_position_limit(p: dict) -> tuple[float, str]:
    """Return (max_pct, label) for a position based on type and position_type."""
    asset_type = p.get("type", "")
    pos_type = p.get("position_type")

    if asset_type in ("crypto", "commodity"):
        return COMMODITY_HEDGE_MAX_PCT, "Rohstoff/Hedge"
    if asset_type == "etf":
        if pos_type == "core":
            return CORE_ETF_MAX_PCT, "Core-ETF"
        return SATELLITE_ETF_MAX_PCT, "Satellite-ETF"
    # stock
    if pos_type == "core":
        return CORE_STOCK_MAX_PCT, "Core-Aktie"
    if pos_type == "satellite":
        return SATELLITE_STOCK_MAX_PCT, "Satellite-Aktie"
    return CORE_STOCK_MAX_PCT, "Aktie"


def generate_alerts(positions: list[dict], market_climate: dict | None, user_prefs: dict | None = None, watchlist_tickers: list[dict] | None = None) -> list[dict]:
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

    # --- 1. Position limits (differentiated by type) ---
    for p in positions:
        if p.get("type") in ("cash", "pension"):
            continue
        if p.get("shares", 0) <= 0:
            continue
        pct = p["market_value_chf"] / total_value * 100
        limit, label = _get_position_limit(p)
        if pct > limit:
            alerts.append({
                "type": "warning",
                "category": "position_limit",
                "title": f"Positions-Limit: {p['name']}",
                "message": f"{p['ticker']} bei {pct:.1f}% des liquiden Vermögens (Max: {limit:.0f}% für {label})",
                "ticker": p.get("ticker"),
                "severity": "high" if pct > limit + 5 else "medium",
            })

    # --- 2. Sector limits ---
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

    # --- 3. Unter 150-DMA (Schwur 1) — differentiated by position type ---
    for p in positions:
        if p.get("type") in ("cash", "pension"):
            continue
        if p.get("shares", 0) <= 0:
            continue
        if p.get("ma_status") == "KRITISCH":
            pos_type = p.get("position_type")
            if pos_type == "core":
                alerts.append({
                    "type": "warning",
                    "category": "ma_critical",
                    "title": f"Unter 150-DMA: {p['name']}",
                    "message": f"{p['ticker']} — Fundamental-Check empfohlen. These noch intakt?",
                    "ticker": p.get("ticker"),
                    "severity": "warning",
                })
            elif pos_type == "satellite":
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
                    "type": "danger",
                    "category": "ma_critical",
                    "title": f"Unter 150-DMA: {p['name']}",
                    "message": f"{p['ticker']} handelt unter der Investor Line (150-DMA)",
                    "ticker": p.get("ticker"),
                    "severity": "critical",
                })

    # --- 4. Unter 50-DMA (differentiated) ---
    for p in positions:
        if p.get("type") in ("cash", "pension"):
            continue
        if p.get("shares", 0) <= 0:
            continue
        if p.get("ma_status") == "WARNUNG":
            pos_type = p.get("position_type")
            if pos_type == "core":
                alerts.append({
                    "type": "info",
                    "category": "ma_warning",
                    "title": f"Unter 50-DMA: {p['name']}",
                    "message": f"{p['ticker']} — Beobachten (kein Core-Verkaufstrigger)",
                    "ticker": p.get("ticker"),
                    "severity": "info",
                })
            elif pos_type == "satellite":
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
                    "type": "warning",
                    "category": "ma_warning",
                    "title": f"Unter 50-DMA: {p['name']}",
                    "message": f"{p['ticker']} unter der Trader Line — Positions-Typ zuweisen für differenzierte Alerts",
                    "ticker": p.get("ticker"),
                    "severity": "medium",
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
        pos_type = p.get("position_type")

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
            pnl_pct = p.get("pnl_pct", 0)
            if pos_type == "satellite" and pnl_pct < satellite_loss_pct:
                alerts.append({
                    "type": "warning",
                    "category": "loss",
                    "title": f"Grosser Verlust: {p['name']}",
                    "message": f"{p['ticker']} bei {pnl_pct:.1f}% — Kein Stop-Loss gesetzt!",
                    "ticker": p.get("ticker"),
                    "severity": "high",
                })
            elif pos_type == "core" and pnl_pct < core_loss_pct:
                alerts.append({
                    "type": "warning",
                    "category": "loss",
                    "title": f"Grosser Verlust: {p['name']}",
                    "message": f"{p['ticker']} bei {pnl_pct:.1f}% — Kein Stop-Loss gesetzt!",
                    "ticker": p.get("ticker"),
                    "severity": "high",
                })
            elif not pos_type and pnl_pct < satellite_loss_pct:
                alerts.append({
                    "type": "warning",
                    "category": "loss",
                    "title": f"Grosser Verlust: {p['name']}",
                    "message": f"{p['ticker']} bei {pnl_pct:.1f}% — Kein Stop-Loss gesetzt!",
                    "ticker": p.get("ticker"),
                    "severity": "high",
                })

    # --- 8. Stop-Loss: not set (only for Satellite — Core has no technical stop requirement) ---
    for p in positions:
        if p.get("type") in ("cash", "pension", "crypto", "commodity"):
            continue
        if p.get("shares", 0) <= 0:
            continue
        if p.get("stop_loss_price") is None:
            pos_type = p.get("position_type")
            if pos_type == "core":
                # Core positions don't require a technical stop-loss
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

    # --- 10. Stop-Loss review (differentiated) ---
    for p in positions:
        if p.get("type") in ("cash", "pension", "crypto", "commodity"):
            continue
        if p.get("shares", 0) <= 0:
            continue
        sl = p.get("stop_loss_price")
        cp = p.get("current_price")
        is_core = p.get("position_type") == "core"

        dist = None
        if sl and cp and sl > 0:
            dist = (cp - sl) / sl * 100
            dist_threshold = CORE_STOP_REVIEW_DISTANCE_PCT if is_core else SATELLITE_STOP_REVIEW_DISTANCE_PCT
            if dist > dist_threshold:
                if is_core:
                    alerts.append({
                        "type": "warning",
                        "category": "stop_loss_review",
                        "title": f"Core-Stop prüfen: {p['name']}",
                        "message": f"{p['ticker']} Abstand zum Stop {dist:.1f}% — quartalsweise prüfen",
                        "ticker": p.get("ticker"),
                        "severity": "medium",
                    })
                else:
                    alerts.append({
                        "type": "warning",
                        "category": "stop_loss_review",
                        "title": f"Stop-Loss nachziehen: {p['name']}",
                        "message": f"{p['ticker']} Abstand zum Stop {dist:.1f}% — nachziehen empfohlen",
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
                days_threshold = CORE_STOP_REVIEW_MAX_DAYS if is_core else SATELLITE_STOP_REVIEW_MAX_DAYS
                if days > days_threshold:
                    dist_str = f" — Abstand {dist:.1f}%" if dist is not None else ""
                    if is_core:
                        alerts.append({
                            "type": "warning",
                            "category": "stop_loss_age",
                            "title": f"{p['ticker']}: Core-Stop quartalsweise prüfen",
                            "message": f"Letzte Aktualisierung vor {days} Tagen{dist_str}",
                            "ticker": p.get("ticker"),
                            "severity": "medium",
                        })
                    else:
                        alerts.append({
                            "type": "warning",
                            "category": "stop_loss_age",
                            "title": f"{p['ticker']}: Stop-Loss prüfen",
                            "message": f"Letzte Aktualisierung vor {days} Tagen{dist_str}",
                            "ticker": p.get("ticker"),
                            "severity": "medium",
                        })
            except (ValueError, TypeError) as e:
                logger.debug(f"Could not parse stop-loss date for {p.get('ticker')}: {e}")

    # --- 11. Position type: not assigned ---
    for p in positions:
        if p.get("type") not in ("stock", "etf"):
            continue
        if p.get("shares", 0) <= 0:
            continue
        if not p.get("position_type"):
            alerts.append({
                "type": "danger",
                "category": "position_type_missing",
                "title": f"{p['ticker']}: Kein Positions-Typ zugewiesen",
                "message": "Bitte Core oder Satellite zuweisen",
                "ticker": p.get("ticker"),
                "severity": "critical",
            })

    # --- 12. Core/Satellite allocation warnings ---
    tradable = [p for p in positions if p.get("type") in ("stock", "etf") and p.get("shares", 0) > 0]
    tradable_total = sum(p["market_value_chf"] for p in tradable) if tradable else 0
    if tradable_total > 0:
        satellite_val = sum(p["market_value_chf"] for p in tradable if p.get("position_type") == "satellite")
        core_val = sum(p["market_value_chf"] for p in tradable if p.get("position_type") == "core")
        sat_pct = satellite_val / tradable_total * 100
        core_pct = core_val / tradable_total * 100
        if sat_pct > 35:
            alerts.append({
                "type": "warning",
                "category": "allocation_satellite",
                "title": "Satellite übergewichtet",
                "message": f"Satellite bei {sat_pct:.0f}% statt Ziel 30%",
                "severity": "medium",
            })
        if core_pct < 60 and core_val > 0:
            alerts.append({
                "type": "warning",
                "category": "allocation_core",
                "title": "Core untergewichtet",
                "message": f"Core bei {core_pct:.0f}% statt Ziel 70%",
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
            is_satellite = p.get("position_type") == "satellite"
            is_core = p.get("position_type") == "core"
            if is_satellite and days_until <= 7:
                # Satellite: 7-Tage-Regel — KEIN Kauf, Stop prüfen
                alerts.append({
                    "type": "warning",
                    "category": "earnings",
                    "title": f"⚠️ Earnings in {days_until}T: {p['name']}",
                    "message": f"{p['ticker']} meldet am {ed.strftime('%d.%m.%Y')} — Kein Satellite-Kauf, Stop-Loss prüfen",
                    "ticker": p.get("ticker"),
                    "severity": "high" if days_until <= 3 else "medium",
                })
            elif is_core and days_until <= 14:
                # Core: 14-Tage-Reminder — Fundamentals prüfen (Earnings-Checkliste)
                alerts.append({
                    "type": "info",
                    "category": "earnings",
                    "title": f"Earnings in {days_until}T: {p['name']}",
                    "message": f"{p['ticker']} meldet am {ed.strftime('%d.%m.%Y')} — Core Earnings-Checkliste durchgehen",
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
        "position_type_missing": "position_type_missing",
        "allocation_satellite": "allocation",
        "allocation_core": "allocation",
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
