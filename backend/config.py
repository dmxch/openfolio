import sys

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://openfolio:CHANGE_ME@localhost:5432/openfolio"
    cors_origins: str = "http://localhost:5173"
    coingecko_base_url: str = "https://api.coingecko.com/api/v3"
    fmp_api_key: str = ""
    jwt_secret: str = ""
    encryption_key: str = ""  # Base64-encoded 32-byte key for AES-256
    admin_email: str = ""
    admin_password: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    alert_email_to: str = ""
    fred_api_key: str = ""
    finnhub_api_key: str = ""
    frontend_url: str = "http://localhost:5173"
    redis_url: str = "redis://localhost:6379/0"

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
