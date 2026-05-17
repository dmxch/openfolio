"""ntfy push notification service.

Fire-and-forget: callers use send_push_for_user() / send_push_aggregated() which
internally spawn asyncio.create_task(_send_push_inner(...)). Each spawned task is
held in the module-level _pending set until completion — this prevents the Python
GC from collecting the task before it finishes (asyncio GC footgun).
The inner function handles all exceptions internally (logger.warning on failure).
This ensures ntfy outages never delay the 60s worker cycle.
Uses httpx (HEILIGE Regel #8), JSON publish mode (topic in body, not URL).
Redis calls use services/cache.py which is synchronous (no await needed) — see
Section 6.6 of FEATURE_PUSH_NOTIFICATIONS.md.
"""
import asyncio
import logging
from datetime import date
from typing import Any, Literal

import httpx

from services.auth_service import decrypt_value

logger = logging.getLogger(__name__)

NtfyPriority = Literal[1, 2, 3, 4, 5]  # 1=min, 3=default, 5=urgent

# Aggregation threshold: send a single digest push instead of N individual pushes
# when N alerts of the same category trigger in the same worker run.
AGGREGATION_THRESHOLD = 3

SEVERITY_TO_PRIORITY: dict[str, NtfyPriority] = {
    "critical": 5,
    "high": 4,
    "medium": 3,
    "info": 2,
}

# Severity -> (ntfy_tag, emoji). Tags drive the icon shown by the ntfy app.
_SEVERITY_TAGS: dict[str, tuple[str, str]] = {
    "critical": ("rotating_light", "🚨"),
    "high": ("chart_with_upwards_trend", "📈"),
    "medium": ("bar_chart", "📊"),
    "info": ("moneybag", "💰"),
}

# German plural labels for aggregated push titles.
# Keys must match the category strings used by settings_service.ALERT_CATEGORIES
# and queried by the email services (price_alert_service, breakout_alert_service, ...).
_CATEGORY_LABELS_DE: dict[str, str] = {
    "price_alert": "Preis-Alarme",
    "breakout": "Breakouts",
    "earnings": "Earnings-Termine",
    "etf_200dma_buy": "ETF-200DMA-Signale",
    "pending_dividend": "ausstehende Dividenden",
    "rule_alert": "Portfolio-Regeln",
    "stop_review": "Stop-Reviews",
    "stop_missing": "fehlende Stops",
    "ma_critical": "MA-Krisen-Signale",
    "ma_warning": "MA-Warnungen",
    "vix": "VIX-Signale",
    "market_climate": "Markt-Klima-Wechsel",
    "loss": "Verlust-Alarme",
    "position_limit": "Positions-Limits",
    "sector_limit": "Sektor-Limits",
    "allocation": "Allokations-Hinweise",
    "stop_proximity": "Stop-Nähe-Warnungen",
    "stop_unconfirmed": "unbestätigte Stops",
}

# Strong-reference set: prevents the Python GC from collecting pending asyncio
# Tasks before they finish. Each task removes itself via add_done_callback.
# See https://docs.python.org/3/library/asyncio-task.html#asyncio.create_task
_pending: set[asyncio.Task] = set()


async def _send_push_inner(
    server_url: str,
    topic: str,
    title: str,
    message: str,
    access_token_encrypted: str | None = None,
    priority: NtfyPriority = 3,
    tags: list[str] | None = None,
) -> None:
    """Inner coroutine — never raises. Used as detached asyncio.Task."""
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if access_token_encrypted:
        try:
            token = decrypt_value(access_token_encrypted)
            headers["Authorization"] = f"Bearer {token}"
        except Exception as e:
            logger.warning(f"ntfy token decrypt failed: {type(e).__name__}")
            return

    payload: dict[str, Any] = {
        "topic": topic,
        "title": title,
        "message": message,
        "priority": priority,
    }
    if tags:
        payload["tags"] = tags

    url = server_url.rstrip("/") + "/"
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
        logger.info(f"ntfy push sent (server={server_url}, priority={priority})")
    except httpx.HTTPStatusError as e:
        logger.warning(
            f"ntfy push failed: HTTP {e.response.status_code} for {server_url}"
        )
    except Exception as e:
        logger.warning(f"ntfy push failed: {type(e).__name__}: {e}")


def _spawn_task(**kwargs) -> None:
    """Create a fire-and-forget task with a strong reference to prevent GC collection."""
    task = asyncio.create_task(_send_push_inner(**kwargs))
    _pending.add(task)
    task.add_done_callback(_pending.discard)


