"""One-shot migration runner (F3, §16) — self-healing against a cold database.

Run as a Cloud Run Job to completion **before** the new revision gets traffic — never on startup.
Acquires a Postgres advisory lock on a direct (non-pooled) connection with a bounded lock_timeout,
skips when already at head (so repeated runs and ``terraform apply`` are no-ops), then runs
``alembic upgrade head``. Transactional DDL means a failed migration rolls back.

Self-healing (§15 bounded-everything): in a Cloud Run **Job** the Cloud SQL Auth Proxy runs as a
sidecar with NO startup-ordering guarantee relative to this container, so the first connections can
race the proxy and get "server closed the connection unexpectedly" / connection timeouts while it
establishes its tunnel. ``_wait_for_db`` retries those transient failures with bounded exponential
backoff+jitter until the database accepts a connection, then proceeds — while a genuinely permanent
error (bad password, missing database/role) is raised immediately so we fail fast instead of
burning the timeout. Every connection is also bounded by ``connect_timeout`` so no attempt hangs.
"""

from __future__ import annotations

import logging
import os
import random
import time
from pathlib import Path
from typing import Any

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, pool
from sqlalchemy.exc import OperationalError

from alembic import command
from app.settings import get_settings

logger = logging.getLogger("cia.migrate")

_LOCK_KEY = 776011  # stable advisory-lock key for CIA control-plane migrations
_BACKEND = Path(__file__).resolve().parent.parent

# Bound every connection attempt so a half-open socket never hangs (libpq/psycopg connect_timeout).
_CONNECT_ARGS = {"connect_timeout": 10}

# Postgres SQLSTATEs that mean "not ready yet — retry" vs "your request is wrong — stop now".
_TRANSIENT_SQLSTATES = {
    "57P03",  # cannot_connect_now (the database system is starting up)
    "08000",  # connection_exception
    "08001",  # sqlclient_unable_to_establish_sqlconnection
    "08004",  # sqlserver_rejected_establishment_of_sqlconnection
    "08006",  # connection_failure
    "53300",  # too_many_connections
    "57P01",  # admin_shutdown
    "57P02",  # crash_shutdown
}
_PERMANENT_SQLSTATES = {
    "28P01",  # invalid_password
    "28000",  # invalid_authorization_specification (incl. no pg_hba entry)
    "3D000",  # invalid_catalog_name (database does not exist)
    "42501",  # insufficient_privilege
}
# Substring fallbacks for drivers/states that don't surface a SQLSTATE (the Cloud SQL proxy race
# reports "server closed the connection unexpectedly" with none).
_PERMANENT_SUBSTR = (
    "password authentication failed",
    "does not exist",
    "no pg_hba.conf entry",
    "permission denied",
    'role "',
)
_TRANSIENT_SUBSTR = (
    "server closed the connection unexpectedly",
    "connection timeout expired",
    "could not connect to server",
    "connection refused",
    "connection reset by peer",
    "no such file or directory",  # the proxy has not created the socket yet (job sidecar race)
    "the database system is starting up",
    "the database system is shutting down",
    "timeout expired",
)


def _sync_url() -> str:
    settings = get_settings()
    url = settings.database_url or "postgresql+psycopg://cia:cia@localhost:5432/cia"
    return url.replace("+asyncpg", "+psycopg")


def _engine(url: str) -> Any:
    return create_engine(url, poolclass=pool.NullPool, connect_args=_CONNECT_ARGS)


def _brief(exc: BaseException) -> str:
    """The first line of an exception, trimmed — readable logs without the full traceback."""
    return str(exc).strip().splitlines()[0][:200] if str(exc).strip() else exc.__class__.__name__


