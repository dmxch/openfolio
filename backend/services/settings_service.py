"""Business logic for user settings, SMTP, onboarding, alert preferences, and data export."""

import csv
import io
import ipaddress
import json
import logging
import socket
from typing import Optional

import aiosmtplib
from email.mime.text import MIMEText
from fastapi import HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from models.alert_preference import AlertPreference
from models.position import Position
from models.smtp_config import SmtpConfig
from models.transaction import Transaction
from models.user import User, UserSettings
from models.watchlist import WatchlistItem

logger = logging.getLogger(__name__)

VALID_CURRENCIES = {"CHF", "EUR", "USD"}
VALID_BROKERS = {"swissquote", "interactive_brokers", "other"}
VALID_SL_METHODS = {"trailing_pct", "higher_low", "ma_based"}
VALID_NUMBER_FORMATS = {"ch", "de", "en"}
VALID_DATE_FORMATS = {"dd.mm.yyyy", "yyyy-mm-dd"}

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

ALERT_CATEGORIES = [
    "stop_missing", "stop_unconfirmed", "stop_proximity", "stop_review",
    "ma_critical", "etf_200dma_buy", "ma_warning", "position_limit", "sector_limit",
    "loss", "market_climate", "vix", "earnings", "allocation",
    "position_type_missing", "price_alert", "breakout",
]

ONBOARDING_STEPS = [
    "profile", "cash_account", "first_position", "import",
    "watchlist", "stop_loss", "market", "diversify",
]

SMTP_PRESETS = {
    "gmail": {"host": "smtp.gmail.com", "port": 587, "use_tls": True},
    "outlook": {"host": "smtp.office365.com", "port": 587, "use_tls": True},
    "proton": {"host": "smtp.protonmail.ch", "port": 587, "use_tls": True},
    "yahoo": {"host": "smtp.mail.yahoo.com", "port": 587, "use_tls": True},
    "gmx": {"host": "mail.gmx.net", "port": 587, "use_tls": True},
    "bluewin": {"host": "smtpauths.bluewin.ch", "port": 465, "use_tls": True},
}


def _mask_api_key(encrypted_key: Optional[str]) -> str:
    """Return masked version of API key for display, or empty string."""
    if not encrypted_key:
        return ""
    try:
        from services.auth_service import decrypt_value
        decrypted = decrypt_value(encrypted_key)
        if len(decrypted) > 8:
            return decrypted[:7] + "..." + decrypted[-4:]
        return "--------"
    except Exception as e:
        logger.debug(f"Could not decrypt/mask API key: {e}")
        return "--------"


def settings_to_dict(s: UserSettings) -> dict:
    """Convert UserSettings model to API response dict."""
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
        "fmp_api_key_masked": _mask_api_key(s.fmp_api_key),
        "has_fmp_api_key": bool(s.fmp_api_key),
        "finnhub_api_key_masked": _mask_api_key(s.finnhub_api_key),
        "has_finnhub_api_key": bool(s.finnhub_api_key),
    }
    for field in ALERT_TOGGLE_FIELDS:
        val = getattr(s, field, None)
        d[field] = val if val is not None else True
    for field, default in ALERT_THRESHOLD_FIELDS:
        val = getattr(s, field, None)
        d[field] = float(val) if val is not None else default
    return d


async def get_or_create_settings(db: AsyncSession, user_id: int) -> UserSettings:
    """Get user settings, creating defaults if they don't exist."""
    result = await db.execute(select(UserSettings).where(UserSettings.user_id == user_id))
    s = result.scalars().first()
    if not s:
        s = UserSettings(user_id=user_id)
        db.add(s)
        await db.commit()
        await db.refresh(s)
    return s


async def get_settings(db: AsyncSession, user_id: int) -> dict:
    """Get user settings as dict."""
    s = await get_or_create_settings(db, user_id)
    return settings_to_dict(s)


