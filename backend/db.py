from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import sessionmaker

from config import settings


def _async_connect_args(database_url: str, statement_timeout_ms: int) -> dict:
    """connect_args for the async engine: opt-in statement_timeout (asyncpg only).

    Bewusst nur statement_timeout: ein Timeout für offene Transaktionen
    (idle_in_transaction_session_timeout) träfe lange Import- und Regen-Läufe.
    """
    if statement_timeout_ms > 0 and database_url.startswith("postgresql+asyncpg"):
        return {"server_settings": {"statement_timeout": str(statement_timeout_ms)}}
    return {}


# hide_parameters: SQLAlchemy hängt sonst die gebundenen Werte an jede
# DB-Fehlermeldung. Über Logs und Fehlertexte gelangten so Nutzerdaten nach aussen.
engine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_size=20,
    max_overflow=20,
    pool_timeout=30,
    pool_recycle=3600,
    pool_pre_ping=True,
    hide_parameters=True,
    connect_args=_async_connect_args(settings.database_url, settings.db_statement_timeout_ms),
)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

# Sync engine for use in ThreadPoolExecutor context (yfinance callbacks, etc.)
_sync_url = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
sync_engine = create_engine(
    _sync_url,
    echo=False,
    pool_size=5,
    max_overflow=10,
    pool_timeout=30,
    pool_recycle=3600,
    pool_pre_ping=True,
    hide_parameters=True,
)
SyncSessionLocal = sessionmaker(bind=sync_engine)


async def get_db():
    async with async_session() as session:
        yield session
