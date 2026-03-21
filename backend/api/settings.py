"""User settings and data export endpoints."""

import csv
import io
import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select, delete, func
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from db import get_db
from models.user import User, UserSettings
from models.position import Position
from models.transaction import Transaction
from models.alert_preference import AlertPreference
from models.smtp_config import SmtpConfig

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/settings", tags=["settings"])

VALID_CURRENCIES = {"CHF", "EUR", "USD"}
VALID_BROKERS = {"swissquote", "interactive_brokers", "other"}
VALID_SL_METHODS = {"trailing_pct", "higher_low", "ma_based"}
VALID_NUMBER_FORMATS = {"ch", "de", "en"}
VALID_DATE_FORMATS = {"dd.mm.yyyy", "yyyy-mm-dd"}


class SettingsUpdate(BaseModel):
    base_currency: Optional[str] = None
    broker: Optional[str] = None
    default_stop_loss_method: Optional[str] = None
    stop_loss_review_distance_pct: Optional[float] = None
    stop_loss_review_max_days: Optional[int] = None
    number_format: Optional[str] = None
    date_format: Optional[str] = None
    # Alert toggles
    alert_stop_missing: Optional[bool] = None
    alert_stop_unconfirmed: Optional[bool] = None
    alert_stop_proximity: Optional[bool] = None
    alert_stop_review: Optional[bool] = None
    alert_ma_critical: Optional[bool] = None
    alert_ma_warning: Optional[bool] = None
    alert_position_limit: Optional[bool] = None
    alert_sector_limit: Optional[bool] = None
    alert_loss: Optional[bool] = None
    alert_market_climate: Optional[bool] = None
    alert_vix: Optional[bool] = None
    alert_earnings: Optional[bool] = None
    alert_allocation: Optional[bool] = None
    alert_position_type_missing: Optional[bool] = None
    # Alert thresholds
    alert_satellite_loss_pct: Optional[float] = None
    alert_core_loss_pct: Optional[float] = None
    alert_stop_proximity_pct: Optional[float] = None


def _mask_api_key(encrypted_key: str | None) -> str:
    """Return masked version of API key for display, or empty string."""
    if not encrypted_key:
        return ""
    try:
        from services.auth_service import decrypt_value
        decrypted = decrypt_value(encrypted_key)
        if len(decrypted) > 8:
            return decrypted[:7] + "…" + decrypted[-4:]
        return "••••••••"
    except Exception as e:
        logger.debug(f"Could not decrypt/mask API key: {e}")
        return "••••••••"


ALERT_TOGGLE_FIELDS = [
    "alert_stop_missing", "alert_stop_unconfirmed", "alert_stop_proximity",
    "alert_stop_review", "alert_ma_critical", "alert_ma_warning",
    "alert_position_limit", "alert_sector_limit", "alert_loss",
    "alert_market_climate", "alert_vix", "alert_earnings",
    "alert_allocation", "alert_position_type_missing",
]

ALERT_THRESHOLD_FIELDS = [
    ("alert_satellite_loss_pct", -15.0),
    ("alert_core_loss_pct", -25.0),
    ("alert_stop_proximity_pct", 3.0),
]


def _settings_to_dict(s: UserSettings) -> dict:
    d = {
        "base_currency": s.base_currency,
        "broker": s.broker,
        "default_stop_loss_method": s.default_stop_loss_method,
        "stop_loss_review_distance_pct": float(s.stop_loss_review_distance_pct) if s.stop_loss_review_distance_pct else 15.0,
        "stop_loss_review_max_days": s.stop_loss_review_max_days or 14,
        "number_format": s.number_format,
        "date_format": s.date_format,
        "fred_api_key_masked": _mask_api_key(s.fred_api_key),
        "has_fred_api_key": bool(s.fred_api_key),
    }
    for field in ALERT_TOGGLE_FIELDS:
        val = getattr(s, field, None)
        d[field] = val if val is not None else True
    for field, default in ALERT_THRESHOLD_FIELDS:
        val = getattr(s, field, None)
        d[field] = float(val) if val is not None else default
    return d


