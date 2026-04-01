import logging
import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from models.property import Property, Mortgage, PropertyExpense, PropertyIncome
from services.auth_service import decrypt_value

logger = logging.getLogger(__name__)


def _decrypt_field(value):
    if not value:
        return value
    try:
        return decrypt_value(value)
    except Exception:
        logger.debug("Decryption failed, treating as legacy plaintext")
        return value  # Legacy plaintext


def _months_between(d1: date, d2: date) -> int:
    return (d2.year - d1.year) * 12 + (d2.month - d1.month)


def calculate_effective_rate(mortgage: Mortgage, saron_rate: float | None = None) -> float:
    """Calculate effective interest rate for a mortgage.

    For SARON mortgages with margin_rate set: max(margin_rate, margin_rate + saron_rate)
    For SARON without margin_rate: fallback to interest_rate (backwards compatible)
    For fixed/variable: use interest_rate as-is.
    """
    if mortgage.type and mortgage.type.value == "saron" and mortgage.margin_rate is not None:
        margin = float(mortgage.margin_rate)
        if saron_rate is not None:
            return round(max(margin, margin + saron_rate), 3)
        return margin
    return float(mortgage.interest_rate)


def _mortgage_to_dict(m: Mortgage, saron_rate: float | None = None) -> dict:
    today = date.today()
    months_elapsed = max(0, _months_between(m.start_date, today)) if m.start_date else 0
    amort_monthly = float(m.amortization_monthly or 0)
    total_amortized = amort_monthly * months_elapsed
    current_amount = float(m.amount) - total_amortized

    days_until_maturity = None
    if m.end_date:
        days_until_maturity = max(0, (m.end_date - today).days)

    monthly_interest = float(m.monthly_payment) if m.monthly_payment is not None else 0
    monthly_total = monthly_interest + amort_monthly

    effective_rate = calculate_effective_rate(m, saron_rate)

    return {
        "id": str(m.id),
        "property_id": str(m.property_id),
        "name": m.name,
        "type": m.type.value if m.type else None,
        "amount": float(m.amount),
        "current_amount": round(current_amount, 2),
        "total_amortized": round(total_amortized, 2),
        "interest_rate": float(m.interest_rate),
        "margin_rate": float(m.margin_rate) if m.margin_rate is not None else None,
        "effective_rate": effective_rate,
        "start_date": m.start_date.isoformat() if m.start_date else None,
        "end_date": m.end_date.isoformat() if m.end_date else None,
        "monthly_payment": float(m.monthly_payment) if m.monthly_payment is not None else None,
        "monthly_total": round(monthly_total, 2),
        "annual_payment": float(m.annual_payment) if m.annual_payment is not None else None,
        "amortization_monthly": float(m.amortization_monthly) if m.amortization_monthly is not None else None,
        "amortization_annual": float(m.amortization_annual) if m.amortization_annual is not None else None,
        "bank": m.bank,
        "notes": m.notes,
        "is_active": m.is_active,
        "days_until_maturity": days_until_maturity,
    }


def _expense_to_dict(e: PropertyExpense) -> dict:
    return {
        "id": str(e.id),
        "property_id": str(e.property_id),
        "date": e.date.isoformat(),
        "category": e.category.value if e.category else None,
        "description": e.description,
        "amount": float(e.amount),
        "recurring": e.recurring,
        "frequency": e.frequency.value if e.frequency else None,
    }


def _income_to_dict(i: PropertyIncome) -> dict:
    return {
        "id": str(i.id),
        "property_id": str(i.property_id),
        "date": i.date.isoformat(),
        "description": i.description,
        "amount": float(i.amount),
        "tenant": i.tenant,
        "recurring": i.recurring,
        "frequency": i.frequency.value if i.frequency else None,
    }


