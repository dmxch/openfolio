import logging
import sys

from pydantic import field_validator
from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://openfolio:CHANGE_ME@localhost:5432/openfolio"
    cors_origins: str = "http://localhost:5173"
    coingecko_base_url: str = "https://api.coingecko.com/api/v3"
    jwt_secret: str = ""
    encryption_key: str = ""  # Base64-encoded 32-byte key for AES-256
    admin_email: str = ""
    admin_password: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    alert_email_to: str = ""
    # Comma-separated hostnames (case-insensitive, exact) that may resolve to private
    # addresses for ntfy (SSRF allowlist), e.g. "ntfy" for the self-hosted container.
    ntfy_allowed_private_hosts: str = ""
    # Same format for the SMTP host of a user's own SMTP config. Without an entry a
    # user-supplied SMTP server must resolve to public addresses only.
    smtp_allowed_private_hosts: str = ""
    # Der Schluessel aus einem leeren LEGACY_ENCRYPTION_KEY (32 Nullen) ist oeffentlich
    # bekannt. Er bleibt zum Entschluesseln im Ring, bis keine Altwerte mehr damit
    # verschluesselt sind (pruefen und umschluesseln:
    # scripts/vr11_reencrypt_legacy_fields.py). Danach auf false setzen (K152).
    legacy_null_key_enabled: bool = True
    frontend_url: str = "http://localhost:5173"
    redis_url: str = "redis://localhost:6379/0"
    # Hinweis: FRED, FMP und Finnhub API-Keys werden NICHT mehr aus der
    # Umgebung gelesen — jeder User traegt seinen eigenen Key in den
    # Settings ein (verschluesselt in user_settings gespeichert).
    #
    # Ausnahme: Der EPS-Scanner-Worker-Job nutzt einen SYSTEM-Level-Finnhub-Key
    # (kein User-Key), damit der Job auf Multi-User-Instanzen deterministisch
    # laeuft (OF-5). Free-Tier reicht (60 Calls/min). Fehlt der Key, faellt der
    # Job komplett auf yfinance zurueck.
    #
    # Dasselbe gilt fuer FMP und FRED: Globale Jobs (nicht an einen Nutzer
    # gebunden) nehmen den System-Key, wenn er gesetzt ist. Ohne System-Key gilt
    # der Key des aeltesten aktiven Admin-Kontos, nie der eines anderen Nutzers.
    finnhub_system_api_key: str = ""
    fmp_system_api_key: str = ""
    fred_system_api_key: str = ""

    # Anzahl vertrauter Reverse-Proxys vor dem Backend, die X-Forwarded-For
    # setzen oder ergaenzen. get_client_ip nimmt den Eintrag an dieser Position
    # von rechts. 1 passt, wenn der letzte Proxy den Header UEBERSCHREIBT (der
    # Container-nginx tut das) oder genau ein Proxy anhaengt. Mindestwert 1.
    trusted_proxy_hops: int = 1

    # statement_timeout (ms) der async-Engine des API-Prozesses. 0 = aus (Default).
    # Wird nur an das Backend durchgereicht, nicht an den Worker: dessen Jobs
    # laufen bewusst lange.
    db_statement_timeout_ms: int = 0

    # Risk-free rate (annualisiert, %) fuer Sharpe/Sortino/Calmar/Information-Ratio
    # auf der Performance-Seite. Default 0.0 = Excess-Return ueber Cash; kann auf den
    # SARON/CHF-Geldmarktsatz gesetzt werden. Rein additive Kennzahl — beruehrt keine
    # geschuetzte Performance-Berechnung (HEILIGE Regeln 1 & 11). Muss in BEIDE
    # docker-compose environment-Bloecke (backend + worker), sonst greift der Default.
    risk_free_rate_pct: float = 0.0

    # Links des Betreibers auf seine AGB, Datenschutzerklaerung und sein Impressum.
    # Leer = Selbstbetrieb: die App zeigt neutrale Texte. Nur https:// wird akzeptiert,
    # damit aus einer Fehlkonfiguration kein javascript:- oder http:-Link im Frontend wird.
    legal_terms_url: str = ""
    legal_privacy_url: str = ""
    legal_imprint_url: str = ""

    @field_validator("legal_terms_url", "legal_privacy_url", "legal_imprint_url", mode="after")
    @classmethod
    def _only_https_urls(cls, value: str, info) -> str:
        value = (value or "").strip()
        if value and not value.lower().startswith("https://"):
            logger.warning("Ignoring %s: only https:// URLs are allowed", info.field_name.upper())
            return ""
        return value

    model_config = {"env_file": ".env"}


settings = Settings()

# Validate required auth settings at import time
if not settings.jwt_secret or len(settings.jwt_secret) < 32:
    print("FATAL: JWT_SECRET must be set and at least 32 characters. Exiting.")
    sys.exit(1)

if settings.jwt_secret.startswith("MUST_BE_SET"):
    print("FATAL: JWT_SECRET uses a placeholder value. Please configure a unique secret via .env or run init.sh. Exiting.")
    sys.exit(1)

if not settings.encryption_key or len(settings.encryption_key) < 32:
    print("FATAL: ENCRYPTION_KEY must be set (Base64-encoded 32 bytes). Exiting.")
    sys.exit(1)

if settings.encryption_key.startswith("MUST_BE_SET"):
    print("FATAL: ENCRYPTION_KEY uses a placeholder value. Please configure a unique key via .env or run init.sh. Exiting.")
    sys.exit(1)

if "CHANGE_ME" in settings.database_url or "MUST_SET" in settings.database_url:
    print("FATAL: DATABASE_URL contains a default/placeholder password. Set POSTGRES_PASSWORD in .env or run init.sh. Exiting.")
    sys.exit(1)