def validate_settings_update(updates: dict) -> None:
    """Validate settings update values. Raises HTTPException on invalid input."""
    if "base_currency" in updates and updates["base_currency"] not in VALID_CURRENCIES:
        raise HTTPException(status_code=422, detail=f"Ungueltige Waehrung. Erlaubt: {', '.join(VALID_CURRENCIES)}")
    if "broker" in updates and updates["broker"] not in VALID_BROKERS:
        raise HTTPException(status_code=422, detail="Ungueltiger Broker")
    if "default_stop_loss_method" in updates and updates["default_stop_loss_method"] not in VALID_SL_METHODS:
        raise HTTPException(status_code=422, detail="Ungueltige Stop-Loss Methode")
    if "number_format" in updates and updates["number_format"] not in VALID_NUMBER_FORMATS:
        raise HTTPException(status_code=422, detail="Ungueltiges Zahlenformat")
    if "date_format" in updates and updates["date_format"] not in VALID_DATE_FORMATS:
        raise HTTPException(status_code=422, detail="Ungueltiges Datumsformat")


async def update_settings(db: AsyncSession, user_id: int, updates: dict) -> dict:
    """Update user settings and return updated dict."""
    validate_settings_update(updates)

    result = await db.execute(select(UserSettings).where(UserSettings.user_id == user_id))
    s = result.scalars().first()
    if not s:
        s = UserSettings(user_id=user_id)
        db.add(s)

    for key, val in updates.items():
        setattr(s, key, val)

    await db.commit()
    await db.refresh(s)
    return settings_to_dict(s)


# --- FRED API Key ---

async def save_fred_api_key(db: AsyncSession, user_id: int, api_key: str) -> dict:
    """Encrypt and save FRED API key. Returns response dict."""
    from services.auth_service import encrypt_value
    from services import cache

    result = await db.execute(select(UserSettings).where(UserSettings.user_id == user_id))
    s = result.scalars().first()
    if not s:
        s = UserSettings(user_id=user_id)
        db.add(s)

    s.fred_api_key = encrypt_value(api_key)
    await db.commit()
    await db.refresh(s)

    cache.delete("macro_indicators")

    return {"ok": True, "fred_api_key_masked": _mask_api_key(s.fred_api_key), "has_fred_api_key": True}


async def delete_fred_api_key(db: AsyncSession, user_id: int) -> None:
    """Delete the user's FRED API key."""
    from services import cache

    result = await db.execute(select(UserSettings).where(UserSettings.user_id == user_id))
    s = result.scalars().first()
    if s:
        s.fred_api_key = None
        await db.commit()

    cache.delete("macro_indicators")


async def test_fred_api_key(db: AsyncSession, user_id: int) -> dict:
    """Test the saved FRED API key by fetching UNRATE."""
    from services.auth_service import decrypt_value
    from services.api_utils import fetch_json

    result = await db.execute(select(UserSettings).where(UserSettings.user_id == user_id))
    s = result.scalars().first()
    if not s or not s.fred_api_key:
        raise HTTPException(status_code=404, detail="Kein FRED API Key konfiguriert")

    try:
        api_key = decrypt_value(s.fred_api_key)
    except Exception as decrypt_err:
        logger.warning(f"FRED API key decrypt failed: {type(decrypt_err).__name__}")
        raise HTTPException(
            status_code=400,
            detail="FRED API Key kann nicht entschluesselt werden. Bitte Key loeschen und neu speichern."
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
            return {"ok": True, "message": f"FRED API Key gueltig. Letzter UNRATE-Wert: {obs[0].get('value', '?')}%"}
        return {"ok": True, "message": "FRED API Key gueltig (keine Daten zurueckgegeben)"}
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"FRED API test failed: {e}")
        raise HTTPException(status_code=400, detail=f"FRED API Fehler: {type(e).__name__}")


# --- FMP API Key (Financial Modeling Prep) ---

async def save_fmp_api_key(db: AsyncSession, user_id: int, api_key: str) -> dict:
    """Encrypt and save FMP API key. Returns response dict."""
    from services.auth_service import encrypt_value

    result = await db.execute(select(UserSettings).where(UserSettings.user_id == user_id))
    s = result.scalars().first()
    if not s:
        s = UserSettings(user_id=user_id)
        db.add(s)

    s.fmp_api_key = encrypt_value(api_key)
    await db.commit()
    await db.refresh(s)
    return {"ok": True, "fmp_api_key_masked": _mask_api_key(s.fmp_api_key), "has_fmp_api_key": True}


async def delete_fmp_api_key(db: AsyncSession, user_id: int) -> None:
    """Delete the user's FMP API key."""
    result = await db.execute(select(UserSettings).where(UserSettings.user_id == user_id))
    s = result.scalars().first()
    if s:
        s.fmp_api_key = None
        await db.commit()