@router.get("")
async def get_settings(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(UserSettings).where(UserSettings.user_id == user.id))
    s = result.scalars().first()
    if not s:
        s = UserSettings(user_id=user.id)
        db.add(s)
        await db.commit()
        await db.refresh(s)
    return _settings_to_dict(s)


@router.patch("")
async def update_settings(data: SettingsUpdate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    from fastapi import HTTPException

    result = await db.execute(select(UserSettings).where(UserSettings.user_id == user.id))
    s = result.scalars().first()
    if not s:
        s = UserSettings(user_id=user.id)
        db.add(s)

    updates = data.model_dump(exclude_unset=True)

    if "base_currency" in updates and updates["base_currency"] not in VALID_CURRENCIES:
        raise HTTPException(status_code=422, detail=f"Ungültige Währung. Erlaubt: {', '.join(VALID_CURRENCIES)}")
    if "broker" in updates and updates["broker"] not in VALID_BROKERS:
        raise HTTPException(status_code=422, detail=f"Ungültiger Broker")
    if "default_stop_loss_method" in updates and updates["default_stop_loss_method"] not in VALID_SL_METHODS:
        raise HTTPException(status_code=422, detail=f"Ungültige Stop-Loss Methode")
    if "number_format" in updates and updates["number_format"] not in VALID_NUMBER_FORMATS:
        raise HTTPException(status_code=422, detail=f"Ungültiges Zahlenformat")
    if "date_format" in updates and updates["date_format"] not in VALID_DATE_FORMATS:
        raise HTTPException(status_code=422, detail=f"Ungültiges Datumsformat")

    for key, val in updates.items():
        setattr(s, key, val)

    await db.commit()
    await db.refresh(s)
    return _settings_to_dict(s)


# --- FRED API Key ---

class FredApiKeyUpdate(BaseModel):
    api_key: str


@router.put("/fred-api-key")
async def save_fred_api_key(data: FredApiKeyUpdate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    from services.auth_service import encrypt_value

    result = await db.execute(select(UserSettings).where(UserSettings.user_id == user.id))
    s = result.scalars().first()
    if not s:
        s = UserSettings(user_id=user.id)
        db.add(s)

    s.fred_api_key = encrypt_value(data.api_key)
    await db.commit()
    await db.refresh(s)

    # Clear cached indicators so they refresh with the new key
    from services import cache
    cache.delete("macro_indicators")

    return {"ok": True, "fred_api_key_masked": _mask_api_key(s.fred_api_key), "has_fred_api_key": True}


@router.delete("/fred-api-key", status_code=204)
async def delete_fred_api_key(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(UserSettings).where(UserSettings.user_id == user.id))
    s = result.scalars().first()
    if s:
        s.fred_api_key = None
        await db.commit()

    from services import cache
    cache.delete("macro_indicators")


@router.post("/fred-api-key/test")
async def test_fred_api_key(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Test the saved FRED API key by fetching UNRATE."""
    from services.auth_service import decrypt_value
    from services.api_utils import fetch_json

    result = await db.execute(select(UserSettings).where(UserSettings.user_id == user.id))
    s = result.scalars().first()
    if not s or not s.fred_api_key:
        raise HTTPException(status_code=404, detail="Kein FRED API Key konfiguriert")

    try:
        api_key = decrypt_value(s.fred_api_key)
    except Exception as decrypt_err:
        logger.warning(f"FRED API key decrypt failed: {type(decrypt_err).__name__}")
        raise HTTPException(
            status_code=400,
            detail="FRED API Key kann nicht entschlüsselt werden. Bitte Key löschen und neu speichern."
        )

    try:
        data = await fetch_json(
            "https://api.stlouisfed.org/fred/series/observations",
            params={
                "series_id": "UNRATE",
                "api_key": api_key,
                "file_type": "json",
                "sort_order": "desc",
                "limit": 1,
            },
        )
        obs = data.get("observations", [])
        if obs:
            return {"ok": True, "message": f"FRED API Key gültig. Letzter UNRATE-Wert: {obs[0].get('value', '?')}%"}
        return {"ok": True, "message": "FRED API Key gültig (keine Daten zurückgegeben)"}
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"FRED API test failed: {e}")
        raise HTTPException(status_code=400, detail=f"FRED API Fehler: {type(e).__name__}")


# --- Alert Preferences ---

ALERT_CATEGORIES = [
    "stop_missing", "stop_unconfirmed", "stop_proximity", "stop_review",
    "ma_critical", "ma_warning", "position_limit", "sector_limit",
    "loss", "market_climate", "vix", "earnings", "allocation",
    "position_type_missing", "price_alert",
]


class AlertPrefUpdate(BaseModel):
    category: str
    is_enabled: Optional[bool] = None
    notify_in_app: Optional[bool] = None
    notify_email: Optional[bool] = None


@router.get("/alert-preferences")
async def get_alert_preferences(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(AlertPreference).where(AlertPreference.user_id == user.id)
    )
    saved = {p.category: p for p in result.scalars().all()}

    prefs = []
    for cat in ALERT_CATEGORIES:
        if cat in saved:
            p = saved[cat]
            prefs.append({
                "category": cat,
                "is_enabled": p.is_enabled,
                "notify_in_app": p.notify_in_app,
                "notify_email": p.notify_email,
            })
        else:
            prefs.append({
                "category": cat,
                "is_enabled": True,
                "notify_in_app": True,
                "notify_email": False,
            })
    return prefs


@router.put("/alert-preferences")
async def update_alert_preference(data: AlertPrefUpdate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if data.category not in ALERT_CATEGORIES:
        raise HTTPException(status_code=400, detail="Ungültige Kategorie")

    result = await db.execute(
        select(AlertPreference).where(
            AlertPreference.user_id == user.id,
            AlertPreference.category == data.category,
        )
    )
    pref = result.scalars().first()
    if not pref:
        pref = AlertPreference(user_id=user.id, category=data.category)
        db.add(pref)

    if data.is_enabled is not None:
        pref.is_enabled = data.is_enabled
    if data.notify_in_app is not None:
        pref.notify_in_app = data.notify_in_app
    if data.notify_email is not None:
        pref.notify_email = data.notify_email

    await db.commit()
    await db.refresh(pref)
    return {
        "category": pref.category,
        "is_enabled": pref.is_enabled,
        "notify_in_app": pref.notify_in_app,
        "notify_email": pref.notify_email,
    }


# --- SMTP Config ---

SMTP_PRESETS = {
    "gmail": {"host": "smtp.gmail.com", "port": 587, "use_tls": True},
    "outlook": {"host": "smtp.office365.com", "port": 587, "use_tls": True},
    "proton": {"host": "smtp.protonmail.ch", "port": 587, "use_tls": True},
    "yahoo": {"host": "smtp.mail.yahoo.com", "port": 587, "use_tls": True},
    "gmx": {"host": "mail.gmx.net", "port": 587, "use_tls": True},
    "bluewin": {"host": "smtpauths.bluewin.ch", "port": 465, "use_tls": True},
}


class SmtpConfigCreate(BaseModel):
    provider: Optional[str] = None
    host: str
    port: int = 587
    username: str
    password: str
    from_email: Optional[str] = None
    use_tls: bool = True


class SmtpConfigUpdate(BaseModel):
    provider: Optional[str] = None
    host: Optional[str] = None
    port: Optional[int] = None
    username: Optional[str] = None
    password: Optional[str] = None
    from_email: Optional[str] = None
    use_tls: Optional[bool] = None


@router.get("/smtp")
async def get_smtp_config(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    cfg = await db.get(SmtpConfig, user.id)
    if not cfg:
        return {"configured": False, "presets": list(SMTP_PRESETS.keys())}
    return {
        "configured": True,
        "provider": cfg.provider,
        "host": cfg.host,
        "port": cfg.port,
        "username": cfg.username,
        "from_email": cfg.from_email or cfg.username,
        "use_tls": cfg.use_tls,
        "presets": list(SMTP_PRESETS.keys()),
    }


def _is_private_ip(ip_str: str) -> bool:
    """Check if an IP address is in a private/reserved range."""
    import ipaddress
    try:
        addr = ipaddress.ip_address(ip_str)
        return (
            addr.is_private
            or addr.is_loopback
            or addr.is_reserved
            or addr.is_link_local
            or addr.is_multicast
        )
    except ValueError:
        return False  # Expected: non-IP hostnames


def _validate_smtp_host(host: str):
    """Reject SMTP hosts that resolve to private/internal IPs (SSRF prevention)."""
    import socket

    # Reject obviously internal hostnames
    lower_host = host.strip().lower()
    if lower_host in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
        raise HTTPException(400, "SMTP-Host darf nicht auf localhost zeigen")
    if lower_host.endswith(".local") or lower_host.endswith(".internal") or lower_host.endswith(".localdomain"):
        raise HTTPException(400, "SMTP-Host darf nicht auf interne Adressen zeigen")

    # Resolve and check all IPs
    try:
        results = socket.getaddrinfo(host, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except socket.gaierror:
        raise HTTPException(400, "SMTP-Host konnte nicht aufgelöst werden")

    for family, stype, proto, canonname, sockaddr in results:
        ip = sockaddr[0]
        if _is_private_ip(ip):
            raise HTTPException(400, "SMTP-Host darf nicht auf private/interne IP-Adressen zeigen")


@router.put("/smtp")
async def save_smtp_config(data: SmtpConfigCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    from services.auth_service import encrypt_value

    _validate_smtp_host(data.host)

    cfg = await db.get(SmtpConfig, user.id)
    if not cfg:
        cfg = SmtpConfig(user_id=user.id)
        db.add(cfg)

    cfg.provider = data.provider
    cfg.host = data.host
    cfg.port = data.port
    cfg.username = data.username
    cfg.password_encrypted = encrypt_value(data.password)
    cfg.from_email = data.from_email or data.username
    cfg.use_tls = data.use_tls

    await db.commit()
    await db.refresh(cfg)
    return {
        "configured": True,
        "provider": cfg.provider,
        "host": cfg.host,
        "port": cfg.port,
        "username": cfg.username,
        "from_email": cfg.from_email,
        "use_tls": cfg.use_tls,
    }


@router.delete("/smtp", status_code=204)
async def delete_smtp_config(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    cfg = await db.get(SmtpConfig, user.id)
    if cfg:
        await db.delete(cfg)
        await db.commit()


@router.post("/smtp/test")
async def test_smtp(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Send a test email using the user's SMTP config."""
    from services.auth_service import decrypt_value
    import aiosmtplib
    from email.mime.text import MIMEText

    cfg = await db.get(SmtpConfig, user.id)
    if not cfg:
        raise HTTPException(status_code=404, detail="Kein SMTP konfiguriert")

    # SSRF check on stored host
    _validate_smtp_host(cfg.host)

    try:
        password = decrypt_value(cfg.password_encrypted)
        from_addr = cfg.from_email or cfg.username

        msg = MIMEText(
            '<div style="background:#1a1a2e;color:#e0e0e0;padding:32px;font-family:sans-serif;border-radius:12px;">'
            '<h2 style="color:#10b981;margin-top:0;">OpenFolio SMTP Test</h2>'
            '<p>Die SMTP-Konfiguration funktioniert korrekt.</p>'
            '</div>',
            "html",
        )
        msg["Subject"] = "OpenFolio — SMTP Test erfolgreich"
        msg["From"] = from_addr
        msg["To"] = user.email

        if cfg.port == 465:
            await aiosmtplib.send(
                msg,
                hostname=cfg.host,
                port=cfg.port,
                username=cfg.username,
                password=password,
                use_tls=True,
                timeout=10,
            )
        else:
            await aiosmtplib.send(
                msg,
                hostname=cfg.host,
                port=cfg.port,
                username=cfg.username,
                password=password,
                start_tls=cfg.use_tls,
                timeout=10,
            )

        return {"ok": True, "message": f"Test-E-Mail gesendet an {user.email}"}
    except aiosmtplib.SMTPAuthenticationError:
        raise HTTPException(status_code=401, detail="SMTP-Authentifizierung fehlgeschlagen")
    except Exception as e:
        logger.warning(f"SMTP test failed: {e}")
        raise HTTPException(status_code=400, detail="SMTP-Verbindung fehlgeschlagen")


# --- Onboarding ---

ONBOARDING_STEPS = [
    "profile", "cash_account", "first_position", "import",
    "watchlist", "stop_loss", "market", "diversify",
]


class StepCompleteRequest(BaseModel):
    step: str


@router.get("/onboarding/status")
async def get_onboarding_status(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Return onboarding state: tour/checklist flags and auto-detected step completion."""
    from models.watchlist import WatchlistItem

    result = await db.execute(select(UserSettings).where(UserSettings.user_id == user.id))
    s = result.scalars().first()
    if not s:
        s = UserSettings(user_id=user.id)
        db.add(s)
        await db.commit()
        await db.refresh(s)

    # Parse manually tracked steps
    manual_steps = {}
    if s.onboarding_steps_json:
        try:
            manual_steps = json.loads(s.onboarding_steps_json)
        except (json.JSONDecodeError, TypeError):
            pass

    # Auto-detect completion of each step
    steps = {}

    # profile: MFA enabled
    steps["profile"] = user.mfa_enabled is True

    # cash_account: has a cash position
    cash_count = await db.scalar(
        select(func.count(Position.id)).where(Position.user_id == user.id, Position.type == "cash")
    )
    steps["cash_account"] = (cash_count or 0) > 0

    # first_position: has stock or ETF
    pos_count = await db.scalar(
        select(func.count(Position.id)).where(
            Position.user_id == user.id,
            Position.type.in_(["stock", "etf"]),
        )
    )
    steps["first_position"] = (pos_count or 0) > 0

    # import: more than 10 transactions (indicates CSV import)
    txn_count = await db.scalar(
        select(func.count(Transaction.id)).where(Transaction.user_id == user.id)
    )
    steps["import"] = (txn_count or 0) > 10

    # watchlist: has watchlist items
    wl_count = await db.scalar(
        select(func.count(WatchlistItem.id)).where(WatchlistItem.user_id == user.id)
    )
    steps["watchlist"] = (wl_count or 0) > 0

    # stop_loss: at least one position with stop_loss_price set
    sl_count = await db.scalar(
        select(func.count(Position.id)).where(
            Position.user_id == user.id,
            Position.stop_loss_price.isnot(None),
        )
    )
    steps["stop_loss"] = (sl_count or 0) > 0

    # market: manually tracked
    steps["market"] = manual_steps.get("market", False)

    # diversify: has crypto, commodity or pension position
    div_count = await db.scalar(
        select(func.count(Position.id)).where(
            Position.user_id == user.id,
            Position.type.in_(["crypto", "commodity", "pension"]),
        )
    )
    steps["diversify"] = (div_count or 0) > 0

    return {
        "tour_completed": s.onboarding_tour_completed,
        "checklist_hidden": s.onboarding_checklist_hidden,
        "steps": steps,
    }


@router.post("/onboarding/tour-complete")
async def mark_tour_complete(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(UserSettings).where(UserSettings.user_id == user.id))
    s = result.scalars().first()
    if not s:
        s = UserSettings(user_id=user.id)
        db.add(s)
    s.onboarding_tour_completed = True
    await db.commit()
    return {"ok": True}


@router.post("/onboarding/hide-checklist")
async def hide_checklist(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(UserSettings).where(UserSettings.user_id == user.id))
    s = result.scalars().first()
    if not s:
        s = UserSettings(user_id=user.id)
        db.add(s)
    s.onboarding_checklist_hidden = True
    await db.commit()
    return {"ok": True}


@router.post("/onboarding/step-complete")
async def mark_step_complete(data: StepCompleteRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if data.step not in ONBOARDING_STEPS:
        raise HTTPException(status_code=400, detail="Ungültiger Schritt")

    result = await db.execute(select(UserSettings).where(UserSettings.user_id == user.id))
    s = result.scalars().first()
    if not s:
        s = UserSettings(user_id=user.id)
        db.add(s)

    manual_steps = {}
    if s.onboarding_steps_json:
        try:
            manual_steps = json.loads(s.onboarding_steps_json)
        except (json.JSONDecodeError, TypeError):
            pass

    manual_steps[data.step] = True
    s.onboarding_steps_json = json.dumps(manual_steps)
    await db.commit()
    return {"ok": True}


# --- Export ---

_CSV_INJECTION_CHARS = ("=", "+", "-", "@", "\t", "\r")


def _sanitize_csv_cell(value) -> str:
    """Prevent CSV formula injection by prefixing dangerous characters."""
    if isinstance(value, str) and value and value[0] in _CSV_INJECTION_CHARS:
        return "'" + value
    return value


export_router = APIRouter(prefix="/api/export", tags=["export"])


@export_router.get("/portfolio")
async def export_portfolio(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Position).where(Position.user_id == user.id, Position.is_active == True))
    positions = result.scalars().all()

    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")
    writer.writerow(["Ticker", "Name", "Typ", "Sektor", "Währung", "Stück", "Einstandswert CHF", "Aktueller Kurs", "Stop-Loss"])

    for p in positions:
        writer.writerow([
            _sanitize_csv_cell(p.ticker), _sanitize_csv_cell(p.name),
            p.type.value, _sanitize_csv_cell(p.sector or ""), p.currency,
            float(p.shares), float(p.cost_basis_chf),
            float(p.current_price) if p.current_price else "",
            float(p.stop_loss_price) if p.stop_loss_price else "",
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=portfolio.csv"},
    )


@export_router.get("/transactions")
async def export_transactions(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    # Get user's transactions directly
    txn_result = await db.execute(
        select(Transaction).where(Transaction.user_id == user.id).order_by(Transaction.date.desc())
    )
    transactions = txn_result.scalars().all()

    if not transactions:
        output = io.StringIO()
        writer = csv.writer(output, delimiter=";")
        writer.writerow(["Datum", "Typ", "Ticker", "Stück", "Kurs", "Währung", "FX", "Gebühren", "Steuern", "Total CHF"])
        output.seek(0)
        return StreamingResponse(iter([output.getvalue()]), media_type="text/csv",
                                 headers={"Content-Disposition": "attachment; filename=transactions.csv"})

    # Get ticker mapping
    pos_ids = list({t.position_id for t in transactions})
    pos_map_result = await db.execute(select(Position.id, Position.ticker).where(Position.id.in_(pos_ids)))
    ticker_map = {row[0]: row[1] for row in pos_map_result}

    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")
    writer.writerow(["Datum", "Typ", "Ticker", "Stück", "Kurs", "Währung", "FX", "Gebühren", "Steuern", "Total CHF"])

    for t in transactions:
        writer.writerow([
            t.date.isoformat(), t.type.value, _sanitize_csv_cell(ticker_map.get(t.position_id, "")),
            float(t.shares), float(t.price_per_share), t.currency,
            float(t.fx_rate_to_chf), float(t.fees_chf), float(t.taxes_chf), float(t.total_chf),
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=transactions.csv"},
    )
