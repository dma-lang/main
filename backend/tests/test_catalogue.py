"""F4/F9: catalogue read endpoints over the seeded cat_v7. DB-backed, self-cleaning.

A module fixture provisions v7 once and drops it afterwards, so the suite stays order-independent.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app import db
from app.main import create_app
from app.services import provision

needs_db = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"), reason="DATABASE_URL not set (DB-backed test)"
)


@pytest.fixture(scope="module")
def provisioned() -> Iterator[None]:
    from app import migrate

    migrate.run()

    async def _setup() -> None:
        db.init_engine()
        await provision.bring_version_online("v7")
        await db.dispose_engine()

    async def _teardown() -> None:
        db.init_engine()
        engine = db.get_engine()
        assert engine is not None
        async with engine.begin() as conn:
            await conn.execute(text("DROP SCHEMA IF EXISTS cat_v7 CASCADE"))
            await conn.execute(
                text("DELETE FROM control.catalogue_version WHERE version_id = 'v7'")
            )
        await db.dispose_engine()

    asyncio.run(_setup())
    yield
    asyncio.run(_teardown())


@pytest.fixture
def client(provisioned: None) -> Iterator[TestClient]:
    with TestClient(create_app()) as c:
        yield c


@needs_db
def test_subcaps_tree(client: TestClient) -> None:
    r = client.get("/api/catalogue/v7/subcaps")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 851
    assert {"id", "name", "pillar", "cat_id", "cat_name", "cluster", "life"} <= set(body[0])


@needs_db
def test_subcap_detail(client: TestClient) -> None:
    sid = client.get("/api/catalogue/v7/subcaps").json()[0]["id"]
    r = client.get(f"/api/catalogue/v7/subcaps/{sid}")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == sid
    # Live counts present and truthfully zero on a freshly provisioned version (enrichment / F5
    # carry-forward seed these); also exercises the cross-schema story_catalogue_link subquery.
    assert body["n_use_cases"] == 0
    assert body["n_stories"] == 0
    assert body["n_platforms"] == 0


@needs_db
def test_summary(client: TestClient) -> None:
    r = client.get("/api/catalogue/v7/summary")
    assert r.status_code == 200
    body = r.json()
    assert body["total_subcaps"] == 851
    assert len(body["pillars"]) == 4


@needs_db
def test_unknown_version_404(client: TestClient) -> None:
    r = client.get("/api/catalogue/v999/subcaps")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"