def _property_to_dict(prop: Property, include_details: bool = True, saron_rate: float | None = None) -> dict:
    today = date.today()
    current_year = today.year

    value = float(prop.estimated_value or prop.purchase_price)

    active_mortgages = [m for m in prop.mortgages if m.is_active]
    mortgage_dicts = [_mortgage_to_dict(m, saron_rate=saron_rate) for m in active_mortgages]

    total_mortgage_original = sum(float(m.amount) for m in active_mortgages)
    total_amortized = sum(md["total_amortized"] for md in mortgage_dicts)
    current_mortgage = sum(md["current_amount"] for md in mortgage_dicts)
    total_monthly = sum(md["monthly_total"] for md in mortgage_dicts)

    equity = value - current_mortgage
    equity_pct = (equity / value * 100) if value > 0 else 0
    ltv = (current_mortgage / value * 100) if value > 0 else 0

    if ltv <= 66.7:
        ltv_status = "green"
    elif ltv <= 80:
        ltv_status = "yellow"
    else:
        ltv_status = "red"

    annual_interest = sum(
        float(m.amount) * calculate_effective_rate(m, saron_rate) / 100
        for m in active_mortgages
    )
    annual_amortization = sum(
        float(m.amortization_annual or 0) for m in active_mortgages
    )

    year_expenses = [e for e in prop.expenses if e.date.year == current_year]
    year_income = [i for i in prop.incomes if i.date.year == current_year]
    annual_expenses = sum(float(e.amount) for e in year_expenses)
    annual_income = sum(float(i.amount) for i in year_income)

    total_annual_cost = annual_interest + annual_amortization + annual_expenses
    net_annual = annual_income - annual_expenses

    next_maturity = None
    days_until_maturity = None
    for md in mortgage_dicts:
        if md["end_date"] and md["days_until_maturity"] is not None:
            if next_maturity is None or md["end_date"] < next_maturity:
                next_maturity = md["end_date"]
                days_until_maturity = md["days_until_maturity"]

    unrealized_gain = value - float(prop.purchase_price)
    unrealized_gain_pct = (unrealized_gain / float(prop.purchase_price) * 100) if float(prop.purchase_price) > 0 else 0

    result = {
        "id": str(prop.id),
        "name": _decrypt_field(prop.name),
        "address": _decrypt_field(prop.address),
        "property_type": prop.property_type.value if prop.property_type else None,
        "purchase_date": prop.purchase_date.isoformat() if prop.purchase_date else None,
        "purchase_price": float(prop.purchase_price),
        "estimated_value": value,
        "estimated_value_date": prop.estimated_value_date.isoformat() if prop.estimated_value_date else None,
        "land_area_m2": float(prop.land_area_m2) if prop.land_area_m2 else None,
        "living_area_m2": float(prop.living_area_m2) if prop.living_area_m2 else None,
        "rooms": float(prop.rooms) if prop.rooms else None,
        "year_built": prop.year_built,
        "canton": prop.canton,
        "notes": _decrypt_field(prop.notes),
        "is_active": prop.is_active,
        "total_mortgage_original": round(total_mortgage_original, 2),
        "total_amortized": round(total_amortized, 2),
        "current_mortgage": round(current_mortgage, 2),
        "total_monthly": round(total_monthly, 2),
        "equity": round(equity, 2),
        "equity_pct": round(equity_pct, 1),
        "ltv": round(ltv, 1),
        "ltv_status": ltv_status,
        "annual_interest": round(annual_interest, 2),
        "annual_amortization": round(annual_amortization, 2),
        "annual_expenses": round(annual_expenses, 2),
        "annual_income": round(annual_income, 2),
        "total_annual_cost": round(total_annual_cost, 2),
        "net_annual": round(net_annual, 2),
        "next_maturity": next_maturity,
        "days_until_maturity": days_until_maturity,
        "unrealized_gain": round(unrealized_gain, 2),
        "unrealized_gain_pct": round(unrealized_gain_pct, 1),
    }

    if include_details:
        result["mortgages"] = mortgage_dicts
        result["expenses"] = [_expense_to_dict(e) for e in year_expenses]
        result["income"] = [_income_to_dict(i) for i in year_income]

    return result


async def get_properties_summary(db: AsyncSession, user_id: uuid.UUID | None = None) -> dict:
    stmt = (
        select(Property)
        .where(Property.is_active == True)
        .options(
            selectinload(Property.mortgages),
            selectinload(Property.expenses),
            selectinload(Property.incomes),
        )
    )
    if user_id is not None:
        stmt = stmt.where(Property.user_id == user_id)
    result = await db.execute(stmt)
    properties = result.scalars().all()

    # Fetch SARON rate for dynamic mortgage calculations
    market_data = await get_real_estate_market_data()
    saron = market_data.get("saron_rate")

    prop_dicts = [_property_to_dict(p, saron_rate=saron) for p in properties]

    total_value = sum(p["estimated_value"] for p in prop_dicts)
    total_mortgage = sum(p["current_mortgage"] for p in prop_dicts)
    total_equity = sum(p["equity"] for p in prop_dicts)

    return {
        "properties": prop_dicts,
        "total_value_chf": round(total_value, 2),
        "total_mortgage_chf": round(total_mortgage, 2),
        "total_equity_chf": round(total_equity, 2),
    }


