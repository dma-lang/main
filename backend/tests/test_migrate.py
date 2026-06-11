"""F3/§15 — the migration runner's self-healing wait-for-database.

In a Cloud Run Job the Cloud SQL Auth Proxy sidecar can lag this container, so the first
connections race it and fail transiently ("server closed the connection unexpectedly", timeouts).
``_wait_for_db`` must retry those within a bounded window, yet fail FAST on a permanent error
(bad password, missing database) so it never burns the timeout on something a retry can't fix.

Classification is pure (no DB). The reachable/permanent paths are DB-backed (skipped without
DATABASE_URL); the unreachable-timeout path needs only a refused TCP port, so it always runs.
"""

from __future__ import annotations

import os
import time

import pytest
from sqlalchemy.exc import OperationalError

from app import migrate


class _Orig(Exception):
    """A stand-in DBAPI error carrying a SQLSTATE, like psycopg's errors."""

    def __init__(self, msg: str, sqlstate: str | None = None) -> None:
        super().__init__(msg)
        self.sqlstate = sqlstate


def _op_error(msg: str, sqlstate: str | None = None) -> OperationalError:
    return OperationalError("SELECT 1", {}, _Orig(msg, sqlstate))


def test_proxy_race_is_transient() -> None:
    # The exact signature the user hit: the Cloud SQL proxy sidecar not ready yet.
    assert migrate._is_transient(_op_error("server closed the connection unexpectedly"))
    assert migrate._is_transient(_op_error("connection timeout expired"))
    assert migrate._is_transient(_op_error("connection refused"))
    # socket not created yet by the proxy
    assert migrate._is_transient(_op_error('connection to server on socket "/cloudsql/x" failed'))


def test_transient_sqlstates() -> None:
    assert migrate._is_transient(_op_error("the database system is starting up", "57P03"))
    assert migrate._is_transient(_op_error("too many clients", "53300"))
    assert migrate._is_transient(_op_error("connection failure", "08006"))


def test_permanent_errors_fail_fast() -> None:
    # These can never be fixed by retrying — they must NOT be treated as transient.
    assert not migrate._is_transient(_op_error('password authentication failed for user "cia"'))
    assert not migrate._is_transient(_op_error('database "cia" does not exist'))
    assert not migrate._is_transient(_op_error("no pg_hba.conf entry for host"))
    assert not migrate._is_transient(_op_error("invalid password", "28P01"))
    assert not migrate._is_transient(_op_error("nope", "3D000"))


def test_unknown_connection_error_defaults_transient() -> None:
    # An unrecognised connection error is retried within the bounded window rather than aborting
    # on first contact (the proxy sidecar can lag) — the deadline still guarantees termination.
    assert migrate._is_transient(_op_error("some brand new proxy hiccup nobody enumerated"))


def test_wait_times_out_on_unreachable_host() -> None:
    # A refused port yields a transient error forever; _wait_for_db must give up at the deadline
    # (not hang) and surface an actionable TimeoutError — and it must have retried, not tried once.
    url = "postgresql+psycopg://nobody:nobody@127.0.0.1:1/postgres"
    start = time.monotonic()
    with pytest.raises(TimeoutError, match="not reachable after"):
        migrate._wait_for_db(url, max_wait=1.5)
    elapsed = time.monotonic() - start
    assert 1.0 <= elapsed <= 12.0  # waited out the window, bounded by connect_timeout


needs_db = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"), reason="DATABASE_URL not set (DB-backed test)"
)


def _psycopg_url() -> str:
    return os.environ["DATABASE_URL"].replace("+asyncpg", "+psycopg")


@needs_db
def test_wait_returns_quickly_when_reachable() -> None:
    start = time.monotonic()
    migrate._wait_for_db(_psycopg_url(), max_wait=10.0)  # returns on first attempt
    assert time.monotonic() - start < 5.0


@needs_db
def test_wait_fails_fast_on_missing_database() -> None:
    # A non-existent database is permanent (SQLSTATE 3D000) — must raise the real OperationalError
    # immediately, never wait out the window. Auth-method-independent (unlike a wrong password).
    base = _psycopg_url().rsplit("/", 1)[0]
    url = f"{base}/cia_no_such_db_zzz"
    start = time.monotonic()
    with pytest.raises(OperationalError):
        migrate._wait_for_db(url, max_wait=30.0)
    assert time.monotonic() - start < 10.0  # fast-failed, did not burn the 30s window
