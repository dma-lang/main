"""Async database engine, session factory, and health helpers (F3).

The app uses asyncpg (async). The engine is opened on startup and disposed on shutdown so the pool
drains within the SIGTERM window. The pool is bounded (§16: max-instances x pool <= Cloud SQL
connection budget). All health helpers are resilient — they never raise into a request.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.settings import get_settings

logger = logging.getLogger("cia.db")

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


class DatabaseNotReadyError(RuntimeError):
    """No engine: DATABASE_URL unset or the migration job has not run. Maps to 503 (not 500) so
    the Login page can tell the operator exactly what to do."""


def init_engine() -> AsyncEngine | None:
    """Create the async engine + session factory if DATABASE_URL is set (idempotent)."""
    global _engine, _sessionmaker
    if _engine is not None:
        return _engine
    settings = get_settings()
    if not settings.database_url:
        logger.warning("DATABASE_URL not set; database features disabled")
        return None
    _engine = create_async_engine(
        settings.database_url,
        pool_size=5,
        max_overflow=5,
        pool_timeout=10,
        pool_pre_ping=True,
    )
    _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    logger.info("database engine initialised")
    return _engine


async def dispose_engine() -> None:
    """Dispose the pool on shutdown (graceful drain within the SIGTERM window)."""
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _sessionmaker = None
        logger.info("database engine disposed")


def get_engine() -> AsyncEngine | None:
    return _engine


def require_engine() -> AsyncEngine:
    """The engine, or DatabaseNotReadyError (503) — services use this instead of a bare
    RuntimeError so a missing/unmigrated database is never reported as a 500."""
    if _engine is None:
        raise DatabaseNotReadyError(
            "database not initialised — set DATABASE_URL and run the migration job "
            "(docs/DEPLOYMENT.md step A9)"
        )
    return _engine


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: an async session bound to the request lifecycle."""
    if _sessionmaker is None:
        raise DatabaseNotReadyError(
            "database not initialised — set DATABASE_URL and run the migration job "
            "(docs/DEPLOYMENT.md step A9)"
        )
    async with _sessionmaker() as session:
        yield session


async def ping() -> bool:
    """True if a trivial query succeeds; resilient (never raises)."""
    if _engine is None:
        return False
    try:
        async with _engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:  # pragma: no cover - exercised only on a real outage
        logger.warning("database ping failed: %s", exc)
        return False


async def active_catalogue_version() -> str | None:
    """The active catalogue version id, or None (no DB / no provisioned version yet)."""
    if _engine is None:
        return None
    try:
        async with _engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT version_id FROM control.catalogue_version "
                    "WHERE status IN ('active', 'provisioned') "
                    "ORDER BY created_at DESC LIMIT 1"
                )
            )
            row = result.first()
        return str(row[0]) if row is not None else None
    except Exception as exc:  # pragma: no cover - before the baseline migration runs
        logger.warning("active catalogue version lookup failed: %s", exc)
        return None
