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


# --------------------------------------------------------------------------------------------
# END-TO-END SIMULATION of the Cloud Run Job <-> Cloud SQL Auth Proxy hop (tests/proxy_sim.py).
# Runs the EXACT job entrypoint (python -m app.migrate) through a fake proxy socket that
# misbehaves precisely the way production did, proving each outcome rather than guessing it.
# --------------------------------------------------------------------------------------------
import subprocess  # noqa: E402
import sys  # noqa: E402
from pathlib import Path  # noqa: E402
from urllib.parse import urlsplit  # noqa: E402

_BACKEND_DIR = Path(__file__).resolve().parent.parent


def _run_job_entrypoint(socket_dir: Path, dbname: str, wait_seconds: str) -> tuple[int, str]:
    """python -m app.migrate, exactly like the Cloud Run job, against a unix-socket DB URL."""
    env = dict(os.environ)
    env["DATABASE_URL"] = f"postgresql+psycopg://cia:cia@/{dbname}?host={socket_dir}"
    env["MIGRATE_DB_WAIT_SECONDS"] = wait_seconds
    proc = subprocess.run(
        [sys.executable, "-m", "app.migrate"],
        cwd=_BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    return proc.returncode, proc.stdout + proc.stderr


@needs_db
def test_e2e_migrate_survives_the_proxy_startup_race(tmp_path: Path) -> None:
    """The sidecar race: the proxy drops connections for the first seconds, then works. The job
    must log the retries, connect once the tunnel is up, and exit 0 — no human, no re-run."""
    from proxy_sim import FakeSqlProxy

    parts = urlsplit(os.environ["DATABASE_URL"].replace("+asyncpg", ""))
    proxy = FakeSqlProxy(
        tmp_path,
        target_host=parts.hostname or "127.0.0.1",
        target_port=parts.port or 5432,
        mode="drop_then_ok",
        drop_for=3.0,
    )
    proxy.start()
    try:
        rc, out = _run_job_entrypoint(tmp_path, (parts.path or "/cia_test").lstrip("/"), "60")
    finally:
        proxy.stop()
    assert rc == 0, out
    assert "database not ready (attempt" in out  # it hit the race…
    assert "reachable after" in out  # …healed itself…
    assert proxy.dropped >= 1 and proxy.forwarded >= 1  # …through the proxy, not around it


def test_e2e_migrate_bounded_when_proxy_never_reaches_the_backend(tmp_path: Path) -> None:
    """The production blocker: the proxy accepts and drops FOREVER (it cannot reach the instance
    backend — e.g. private-IP-only with no VPC egress). The simulation must reproduce the exact
    production error string, and the job must give up at the bound with an actionable message —
    never hang, never exit opaquely."""
    from proxy_sim import FakeSqlProxy

    proxy = FakeSqlProxy(tmp_path, mode="drop")  # never forwards; Postgres is never contacted
    proxy.start()
    try:
        rc, out = _run_job_entrypoint(tmp_path, "cia", "6")
    finally:
        proxy.stop()
    assert rc != 0
    assert "server closed the connection unexpectedly" in out  # the literal production signature
    assert "not reachable after 6s" in out
    assert "--set-cloudsql-instances" in out  # the actionable hint names the wiring to check


def test_e2e_migrate_bounded_when_the_proxy_socket_is_absent(tmp_path: Path) -> None:
    """The sidecar never even created the socket: still a bounded, explained failure."""
    rc, out = _run_job_entrypoint(tmp_path, "cia", "5")
    assert rc != 0
    assert "not reachable after 5s" in out
    assert "database not ready (attempt" in out  # retried (transient), then gave up at the bound