def send_push_for_user(
    ntfy_cfg,  # NtfyConfig model instance
    category: str,
    title: str,
    message: str,
    severity: str = "medium",
    redis_client=None,  # services/cache module passed by caller for dedup
) -> None:
    """Schedule a single push as detached fire-and-forget task.

    Applies per-alert dedup: ntfy_dedup:{user_id}:{category}:{title}
    with TTL 24h via Redis. Pass redis_client=None to skip dedup (e.g. test push).
    Caller must NOT await this function.

    redis_client is services/cache — its get()/set() are synchronous (no await).
    """
    if not ntfy_cfg or not ntfy_cfg.is_enabled:
        return

    if redis_client is not None:
        dedup_key = f"ntfy_dedup:{ntfy_cfg.user_id}:{category}:{title}"
        if redis_client.get(dedup_key):
            return
        # ttl param name on services/cache.set() is `ttl` (not `ex`)
        redis_client.set(dedup_key, "1", ttl=86400)  # 24h

    priority = SEVERITY_TO_PRIORITY.get(severity, 3)
    tag_info = _SEVERITY_TAGS.get(severity)
    tags = [tag_info[0]] if tag_info else None
    _spawn_task(
        server_url=ntfy_cfg.server_url,
        topic=ntfy_cfg.topic,
        title=title,
        message=message,
        access_token_encrypted=ntfy_cfg.access_token_encrypted,
        priority=priority,
        tags=tags,
    )


def send_push_aggregated(
    ntfy_cfg,  # NtfyConfig model instance
    category: str,
    alerts: list[dict],  # list of {"title": str, "message": str, "severity": str}
    redis_client=None,
    force_aggregate: bool = False,
) -> None:
    """Send push(es) for a batch of alerts of the same category in one worker run.

    If len(alerts) >= AGGREGATION_THRESHOLD or force_aggregate=True: one aggregated
    push with per-day dedup. Otherwise: N individual pushes with per-alert dedup.
    force_aggregate=True is for callers whose email pendant is also a digest
    (e.g. pending_dividend, weekly), where individual pushes would diverge
    from the established UX.
    Caller must NOT await this function.

    redis_client is services/cache — its get()/set() are synchronous (no await).
    """
    if not ntfy_cfg or not ntfy_cfg.is_enabled or not alerts:
        return

    if force_aggregate or len(alerts) >= AGGREGATION_THRESHOLD:
        # One aggregated push per category per calendar day
        if redis_client is not None:
            agg_key = (
                f"ntfy_dedup_agg:{ntfy_cfg.user_id}:{category}:"
                f"{date.today().isoformat()}"
            )
            if redis_client.get(agg_key):
                return
            redis_client.set(agg_key, "1", ttl=86400)

        severity = alerts[0].get("severity", "medium")
        priority = SEVERITY_TO_PRIORITY.get(severity, 3)
        tag_info = _SEVERITY_TAGS.get(severity)
        tags = [tag_info[0]] if tag_info else None

        first_titles = [a["title"] for a in alerts[:3]]
        extra = len(alerts) - 3
        body = ", ".join(first_titles)
        if extra > 0:
            body += f" +{extra} weitere"

        label = _CATEGORY_LABELS_DE.get(category, category)
        _spawn_task(
            server_url=ntfy_cfg.server_url,
            topic=ntfy_cfg.topic,
            title=f"{len(alerts)} {label} ausgelöst",
            message=body,
            access_token_encrypted=ntfy_cfg.access_token_encrypted,
            priority=priority,
            tags=tags,
        )
    else:
        for alert in alerts:
            send_push_for_user(
                ntfy_cfg=ntfy_cfg,
                category=category,
                title=alert["title"],
                message=alert["message"],
                severity=alert.get("severity", "medium"),
                redis_client=redis_client,
            )


async def send_push_test(ntfy_cfg) -> tuple[bool, str]:
    """Synchronous test push — awaited by the API endpoint, NOT fire-and-forget.

    Returns (success: bool, error_message: str).
    Uses severity 'high' so the user sees the actual sound/vibration behaviour.
    Deliberately ignores ntfy_cfg.is_enabled — test push works even when paused
    so users can verify the setup while pushes are temporarily disabled.
    """
    if not ntfy_cfg:
        return False, "Keine ntfy-Konfiguration gefunden"

    headers: dict[str, str] = {"Content-Type": "application/json"}
    if ntfy_cfg.access_token_encrypted:
        try:
            token = decrypt_value(ntfy_cfg.access_token_encrypted)
            headers["Authorization"] = f"Bearer {token}"
        except Exception as e:
            return False, f"Token kann nicht entschlüsselt werden: {type(e).__name__}"

    payload = {
        "topic": ntfy_cfg.topic,
        "title": "OpenFolio Test",
        "message": "Test-Push von OpenFolio — wenn du das siehst, funktioniert's.",
        "priority": 4,  # high
        "tags": ["chart_with_upwards_trend"],
    }
    url = ntfy_cfg.server_url.rstrip("/") + "/"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
        return True, ""
    except httpx.HTTPStatusError as e:
        reason = getattr(e.response, "reason_phrase", "") or ""
        return False, f"{e.response.status_code} {reason}".strip()
    except httpx.RequestError as e:
        return False, f"Verbindung fehlgeschlagen: {type(e).__name__}"
    except Exception as e:
        return False, str(e)
