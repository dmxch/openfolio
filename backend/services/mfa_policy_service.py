"""MFA enforcement policy — globaler, admin-steuerbarer Zwang zur MFA-Einrichtung.

Die Policy liegt als einzelne Zeile in ``app_settings`` (key ``mfa_policy``) und
ist eine der vier Stufen:

- ``off``          — niemand wird gezwungen (MFA bleibt rein optional)
- ``admins_only``  — nur Admins muessen MFA einrichten
- ``selected``     — nur User mit ``User.mfa_required = True`` (im Admin-Panel gesetzt)
- ``all``          — alle User muessen MFA einrichten

Die Erzwingung selbst passiert in :func:`auth.get_current_user`: ein betroffener
User ohne aktives MFA wird von allen geschuetzten Endpoints geblockt (403), bis er
MFA aktiviert — ausser den wenigen Endpoints, die er zum Einrichten/Abmelden
braucht. Die externe API (X-API-Key / :func:`auth.get_api_user`) ist bewusst
ausgenommen.
"""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.app_setting import AppSetting
from models.user import User

logger = logging.getLogger(__name__)

MFA_POLICY_KEY = "mfa_policy"
MFA_POLICIES = ("off", "admins_only", "selected", "all")

# Fallback, wenn die Zeile fehlt (z.B. Test-DB via create_all, oder eine Instanz
# vor Migration 094). Bewusst ``off`` — fehlende Konfiguration erzwingt NICHTS
# (fail-open fuer die Erzwingung, damit ein fehlendes Setting niemanden aussperrt).
# Der echte Deployment-Default wird von Migration 094 als ``all`` geseedet.
DEFAULT_WHEN_MISSING = "off"


async def get_mfa_policy(db: AsyncSession) -> str:
    """Aktuelle globale MFA-Policy (validiert; Fallback ``off`` wenn ungesetzt)."""
    result = await db.execute(select(AppSetting).where(AppSetting.key == MFA_POLICY_KEY))
    setting = result.scalars().first()
    if setting is None:
        # Row fehlt = "nicht konfiguriert" (Tests via create_all, Instanz vor 094).
        # Legitim -> still auf off; KEIN Log (waere sonst Dauer-Spam pro Request).
        return DEFAULT_WHEN_MISSING
    if setting.value not in MFA_POLICIES:
        # Row existiert, aber der Wert ist korrupt -> die Erzwingung (ein
        # Security-Control) wuerde lautlos abschalten. Das sichtbar machen.
        logger.warning(
            "mfa_policy has invalid value %r — falling back to %r (enforcement effectively OFF)",
            setting.value,
            DEFAULT_WHEN_MISSING,
        )
        return DEFAULT_WHEN_MISSING
    return setting.value


def mfa_is_required_for(user: User, policy: str) -> bool:
    """Ob MFA fuer diesen User unter der gegebenen Policy verpflichtend ist."""
    if policy == "all":
        return True
    if policy == "admins_only":
        return bool(user.is_admin)
    if policy == "selected":
        return bool(user.mfa_required)
    return False  # "off" oder unbekannt


async def user_needs_mfa_setup(db: AsyncSession, user: User) -> bool:
    """True, wenn der User MFA haben MUSS, es aber noch nicht aktiviert hat."""
    if user.mfa_enabled:
        return False
    policy = await get_mfa_policy(db)
    return mfa_is_required_for(user, policy)
