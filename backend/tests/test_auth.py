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


def test_named_admins_and_firebase_config_are_hardcoded_defaults() -> None:
    """The deployment's public Firebase web config + the two named admins are baked-in defaults
    (env still overrides for rotation) — a deploy needs no FIREBASE_*/ADMIN_EMAILS vars at all."""
    from app.settings import Settings

    s = Settings()
    assert s.admin_emails == ["tom.hedgecoth@zennify.com", "mishley.otiende@zennify.com"]
    assert s.firebase_project_id == "digital-maturity-assessor"
    assert s.firebase_web_api_key and s.firebase_web_api_key.startswith("AIza")
    assert s.firebase_auth_domain == "digital-maturity-assessor.firebaseapp.com"
    assert s.firebase_storage_bucket == "digital-maturity-assessor.firebasestorage.app"
    assert s.firebase_messaging_sender_id == "306195530103"
    assert s.firebase_app_id == "1:306195530103:web:5e924628c5bf54c91b2172"
    assert s.firebase_measurement_id == "G-9J4D5RR5D6"


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


def test_live_config_serves_full_firebase_block() -> None:
    """GET /api/config in live auth hands the SPA the FULL hardcoded web config."""
    from app.routers.me import client_config
    from app.settings import Settings

    cfg = asyncio.run(client_config(Settings(auth_mode="live")))
    fb = cfg["firebase"]
    assert cfg["auth_mode"] == "live" and fb is not None
    assert set(fb) == {
        "api_key",
        "auth_domain",
        "project_id",
        "storage_bucket",
        "messaging_sender_id",
        "app_id",
        "measurement_id",
    }
    assert fb["project_id"] == "digital-maturity-assessor"


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


def test_require_admin_blocks_non_admin() -> None:
    with pytest.raises(HTTPException) as exc:
        asyncio.run(require_admin(user={"uid": "u", "is_admin": False}))
    assert exc.value.status_code == 403


def test_require_admin_allows_admin() -> None:
    out = asyncio.run(require_admin(user={"uid": "u", "is_admin": True}))
    assert out["is_admin"] is True
