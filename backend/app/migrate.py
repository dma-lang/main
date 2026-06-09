"""One-shot migration runner (F3, §16).

Run as a Cloud Run Job to completion **before** the new revision gets traffic — never on startup.
Acquires a Postgres advisory lock on a direct (non-pooled) connection with a bounded lock_timeout,
skips when already at head (so repeated runs and ``terraform apply`` are no-ops), then runs
``alembic upgrade head``. Transactional DDL means a failed migration rolls back.
"""

from __future__ import annotations

import logging
from pathlib import Path

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, pool

from alembic import command
from app.settings import get_settings

logger = logging.getLogger("cia.migrate")

_LOCK_KEY = 776011  # stable advisory-lock key for CIA control-plane migrations
_BACKEND = Path(__file__).resolve().parent.parent


def _sync_url() -> str:
    settings = get_settings()
    url = settings.database_url or "postgresql+psycopg://cia:cia@localhost:5432/cia"
    return url.replace("+asyncpg", "+psycopg")


def _alembic_config() -> Config:
    cfg = Config(str(_BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(_BACKEND / "alembic"))
    return cfg


def _at_head(url: str, cfg: Config) -> bool:
    engine = create_engine(url, poolclass=pool.NullPool)
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

    if _at_head(url, cfg):
        logger.info("already at head; nothing to do")
        return 0

    # Advisory lock on a DIRECT (non-pooled) connection with a bounded lock_timeout (§16).
    engine = create_engine(url, poolclass=pool.NullPool)
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
