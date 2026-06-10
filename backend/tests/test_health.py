"""F1: health/liveness probes and lifespan.

Uses a context-managed TestClient so the lifespan (startup + graceful-shutdown drain) actually runs.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import APP_VERSION
from app.main import _APP_ROOT, _mount_spa, create_app


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


def test_spa_served_from_built_dir(tmp_path: Path) -> None:
    """A real build (index.html + assets) is served at '/', mounted last so API routes still win."""
    (tmp_path / "index.html").write_text("<!doctype html><title>CIA</title>")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text("export {}")
    app = FastAPI()
    _mount_spa(app, str(tmp_path))
    with TestClient(app) as c:
        r = c.get("/")
        assert r.status_code == 200 and "CIA" in r.text


def test_relative_static_dir_anchored_to_app_root_not_cwd(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A relative STATIC_DIR resolves against the app root, not the launch cwd — the bug where a
    wrong cwd silently served a stale build. Asserted via the resolved path, run from cwd=/tmp."""
    monkeypatch.chdir("/tmp")
    app = FastAPI()
    with caplog.at_level(logging.WARNING, logger="cia"):
        _mount_spa(app, "no-such-build-xyz")  # resolves under the app root, not /tmp
    assert str(_APP_ROOT / "no-such-build-xyz") in caplog.text


def test_incomplete_build_serves_api_only(tmp_path: Path) -> None:
    """A dir present but missing index.html (incomplete/stale build) is not mounted — the API still
    works; the SPA route simply 404s instead of crashing boot."""
    (tmp_path / "assets").mkdir()  # no index.html
    app = FastAPI()

    @app.get("/api/ping")
    def _ping() -> dict[str, str]:
        return {"ok": "1"}

    _mount_spa(app, str(tmp_path))
    with TestClient(app) as c:
        assert c.get("/api/ping").json() == {"ok": "1"}  # API intact
        assert c.get("/").status_code == 404  # SPA not mounted
