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


def test_require_admin_blocks_non_admin() -> None:
    with pytest.raises(HTTPException) as exc:
        asyncio.run(require_admin(user={"uid": "u", "is_admin": False}))
    assert exc.value.status_code == 403


def test_require_admin_allows_admin() -> None:
    out = asyncio.run(require_admin(user={"uid": "u", "is_admin": True}))
    assert out["is_admin"] is True