async def get_property_detail(db: AsyncSession, property_id: uuid.UUID, user_id: uuid.UUID | None = None) -> dict | None:
    stmt = (
        select(Property)
        .where(Property.id == property_id)
        .options(
            selectinload(Property.mortgages),
            selectinload(Property.expenses),
            selectinload(Property.incomes),
        )
    )
    if user_id is not None:
        stmt = stmt.where(Property.user_id == user_id)
    result = await db.execute(stmt)
    prop = result.scalar_one_or_none()
    if not prop:
        return None

    market_data = await get_real_estate_market_data()
    saron = market_data.get("saron_rate")
    return _property_to_dict(prop, saron_rate=saron)


import json
import logging

import httpx

from dateutils import utcnow
from db import async_session
from models.app_config import AppConfig
from sqlalchemy import select

_logger = logging.getLogger(__name__)

# In-memory cache for SARON (avoids DB round-trip on every request)
_saron_cache: dict | None = None


async def fetch_saron_rate() -> dict | None:
    """Fetch current SARON rate from SNB Data Portal and persist to DB."""
    try:
        url = "https://data.snb.ch/api/cube/snbgwdzid/data/csv/en"
        params = {"dimSel": "D0(SARON)"}
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, params=params, timeout=15)
            resp.raise_for_status()

        lines = resp.text.strip().split("\n")

        last_date = None
        last_value = None

        for line in reversed(lines):
            parts = line.split(";")
            if len(parts) < 2:
                parts = line.split(",")
            if len(parts) >= 2:
                try:
                    value = float(parts[-1].strip().replace('"', ''))
                    date_str = parts[0].strip().replace('"', '')
                    last_date = date_str
                    last_value = value
                    break
                except ValueError:
                    continue  # Expected: parsing CSV rows with non-numeric values

        if last_value is not None:
            _logger.info(f"SNB SARON: {last_value}% (Date: {last_date})")
            result = {"rate": last_value, "date": last_date, "source": "SNB"}
            await _persist_saron(result)
            return result

        _logger.warning("Could not parse SARON value from SNB CSV")
        return None

    except Exception as e:
        _logger.error(f"SNB SARON fetch failed: {e}")
        return None


async def _persist_saron(data: dict):
    """Save SARON rate to app_config DB table and update in-memory cache."""
    global _saron_cache
    now = utcnow()
    value_json = json.dumps(data)
    try:
        async with async_session() as db:
            result = await db.execute(
                select(AppConfig).where(AppConfig.key == "saron_rate")
            )
            row = result.scalar_one_or_none()
            if row:
                row.value = value_json
                row.updated_at = now
            else:
                db.add(AppConfig(key="saron_rate", value=value_json, updated_at=now))
            await db.commit()
        _saron_cache = {**data, "fetched_at": now.isoformat()}
    except Exception as e:
        _logger.error(f"Failed to persist SARON to DB: {e}")


async def get_real_estate_market_data() -> dict:
    """Return SARON rate from cache → DB → defaults."""
    global _saron_cache

    if _saron_cache:
        return {
            "saron_rate": _saron_cache["rate"],
            "saron_date": _saron_cache["date"],
            "saron_source": _saron_cache["source"],
            "saron_fetched_at": _saron_cache.get("fetched_at"),
        }

    # Load from DB
    try:
        async with async_session() as db:
            result = await db.execute(
                select(AppConfig).where(AppConfig.key == "saron_rate")
            )
            row = result.scalar_one_or_none()
            if row:
                data = json.loads(row.value)
                _saron_cache = {**data, "fetched_at": row.updated_at.isoformat()}
                return {
                    "saron_rate": data["rate"],
                    "saron_date": data["date"],
                    "saron_source": data["source"],
                    "saron_fetched_at": row.updated_at.isoformat(),
                }
    except Exception as e:
        _logger.warning(f"Failed to load SARON from DB: {e}")

    return {
        "saron_rate": None,
        "saron_date": None,
        "saron_source": "nicht verfügbar",
        "saron_fetched_at": None,
    }