def _is_transient(exc: BaseException) -> bool:
    """True if a connection error is worth retrying (proxy/instance not ready), False if it is a
    permanent misconfiguration (auth, missing database) we must surface immediately. Unknown
    connection errors default to transient: in a Cloud Run Job the SQL-proxy sidecar can lag this
    container, so we retry within the bounded window rather than aborting on first contact."""
    orig = getattr(exc, "orig", exc)
    sqlstate = getattr(orig, "sqlstate", None)
    if sqlstate in _PERMANENT_SQLSTATES:
        return False
    if sqlstate in _TRANSIENT_SQLSTATES:
        return True
    text = str(exc).lower()
    if any(s in text for s in _PERMANENT_SUBSTR):
        return False
    return True


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ[name])
    except (KeyError, ValueError):
        return default


def _wait_for_db(url: str, max_wait: float | None = None) -> None:
    """Block until the database accepts a connection, retrying transient failures with bounded
    exponential backoff+jitter. Raises immediately on a permanent error, and raises TimeoutError
    once ``max_wait`` (env MIGRATE_DB_WAIT_SECONDS, default 180s) is exhausted — so the job either
    migrates against a ready DB or fails with an actionable message, never silently hangs."""
    if max_wait is None:
        max_wait = _env_float("MIGRATE_DB_WAIT_SECONDS", 180.0)
    deadline = time.monotonic() + max_wait
    delay = 1.0
    attempts = 0
    engine = _engine(url)
    try:
        while True:
            attempts += 1
            try:
                with engine.connect() as conn:
                    conn.exec_driver_sql("SELECT 1")
                if attempts > 1:
                    logger.info("database reachable after %d attempt(s)", attempts)
                return
            except OperationalError as exc:
                if not _is_transient(exc):
                    raise  # bad password / missing database -> fail fast, retrying cannot help
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(
                        f"database not reachable after {max_wait:.0f}s ({attempts} attempts): "
                        f"{_brief(exc)} — verify the Cloud SQL instance is RUNNABLE and the job "
                        f"has --set-cloudsql-instances set"
                    ) from exc
                sleep_for = min(delay, max(0.0, remaining)) + random.uniform(0, 0.5)
                logger.warning(
                    "database not ready (attempt %d): %s — retrying in %.1fs",
                    attempts,
                    _brief(exc),
                    sleep_for,
                )
                time.sleep(sleep_for)
                delay = min(delay * 2, 8.0)
    finally:
        engine.dispose()


def _alembic_config() -> Config:
    cfg = Config(str(_BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(_BACKEND / "alembic"))
    return cfg


def _at_head(url: str, cfg: Config) -> bool:
    engine = _engine(url)
    try:
        with engine.connect() as conn:
            current = MigrationContext.configure(conn).get_current_revision()
        head = ScriptDirectory.from_config(cfg).get_current_head()
        return current == head
    finally:
        engine.dispose()


def run() -> int:
    """Idempotently bring the control plane to head under an advisory lock; returns an exit code."""
    url = _sync_url()
    cfg = _alembic_config()

    # Self-heal the Cloud Run Job <-> Cloud SQL proxy startup race before touching the schema.
    _wait_for_db(url)

    if _at_head(url, cfg):
        logger.info("already at head; nothing to do")
        return 0

    # Advisory lock on a DIRECT (non-pooled) connection with a bounded lock_timeout (§16).
    engine = _engine(url)
    try:
        with engine.connect() as conn:
            conn.exec_driver_sql("SET lock_timeout = '30s'")
            acquired = conn.exec_driver_sql(
                "SELECT pg_try_advisory_lock(%(key)s)", {"key": _LOCK_KEY}
            ).scalar()
            if not acquired:
                logger.error("could not acquire migration advisory lock; another run holds it")
                return 1
            try:
                if _at_head(url, cfg):  # another runner may have finished while we waited
                    logger.info("became head while acquiring lock; nothing to do")
                    return 0
                logger.info("running alembic upgrade head")
                command.upgrade(cfg, "head")
                logger.info("migration complete")
                return 0
            finally:
                conn.exec_driver_sql("SELECT pg_advisory_unlock(%(key)s)", {"key": _LOCK_KEY})
    finally:
        engine.dispose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    raise SystemExit(run())
