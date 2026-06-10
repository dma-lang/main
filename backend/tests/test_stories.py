"""F5: canonical story corpus ingest + carry-forward onto v7. DB-backed, self-cleaning.

A module fixture provisions v7, ingests the corpus and carries it; teardown drops cat_v7 and clears
the story tables so the suite stays order-independent (other modules assert n_stories == 0).
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app import db
from app.main import create_app
from app.services import provision, stories

needs_db = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"), reason="DATABASE_URL not set (DB-backed test)"
)


@pytest.fixture(scope="module")
def carried() -> Iterator[dict[str, Any]]:
    from app import migrate

    migrate.run()
    summary: dict[str, Any] = {}

    async def _setup() -> dict[str, Any]:
        db.init_engine()
        await provision.bring_version_online("v7")
        result = await stories.carry_forward("v7")
        await db.dispose_engine()
        return result

    async def _teardown() -> None:
        db.init_engine()
        engine = db.get_engine()
        assert engine is not None
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM control.story_subcap_carry"))
            await conn.execute(text("DELETE FROM control.story"))
            await conn.execute(text("DROP SCHEMA IF EXISTS cat_v7 CASCADE"))
            await conn.execute(
                text("DELETE FROM control.catalogue_version WHERE version_id = 'v7'")
            )
        await db.dispose_engine()

    summary.update(asyncio.run(_setup()))
    yield summary
    asyncio.run(_teardown())


@pytest.fixture
def client(carried: dict[str, Any]) -> Iterator[TestClient]:
    with TestClient(create_app()) as c:
        yield c


@needs_db
def test_carry_summary(carried: dict[str, Any]) -> None:
    # Exact, because the seed is the canonical 14,406-row corpus committed to the repo.
    assert carried["stories_ingested"] == 14406
    assert carried["confirmed"] == 13656
    assert carried["unmapped"] == 750
    assert carried["confirmed"] + carried["unmapped"] == carried["stories_ingested"]


@needs_db
def test_carry_idempotent(carried: dict[str, Any]) -> None:
    async def _rerun() -> int:
        db.init_engine()
        await stories.carry_forward("v7")
        engine = db.get_engine()
        assert engine is not None
        async with engine.connect() as conn:
            n = (await conn.execute(text("SELECT count(*) FROM control.story"))).scalar()
        await db.dispose_engine()
        return int(n or 0)

    assert asyncio.run(_rerun()) == 14406  # re-run upserts, never duplicates


@needs_db
def test_subcap_stories_endpoint(client: TestClient) -> None:
    r = client.get("/api/catalogue/v7/subcaps/P2C3.5.1/stories?size=5")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1501
    assert len(body["items"]) == 5
    # ordered by composite desc, with the graded sub-scores present
    first = body["items"][0]
    assert first["composite_score"] is not None
    assert {"story_key", "ac_score", "sd_score", "story_score", "confidence_level"} <= set(first)


@needs_db
def test_detail_n_stories_lights_up(client: TestClient) -> None:
    detail = client.get("/api/catalogue/v7/subcaps/P2C3.5.1").json()
    assert detail["n_stories"] == 1501


@needs_db
def test_unmapped_subcap_has_no_stories(client: TestClient) -> None:
    # P3C1.8.PEN1/PEN2 subverticals are absent from v7 -> those stories are unmapped, never dropped.
    r = client.get("/api/catalogue/v7/subcaps/P1C1.1.1/stories")
    assert r.status_code == 200
    assert r.json()["total"] == 0


@needs_db
def test_lifecycle(client: TestClient) -> None:
    body = client.get("/api/catalogue/v7/lifecycle").json()
    assert body["subcaps_delivered"] > 0  # carry-forward linked the corpus
    assert body["offerings"] > 0  # offerings seeded by enrichment
    assert 0 <= body["covered_pct"] <= 100
    assert 0 <= body["gaps"] <= body["subcaps_delivered"]
    assert len(body["top"]) > 0
    assert body["top"][0]["stories"] > 0  # most-delivered subcap carries a real story count


@needs_db
def test_story_library_endpoint(client: TestClient) -> None:
    body = client.get("/api/stories?size=5").json()
    assert body["total"] == 14406  # the canonical corpus (synthetic excluded)
    assert (body["high"], body["medium"], body["low"]) == (12417, 1873, 116)
    assert len(body["buckets"]) == 6 and sum(body["buckets"]) == 14406
    assert len(body["items"]) == 5
    # filters narrow the analysis set
    hi = client.get("/api/stories?conf=HIGH&pillar=P3&min_composite=2.5&size=1").json()
    assert 0 < hi["total"] < body["total"]
