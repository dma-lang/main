"""F2: identity, preferences, and the admin gate.

The identity/preferences tests are DB-backed (skipped without DATABASE_URL). The require_admin gate
is pure logic and always runs. A module fixture brings the control plane to head before DB tests.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.deps import require_admin
from app.main import create_app

needs_db = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"), reason="DATABASE_URL not set (DB-backed test)"
)


@pytest.fixture(scope="module")
def _migrated() -> None:
    from app import migrate

    migrate.run()  # idempotent: at-head skip or upgrade


@pytest.fixture
def client(_migrated: None) -> Iterator[TestClient]:
    with TestClient(create_app()) as c:
        yield c


@needs_db
def test_me_returns_hermetic_identity(client: TestClient) -> None:
    r = client.get("/api/me")
    assert r.status_code == 200
    body = r.json()
    assert body["uid"]
    assert body["email"] == "dev@zennify.com"
    assert body["is_admin"] is True
    assert "preferences" in body


@needs_db
def test_update_preferences_persists(client: TestClient) -> None:
    payload = {"preferences": {"theme": "dark", "lens": "pillar"}}
    r = client.patch("/api/me/preferences", json=payload)
    assert r.status_code == 200
    assert r.json()["preferences"]["theme"] == "dark"
    again = client.get("/api/me").json()  # a fresh read reflects the persisted change
    assert again["preferences"]["lens"] == "pillar"


def test_hermetic_llm_mode_does_not_disable_auth() -> None:
    """The cost switch must never disable authentication: LLM_MODE=hermetic with live auth still
    fails closed on a missing token (the dev identity needs AUTH_MODE=dev EXPLICITLY)."""
    from app.deps import get_current_user
    from app.settings import Settings

    s = Settings(llm_mode="hermetic", auth_mode="live")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(get_current_user(authorization=None, settings=s))
    assert exc.value.status_code == 401


@needs_db
def test_admin_grant_list_is_runtime_editable(client: TestClient) -> None:
    """The admin config space: the two named admins are seeded; grants/revokes persist, are
    domain-restricted, audited, and a bootstrap (env) admin cannot be revoked here."""
    seeded = {a["email"] for a in client.get("/api/admin/admins").json()}
    assert "tom.hedgecoth@zennify.com" in seeded
    assert "mishley.otiende@zennify.com" in seeded

    # grant -> persisted and listed as a removable runtime grant
    assert client.post("/api/admin/admins", json={"email": "qa.lead@zennify.com"}).json()["ok"]
    row = next(
        a for a in client.get("/api/admin/admins").json() if a["email"] == "qa.lead@zennify.com"
    )
    assert row["source"] == "grant" and row["removable"] is True

    # non-domain is rejected (admins must be @zennify.com, like sign-in)
    assert client.post("/api/admin/admins", json={"email": "x@gmail.com"}).status_code == 400

    # revoke a runtime grant; revoking a non-grant 404s
    assert client.request("DELETE", "/api/admin/admins/qa.lead@zennify.com").json()["ok"]
    assert client.request("DELETE", "/api/admin/admins/nobody@zennify.com").status_code == 404


def test_admin_resolution_unions_bootstrap_and_grants() -> None:
    """ADMIN_EMAILS (env bootstrap) is admin immediately, before any DB grant — defense in depth
    so an operator can never lock everyone out."""
    from app.services.admins import _bootstrap
    from app.settings import Settings

    s = Settings(admin_emails=["boss@zennify.com"])
    assert _bootstrap(s) == {"boss@zennify.com"}


def test_named_admins_are_hardcoded_defaults_and_auth_fails_closed_unconfigured() -> None:
    """The two named admins stay baked-in defaults. Live auth uses plain Google Identity
    Services: without GOOGLE_CLIENT_ID the verifier must fail CLOSED with an actionable 503 —
    never accept a token whose audience we can't pin."""
    from fastapi import HTTPException

    from app.deps import _verify_google
    from app.settings import Settings

    s = Settings()
    assert s.admin_emails == ["tom.hedgecoth@zennify.com", "mishley.otiende@zennify.com"]
    assert s.google_client_id == ""  # set per-deployment via GOOGLE_CLIENT_ID
    with pytest.raises(HTTPException) as exc:
        _verify_google("whatever", Settings(auth_mode="live", google_client_id=""))
    assert exc.value.status_code == 503
    assert "GOOGLE_CLIENT_ID" in str(exc.value.detail)