async def test_fmp_api_key(db: AsyncSession, user_id: int) -> dict:
    """Test the saved FMP API key with a lightweight quote request."""
    from services.auth_service import decrypt_value
    from services.api_utils import fetch_json

    result = await db.execute(select(UserSettings).where(UserSettings.user_id == user_id))
    s = result.scalars().first()
    if not s or not s.fmp_api_key:
        raise HTTPException(status_code=404, detail="Kein FMP API Key konfiguriert")

    try:
        api_key = decrypt_value(s.fmp_api_key)
    except Exception:
        raise HTTPException(
            status_code=400,
            detail="FMP API Key kann nicht entschluesselt werden. Bitte Key loeschen und neu speichern."
        )

    try:
        # Neuer /stable/-Endpoint (der Legacy-Endpoint /api/v3/quote ist
        # seit August 2025 deprecated und nur noch fuer Alt-Subscriptions
        # zugaenglich).
        data = await fetch_json(
            "https://financialmodelingprep.com/stable/quote",
            params={"symbol": "AAPL", "apikey": api_key},
            timeout=10,
        )
        if isinstance(data, list) and data:
            price = data[0].get("price")
            return {"ok": True, "message": f"FMP API Key gueltig. AAPL: ${price}"}
        if isinstance(data, dict) and data.get("Error Message"):
            raise HTTPException(status_code=400, detail=f"FMP Fehler: {data['Error Message']}")
        return {"ok": True, "message": "FMP API Key gueltig"}
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"FMP API test failed: {e}")
        raise HTTPException(status_code=400, detail=f"FMP API Fehler: {type(e).__name__}")


# --- Finnhub API Key ---

async def save_finnhub_api_key(db: AsyncSession, user_id: int, api_key: str) -> dict:
    """Encrypt and save Finnhub API key. Returns response dict."""
    from services.auth_service import encrypt_value

    result = await db.execute(select(UserSettings).where(UserSettings.user_id == user_id))
    s = result.scalars().first()
    if not s:
        s = UserSettings(user_id=user_id)
        db.add(s)

    s.finnhub_api_key = encrypt_value(api_key)
    await db.commit()
    await db.refresh(s)
    return {"ok": True, "finnhub_api_key_masked": _mask_api_key(s.finnhub_api_key), "has_finnhub_api_key": True}


async def delete_finnhub_api_key(db: AsyncSession, user_id: int) -> None:
    """Delete the user's Finnhub API key."""
    result = await db.execute(select(UserSettings).where(UserSettings.user_id == user_id))
    s = result.scalars().first()
    if s:
        s.finnhub_api_key = None
        await db.commit()


async def test_finnhub_api_key(db: AsyncSession, user_id: int) -> dict:
    """Test the saved Finnhub API key with a lightweight quote request."""
    from services.auth_service import decrypt_value
    from services.api_utils import fetch_json

    result = await db.execute(select(UserSettings).where(UserSettings.user_id == user_id))
    s = result.scalars().first()
    if not s or not s.finnhub_api_key:
        raise HTTPException(status_code=404, detail="Kein Finnhub API Key konfiguriert")

    try:
        api_key = decrypt_value(s.finnhub_api_key)
    except Exception:
        raise HTTPException(
            status_code=400,
            detail="Finnhub API Key kann nicht entschluesselt werden. Bitte Key loeschen und neu speichern."
        )

    try:
        data = await fetch_json(
            "https://finnhub.io/api/v1/quote",
            params={"symbol": "AAPL", "token": api_key},
            timeout=10,
        )
        if isinstance(data, dict) and "c" in data:
            return {"ok": True, "message": f"Finnhub API Key gueltig. AAPL: ${data['c']}"}
        return {"ok": True, "message": "Finnhub API Key gueltig"}
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"Finnhub API test failed: {e}")
        raise HTTPException(status_code=400, detail=f"Finnhub API Fehler: {type(e).__name__}")


# --- Per-User API Key Lookup Helper ---

async def get_user_api_key(db: AsyncSession, user_id, field: str) -> str | None:
    """Liest und entschluesselt einen API-Key aus user_settings.

    `field` ist eine der UserSettings-Spalten: `fred_api_key`, `fmp_api_key`,
    `finnhub_api_key`. Returnt None wenn nicht konfiguriert oder nicht
    entschluesselbar.
    """
    if field not in ("fred_api_key", "fmp_api_key", "finnhub_api_key"):
        raise ValueError(f"Unbekanntes API-Key-Feld: {field}")

    from services.auth_service import decrypt_value

    result = await db.execute(
        select(getattr(UserSettings, field)).where(UserSettings.user_id == user_id)
    )
    row = result.first()
    if not row or not row[0]:
        return None
    try:
        return decrypt_value(row[0])
    except Exception as e:
        logger.warning(f"{field} decrypt failed for user {user_id}: {e}")
        return None


