"""Shared test fixtures — in-memory SQLite, no production DB."""

import os
import sys

# Set test env vars BEFORE any app imports
os.environ["DATABASE_URL"] = "sqlite+aiosqlite://"
os.environ["JWT_SECRET"] = "test-jwt-secret-at-least-32-characters-long-for-tests"
os.environ["ENCRYPTION_KEY"] = "dGVzdC1lbmNyeXB0aW9uLWtleS0zMmJ5dGVzIQ=="  # base64 of 32 bytes
os.environ["CORS_ORIGINS"] = "http://localhost:5173"

import types
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import sessionmaker

# Create test engines
test_engine = create_async_engine("sqlite+aiosqlite://", echo=False)
test_sync_engine = create_engine("sqlite://", echo=False)
TestSession = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
TestSyncSession = sessionmaker(bind=test_sync_engine)


async def _get_db():
    async with TestSession() as session:
        yield session


# Pre-register a fake db module BEFORE any app code imports it
fake_db = types.ModuleType("db")
fake_db.engine = test_engine
fake_db.sync_engine = test_sync_engine
fake_db.async_session = TestSession
fake_db.SyncSessionLocal = TestSyncSession
fake_db.get_db = _get_db
sys.modules["db"] = fake_db

from models import Base


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    """Create all tables before each test, drop after."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def db():
    """Provide a test DB session."""
    async with TestSession() as session:
        yield session


@pytest_asyncio.fixture
async def client(db, monkeypatch):
    """Provide an async test client with DB override."""
    from main import app
    from api.auth import limiter

    async def override_get_db():
        yield db

    app.dependency_overrides[_get_db] = override_get_db

    # Disable rate limiting for tests
    limiter.enabled = False

    # Disable the fire-and-forget last_used_at update. In production each
    # request has its own DB session, so opening a parallel session for the
    # touch is harmless. With SQLite/StaticPool in tests it would race with
    # the request's own transaction on the shared connection. Tests don't
    # care about last_used_at — skip it entirely.
    async def _noop(*args, **kwargs):
        return None
    from services import api_token_service as _ats
    monkeypatch.setattr(_ats, "_touch_last_used", _noop)

    # Disable the fire-and-forget price seed on position-create. It opens its own
    # session and does a yfinance network call — both would race the shared SQLite
    # StaticPool connection and hit the network in tests. Tests don't assert on the
    # seeded price.
    def _noop_seed(*args, **kwargs):
        return None
    from services import cache_service as _cs
    monkeypatch.setattr(_cs, "trigger_position_price_seed", _noop_seed)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()
    limiter.enabled = True