def test_admin_emails_env_accepts_plain_lists(monkeypatch: pytest.MonkeyPatch) -> None:
    """ADMIN_EMAILS=a,b (the documented form) must not crash settings at boot — pydantic-settings
    would JSON-decode it in the env source; NoDecode + the validator accept comma, semicolon and
    JSON-array forms."""
    from app.settings import Settings

    monkeypatch.setenv("ADMIN_EMAILS", "a@zennify.com,b@zennify.com")
    assert Settings().admin_emails == ["a@zennify.com", "b@zennify.com"]
    monkeypatch.setenv("ADMIN_EMAILS", "a@zennify.com;b@zennify.com")
    assert Settings().admin_emails == ["a@zennify.com", "b@zennify.com"]
    monkeypatch.setenv("ADMIN_EMAILS", '["c@zennify.com"]')
    assert Settings().admin_emails == ["c@zennify.com"]


def test_live_config_serves_google_client_id() -> None:
    """GET /api/config in live auth hands the SPA the Google OAuth client id (a public
    identifier); dev mode serves none. No Firebase block anywhere."""
    from app.routers.me import client_config
    from app.settings import Settings

    cfg = asyncio.run(
        client_config(Settings(auth_mode="live", google_client_id="abc.apps.googleusercontent.com"))
    )
    assert cfg["auth_mode"] == "live"
    assert cfg["google_client_id"] == "abc.apps.googleusercontent.com"
    assert "firebase" not in cfg
    dev = asyncio.run(client_config(Settings(auth_mode="dev")))
    assert dev["auth_mode"] == "dev" and dev["google_client_id"] is None


def test_db_not_ready_is_503_not_500(monkeypatch: pytest.MonkeyPatch) -> None:
    """No engine (DATABASE_URL unset / migration job not run) must surface as an actionable 503
    `unavailable` envelope, not a generic 500 — the Login page tells the operator to run A9."""
    from app import db

    monkeypatch.setattr(db, "init_engine", lambda: None)  # lifespan no-op: simulate no DB
    monkeypatch.setattr(db, "_engine", None)
    monkeypatch.setattr(db, "_sessionmaker", None)
    with TestClient(create_app(), raise_server_exceptions=False) as c:
        r = c.get("/api/me")
    assert r.status_code == 503
    body = r.json()["error"]
    assert body["code"] == "unavailable"
    assert "migration job" in body["message"]


def test_google_token_transport_is_installed() -> None:
    """REGRESSION: live sign-in verifies the Google ID token via
    google.auth.transport.requests, which needs the `requests` package — shipped only by the
    google-auth[requests] EXTRA. When it was missing, EVERY real sign-in 500'd with an ImportError
    that the Login page mislabelled 'database not ready'. This guards the dependency for good."""
    import importlib

    importlib.import_module("requests")
    importlib.import_module("google.auth.transport.requests")  # must import, not ImportError


def test_db_unreachable_is_honest_503_not_500(monkeypatch: pytest.MonkeyPatch) -> None:
    """The engine EXISTS but the database is UNREACHABLE (driver OperationalError): the request
    must surface as a clean 503 whose message points at the SERVICE's Cloud SQL connection — never
    a raw 500, and never the misleading 'run the migration job' (that's a different connection)."""
    from sqlalchemy.exc import OperationalError

    from app.services import users

    async def _boom(*_a: object, **_k: object) -> dict[str, object]:
        raise OperationalError("SELECT 1", {}, Exception("connection refused"))

    monkeypatch.setattr(users, "upsert_user", _boom)
    with TestClient(create_app(), raise_server_exceptions=False) as c:
        r = c.get("/api/me")  # dev identity -> straight to the upsert -> DB error
    assert r.status_code == 503
    msg = r.json()["error"]["message"]
    assert "cannot reach its database" in msg
    # it must clarify this is the SERVICE's connection, NOT tell them to run the migration job
    assert "NOT the migration job" in msg


def test_config_reports_db_health_for_login_preflight() -> None:
    """/api/config carries db status so the Login page can name the exact blocker (sign-in
    unconfigured vs database unreachable) before the user ever clicks."""
    with TestClient(create_app()) as c:
        cfg = c.get("/api/config").json()
    assert cfg["db"] in {"ok", "down", "not_configured"}


def test_require_admin_blocks_non_admin() -> None:
    with pytest.raises(HTTPException) as exc:
        asyncio.run(require_admin(user={"uid": "u", "is_admin": False}))
    assert exc.value.status_code == 403


def test_require_admin_allows_admin() -> None:
    out = asyncio.run(require_admin(user={"uid": "u", "is_admin": True}))
    assert out["is_admin"] is True
