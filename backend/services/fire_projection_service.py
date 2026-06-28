"""FIRE-/Kapital-Projektion (real, d.h. inflationsbereinigt — Ziel in heutigen CHF).

Reiner, zustandsloser Rechner: Startkapital aus dem echten Vermoegen
(net_worth_service), alle Annahmen als Parameter (UI-Regler). Projiziert das
Kapital Jahr fuer Jahr (capital_{t+1} = capital_t*(1+r) + Sparrate) und bestimmt
die FIRE-Zahl (Ziel-Jahresausgaben / Entnahmerate) sowie Jahre-bis-FIRE.

Bewusst real: Rendite + Ausgaben in heutiger Kaufkraft, keine separate Inflations-
Modellierung. Beruehrt keine Korrektheits-Invariante (read-only Projektion).
"""
from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from services.net_worth_service import get_net_worth

_MAX_HORIZON = 60


async def compute_fire_projection(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    capital_base: str = "net_worth",
    annual_return_pct: float = 5.0,
    annual_savings_chf: float = 40000.0,
    withdrawal_rate_pct: float = 4.0,
    target_annual_spending_chf: float | None = None,
    horizon_years: int = 40,
) -> dict:
    nw = await get_net_worth(db, user_id)
    comp = {c["key"]: float(c["value_chf"]) for c in nw.get("components", [])}
    securities = comp.get("securities", 0.0)
    cash = comp.get("cash", 0.0)
    pension = comp.get("pension", 0.0)

    if capital_base == "liquid":
        start = securities + cash
    elif capital_base == "with_pension":
        start = securities + cash + pension
    else:
        capital_base = "net_worth"
        start = float(nw.get("net_worth_chf") or 0.0)

    r = annual_return_pct / 100.0
    horizon = max(1, min(int(horizon_years), _MAX_HORIZON))

    fire_number = None
    if target_annual_spending_chf and withdrawal_rate_pct and withdrawal_rate_pct > 0:
        fire_number = round(float(target_annual_spending_chf) / (withdrawal_rate_pct / 100.0), 2)

    curve = [{"year": 0, "capital_chf": round(start, 2)}]
    cap = start
    years_to_fire = 0 if (fire_number is not None and start >= fire_number) else None
    for y in range(1, horizon + 1):
        cap = cap * (1.0 + r) + float(annual_savings_chf)
        curve.append({"year": y, "capital_chf": round(cap, 2)})
        if fire_number is not None and years_to_fire is None and cap >= fire_number:
            years_to_fire = y

    coverage = round(start / fire_number * 100.0, 1) if fire_number else None

    return {
        "capital_base": capital_base,
        "starting_capital_chf": round(start, 2),
        "fire_number_chf": fire_number,
        "years_to_fire": years_to_fire,      # None = im Horizont nicht erreicht (oder kein Ziel gesetzt)
        "coverage_pct": coverage,            # heutiges Kapital / FIRE-Zahl
        "final_capital_chf": round(cap, 2),
        "assumptions": {
            "annual_return_pct": annual_return_pct,
            "annual_savings_chf": float(annual_savings_chf),
            "withdrawal_rate_pct": withdrawal_rate_pct,
            "target_annual_spending_chf": float(target_annual_spending_chf) if target_annual_spending_chf else None,
            "horizon_years": horizon,
            "real_terms": True,
        },
        "projection": curve,
    }