# --- Alert Preferences ---

async def get_alert_preferences(db: AsyncSession, user_id: int) -> list[dict]:
    """Get all alert preferences with defaults for unconfigured categories."""
    result = await db.execute(
        select(AlertPreference).where(AlertPreference.user_id == user_id)
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


async def update_alert_preference(
    db: AsyncSession,
    user_id: int,
    category: str,
    is_enabled: Optional[bool] = None,
    notify_in_app: Optional[bool] = None,
    notify_email: Optional[bool] = None,
) -> dict:
    """Update a single alert preference category."""
    if category not in ALERT_CATEGORIES:
        raise HTTPException(status_code=400, detail="Ungueltige Kategorie")

    result = await db.execute(
        select(AlertPreference).where(
            AlertPreference.user_id == user_id,
            AlertPreference.category == category,
        )
    )
    pref = result.scalars().first()
    if not pref:
        pref = AlertPreference(user_id=user_id, category=category)
        db.add(pref)

    if is_enabled is not None:
        pref.is_enabled = is_enabled
    if notify_in_app is not None:
        pref.notify_in_app = notify_in_app
    if notify_email is not None:
        pref.notify_email = notify_email

    await db.commit()
    await db.refresh(pref)
    return {
        "category": pref.category,
        "is_enabled": pref.is_enabled,
        "notify_in_app": pref.notify_in_app,
        "notify_email": pref.notify_email,
    }


# --- SMTP Config ---

def _is_private_ip(ip_str: str) -> bool:
    """Check if an IP address is in a private/reserved range."""
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


def validate_smtp_host(host: str) -> None:
    """Reject SMTP hosts that resolve to private/internal IPs (SSRF prevention)."""
    lower_host = host.strip().lower()
    if lower_host in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
        raise HTTPException(400, "SMTP-Host darf nicht auf localhost zeigen")
    if lower_host.endswith(".local") or lower_host.endswith(".internal") or lower_host.endswith(".localdomain"):
        raise HTTPException(400, "SMTP-Host darf nicht auf interne Adressen zeigen")

    try:
        results = socket.getaddrinfo(host, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except socket.gaierror:
        raise HTTPException(400, "SMTP-Host konnte nicht aufgeloest werden")

    for family, stype, proto, canonname, sockaddr in results:
        ip = sockaddr[0]
        if _is_private_ip(ip):
            raise HTTPException(400, "SMTP-Host darf nicht auf private/interne IP-Adressen zeigen")


async def get_smtp_config(db: AsyncSession, user_id: int) -> dict:
    """Get SMTP configuration for user."""
    cfg = await db.get(SmtpConfig, user_id)
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


async def save_smtp_config(
    db: AsyncSession,
    user_id: int,
    provider: Optional[str],
    host: str,
    port: int,
    username: str,
    password: str,
    from_email: Optional[str],
    use_tls: bool,
) -> dict:
    """Validate and save SMTP configuration."""
    from services.auth_service import encrypt_value

    validate_smtp_host(host)

    cfg = await db.get(SmtpConfig, user_id)
    if not cfg:
        cfg = SmtpConfig(user_id=user_id)
        db.add(cfg)

    cfg.provider = provider
    cfg.host = host
    cfg.port = port
    cfg.username = username
    cfg.password_encrypted = encrypt_value(password)
    cfg.from_email = from_email or username
    cfg.use_tls = use_tls

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


async def delete_smtp_config(db: AsyncSession, user_id: int) -> None:
    """Delete SMTP configuration for user."""
    cfg = await db.get(SmtpConfig, user_id)
    if cfg:
        await db.delete(cfg)
        await db.commit()


async def test_smtp_config(db: AsyncSession, user: User) -> dict:
    """Send a test email using the user's SMTP config."""
    from services.auth_service import decrypt_value

    cfg = await db.get(SmtpConfig, user.id)
    if not cfg:
        raise HTTPException(status_code=404, detail="Kein SMTP konfiguriert")

    validate_smtp_host(cfg.host)

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
        msg["Subject"] = "OpenFolio -- SMTP Test erfolgreich"
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
        raise HTTPException(status_code=400, detail=f"SMTP-Verbindung fehlgeschlagen: {e}")


# --- Onboarding ---

async def get_onboarding_status(db: AsyncSession, user: User) -> dict:
    """Return onboarding state: tour/checklist flags and auto-detected step completion."""
    s = await get_or_create_settings(db, user.id)

    manual_steps = {}
    if s.onboarding_steps_json:
        try:
            manual_steps = json.loads(s.onboarding_steps_json)
        except (json.JSONDecodeError, TypeError):
            logger.debug("Corrupt onboarding_steps_json for user %s", user.id, exc_info=True)

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


async def mark_tour_complete(db: AsyncSession, user_id: int) -> dict:
    """Mark onboarding tour as completed."""
    s = await get_or_create_settings(db, user_id)
    s.onboarding_tour_completed = True
    await db.commit()
    return {"ok": True}


async def hide_checklist(db: AsyncSession, user_id: int) -> dict:
    """Hide onboarding checklist."""
    s = await get_or_create_settings(db, user_id)
    s.onboarding_checklist_hidden = True
    await db.commit()
    return {"ok": True}


async def mark_step_complete(db: AsyncSession, user_id: int, step: str) -> dict:
    """Mark a single onboarding step as complete."""
    if step not in ONBOARDING_STEPS:
        raise HTTPException(status_code=400, detail="Ungueltiger Schritt")

    s = await get_or_create_settings(db, user_id)

    manual_steps = {}
    if s.onboarding_steps_json:
        try:
            manual_steps = json.loads(s.onboarding_steps_json)
        except (json.JSONDecodeError, TypeError):
            logger.debug("Corrupt onboarding_steps_json for user %s", user_id, exc_info=True)

    manual_steps[step] = True
    s.onboarding_steps_json = json.dumps(manual_steps)
    await db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Data Export
# ---------------------------------------------------------------------------

_CSV_INJECTION_CHARS = ("=", "+", "-", "@", "\t", "\r")


def _sanitize_csv_cell(value) -> str:
    """Prevent CSV formula injection by prefixing dangerous characters."""
    if isinstance(value, str) and value and value[0] in _CSV_INJECTION_CHARS:
        return "'" + value
    return value


async def export_portfolio_csv(db: AsyncSession, user_id) -> str:
    """Generate CSV string of all active positions for a user."""
    result = await db.execute(
        select(Position).where(Position.user_id == user_id, Position.is_active == True)
    )
    positions = result.scalars().all()

    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")
    writer.writerow(["Ticker", "Name", "Typ", "Sektor", "Waehrung", "Stueck", "Einstandswert CHF", "Aktueller Kurs", "Stop-Loss"])

    for p in positions:
        writer.writerow([
            _sanitize_csv_cell(p.ticker), _sanitize_csv_cell(p.name),
            p.type.value, _sanitize_csv_cell(p.sector or ""), p.currency,
            float(p.shares), float(p.cost_basis_chf),
            float(p.current_price) if p.current_price else "",
            float(p.stop_loss_price) if p.stop_loss_price else "",
        ])

    output.seek(0)
    return output.getvalue()


async def export_transactions_csv(db: AsyncSession, user_id) -> str:
    """Generate CSV string of all transactions for a user."""
    txn_result = await db.execute(
        select(Transaction).where(Transaction.user_id == user_id).order_by(Transaction.date.desc())
    )
    transactions = txn_result.scalars().all()

    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")
    writer.writerow(["Datum", "Typ", "Ticker", "Stueck", "Kurs", "Waehrung", "FX", "Gebuehren", "Steuern", "Total CHF"])

    if transactions:
        pos_ids = list({t.position_id for t in transactions})
        pos_map_result = await db.execute(select(Position.id, Position.ticker).where(Position.id.in_(pos_ids)))
        ticker_map = {row[0]: row[1] for row in pos_map_result}

        for t in transactions:
            writer.writerow([
                t.date.isoformat(), t.type.value, _sanitize_csv_cell(ticker_map.get(t.position_id, "")),
                float(t.shares), float(t.price_per_share), t.currency,
                float(t.fx_rate_to_chf), float(t.fees_chf), float(t.taxes_chf), float(t.total_chf),
            ])

    output.seek(0)
    return output.getvalue()
