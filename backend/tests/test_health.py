"""F1: health/liveness probes and lifespan.

Uses a context-managed TestClient so the lifespan (startup + graceful-shutdown drain) actually runs.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app import APP_VERSION
from app.main import create_app


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app()) as c:
        yield c


def test_healthz_reports_version_and_mode(client: TestClient) -> None:
    r = client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["app_version"] == APP_VERSION
    assert body["llm_mode"]  # hermetic by default
    assert "catalogue_version" in body  # null until F4 provisions a version


def test_livez(client: TestClient) -> None:
    r = client.get("/livez")
    assert r.status_code == 200
    assert r.json() == {"status": "alive"}
