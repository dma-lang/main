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


def test_require_admin_blocks_non_admin() -> None:
    with pytest.raises(HTTPException) as exc:
        asyncio.run(require_admin(user={"uid": "u", "is_admin": False}))
    assert exc.value.status_code == 403


def test_require_admin_allows_admin() -> None:
    out = asyncio.run(require_admin(user={"uid": "u", "is_admin": True}))
    assert out["is_admin"] is True
