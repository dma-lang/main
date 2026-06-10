"""F9: API conventions — trust envelope + pagination models, /api/versions, error envelope.

Model tests run anywhere; the version/error tests are DB-backed (skipped without DATABASE_URL).
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.models.common import Page
from app.models.enums import ClaimLabel, SourceTier
from app.models.trust import TrustEnvelope

needs_db = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"), reason="DATABASE_URL not set (DB-backed test)"
)


@pytest.fixture(scope="module")
def _migrated() -> None:
    from app import migrate

    migrate.run()


@pytest.fixture
def client(_migrated: None) -> Iterator[TestClient]:
    with TestClient(create_app()) as c:
        yield c


def test_trust_envelope_serializes() -> None:
    env = TrustEnvelope(
        claim_label=ClaimLabel.FACT, source_tier=SourceTier.T1, ers=0.9, chain_id="rc-1"
    )
    dumped = env.model_dump()
    assert dumped["claim_label"] == "FACT"
    assert dumped["source_tier"] == "T1"
    assert dumped["ers"] == 0.9
    assert dumped["chain_id"] == "rc-1"


def test_page_has_more() -> None:
    page: Page[int] = Page[int](items=[1, 2], total=10, page=1, page_size=2)
    assert page.has_more is True
    assert page.model_dump()["has_more"] is True


@needs_db
def test_list_versions_returns_list(client: TestClient) -> None:
    r = client.get("/api/versions")
    assert r.status_code == 200
    assert isinstance(r.json(), list)  # may contain provisioned versions (F4+)


@needs_db
def test_resolve_version_404_uses_error_envelope(client: TestClient) -> None:
    r = client.get("/api/versions/v999")
    assert r.status_code == 404
    body = r.json()
    assert body["error"]["code"] == "not_found"
    assert "message" in body["error"]
