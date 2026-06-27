"""Netto-Vermoegen: konsolidiertes Gesamtbild inkl. Immobilien (brutto) und
Hypothek als explizite Verbindlichkeit.

Netto-Vermoegen = Finanzanlagen (Wertschriften + Cash + Vorsorge + Private Equity,
aus portfolio_service) + Immobilien (Brutto) − Hypothek (amortisierte Restschuld).
Bewusst KEINE liquide Performance-Sicht (das ist Invariante #2); dies ist das
Gesamtvermoegen (Konzept A) minus Verbindlichkeiten. Komponenten werden aus den
Positions-Marktwerten direkt kategorisiert (jede Position genau einmal -> kein
Doppelzaehlen). Real-Estate-Positionen (shares=0) sind NICHT in der Summary; ihr
Wert kommt aus property_service (estimated_value bzw. purchase_price).
"""
from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from services.portfolio_service import get_portfolio_summary
from services.property_service import get_properties_summary


async def get_net_worth(db: AsyncSession, user_id: uuid.UUID) -> dict:
    summary = await get_portfolio_summary(db, user_id=user_id)
    props = await get_properties_summary(db, user_id)

    cats = {"securities": 0.0, "cash": 0.0, "pension": 0.0, "private_equity": 0.0}
    for p in summary.get("positions", []):
        mv = float(p.get("market_value_chf") or 0)
        t = p.get("type")
        if t == "pension":
            cats["pension"] += mv
        elif t == "private_equity":
            cats["private_equity"] += mv
        elif t == "cash" or p.get("count_as_cash"):
            cats["cash"] += mv
        elif t in ("stock", "etf", "crypto", "commodity"):
            cats["securities"] += mv

    re_gross = float(props.get("total_value_chf") or 0)
    mortgage = float(props.get("total_mortgage_chf") or 0)

    total_assets = cats["securities"] + cats["cash"] + cats["pension"] + cats["private_equity"] + re_gross
    net_worth = total_assets - mortgage

    components = [
        {"key": "securities", "label": "Wertschriften", "value_chf": round(cats["securities"], 2), "kind": "asset"},
        {"key": "cash", "label": "Cash", "value_chf": round(cats["cash"], 2), "kind": "asset"},
        {"key": "pension", "label": "Vorsorge", "value_chf": round(cats["pension"], 2), "kind": "asset"},
        {"key": "private_equity", "label": "Private Equity", "value_chf": round(cats["private_equity"], 2), "kind": "asset"},
        {"key": "real_estate", "label": "Immobilien (Brutto)", "value_chf": round(re_gross, 2), "kind": "asset"},
        {"key": "mortgage", "label": "Hypothek", "value_chf": round(-mortgage, 2), "kind": "liability"},
    ]
    components = [c for c in components if abs(c["value_chf"]) > 0.005]

    return {
        "net_worth_chf": round(net_worth, 2),
        "total_assets_chf": round(total_assets, 2),
        "total_liabilities_chf": round(mortgage, 2),
        "has_real_estate": re_gross > 0 or mortgage > 0,
        "components": components,
    }
