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
    # 13,656 carry natively; the 750 whose subvertical-suffixed subcap ids are absent from v7
    # (P3C1.8.PEN1/PEN2 …) fall through to the embedding nearest-neighbour pass — never dropped.
    assert carried["stories_ingested"] == 14406
    assert carried["confirmed"] == 14406
    assert carried["unmapped"] == 0
    total = carried["confirmed"] + carried["review"] + carried["unmapped"]
    assert total == carried["stories_ingested"]
    # The v7 workbooks' embedded synthetic stories ingest alongside, labelled, never mixed.
    assert carried["synthetic_ingested"] == 4552
    # The v7 CATALOGUE's own per-subcap Jira references (Story_Refs_with_UC_Links) become real
    # links wherever the key resolves to a stored corpus story — exact, from the canonical seeds.
    assert carried["catalogue_ref_links"] == 1929  # additional links actually landed
    assert carried["catalogue_refs_unresolved"] == 160  # counted, never invented as stories
    assert carried["jira_linked_subcaps"] == 318  # up from the corpus' own 87


@needs_db
def test_nearest_neighbour_via_recorded(carried: dict[str, Any]) -> None:
    # The NN fallback is auditable: carries it resolved say so, with a similarity in-band.
    async def _q() -> list[dict[str, Any]]:
        db.init_engine()
        engine = db.get_engine()
        assert engine is not None
        async with engine.connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT via, count(*) AS n, min(similarity) AS lo, max(similarity) AS hi "
                        "FROM control.story_subcap_carry c "
                        "JOIN control.story s ON s.story_key = c.story_key "
                        "WHERE c.target_version = 'v7' AND NOT s.is_synthetic "
                        "GROUP BY via ORDER BY via"
                    )
                )
            ).mappings()
            out = [dict(r) for r in rows]
        await db.dispose_engine()
        return out

    by_via = {r["via"]: r for r in asyncio.run(_q())}
    assert by_via["native"]["n"] == 13656
    nn = by_via["nearest_neighbour"]
    assert nn["n"] == 750
    assert float(nn["lo"]) >= 0.70  # gated: only confirm/review bands carry a subcap


@needs_db
def test_carry_idempotent(carried: dict[str, Any]) -> None:
    async def _rerun() -> tuple[int, int]:
        db.init_engine()
        await stories.carry_forward("v7")
        engine = db.get_engine()
        assert engine is not None
        async with engine.connect() as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT count(*) FILTER (WHERE NOT is_synthetic) AS jira, "
                        "count(*) FILTER (WHERE is_synthetic) AS synthetic FROM control.story"
                    )
                )
            ).one()
        await db.dispose_engine()
        return int(row.jira), int(row.synthetic)

    # re-run upserts, never duplicates — and never blurs the Jira/synthetic boundary
    assert asyncio.run(_rerun()) == (14406, 4552)


@needs_db
def test_subcap_stories_endpoint(client: TestClient) -> None:
    r = client.get("/api/catalogue/v7/subcaps/P2C3.5.1/stories?size=5")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1513  # 1501 corpus carries + 12 catalogue-ref links
    assert len(body["items"]) == 5
    # ordered by composite desc, with the graded sub-scores present
    first = body["items"][0]
    assert first["composite_score"] is not None
    assert {"story_key", "ac_score", "sd_score", "story_score", "confidence_level"} <= set(first)


@needs_db
def test_detail_n_stories_lights_up(client: TestClient) -> None:
    detail = client.get("/api/catalogue/v7/subcaps/P2C3.5.1").json()
    assert detail["n_stories"] == 1513


@needs_db
def test_undelivered_subcap_has_no_stories(client: TestClient) -> None:
    # A subcap with no delivery history AND no catalogue refs shows an honest zero, not
    # borrowed counts. (P1C1.1.1 is no longer such a case: the v7 catalogue references real Jira
    # stories for it, which now link.)
    r = client.get("/api/catalogue/v7/subcaps/P1C1.1.6/stories")
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
    assert body["total"] == 14406  # the canonical corpus (synthetic excluded by default)
    assert (body["jira_total"], body["synthetic_total"]) == (14406, 4552)
    assert (body["high"], body["medium"], body["low"]) == (12417, 1873, 116)
    assert len(body["buckets"]) == 6 and sum(body["buckets"]) == 14406
    assert len(body["items"]) == 5
    assert all(r["is_synthetic"] is False for r in body["items"])
    # filters narrow the analysis set
    hi = client.get("/api/stories?conf=HIGH&pillar=P3&min_composite=2.5&size=1").json()
    assert 0 < hi["total"] < body["total"]


@needs_db
def test_story_library_synthetic_filter(client: TestClient) -> None:
    only = client.get("/api/stories?synthetic=only&size=5").json()
    assert only["total"] == 4552
    assert all(r["is_synthetic"] is True for r in only["items"])
    # synthetic keys are the workbook generations, never Jira-prefixed real keys
    assert all(r["source_system"] != "jira" for r in only["items"])
    both = client.get("/api/stories?synthetic=include&size=1").json()
    assert both["total"] == 14406 + 4552
    bogus = client.get("/api/stories?synthetic=everything&size=1").json()
    assert bogus["total"] == 14406  # unknown mode falls back to the safe default (exclude)


@needs_db
def test_analysis_view_is_jira_only(carried: dict[str, Any]) -> None:
    # The analysis-grade view (heatmap, counts, lifecycle, trace…) excludes synthetic rows by
    # construction — migration 0011 joins control.story and filters is_synthetic.
    async def _q() -> tuple[int, int]:
        db.init_engine()
        engine = db.get_engine()
        assert engine is not None
        async with engine.connect() as conn:
            linked = (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM control.story_catalogue_link "
                        "WHERE version_id = 'v7'"
                    )
                )
            ).scalar()
            syn_carries = (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM control.story_subcap_carry c "
                        "JOIN control.story s ON s.story_key = c.story_key "
                        "WHERE c.target_version = 'v7' AND s.is_synthetic"
                    )
                )
            ).scalar()
        await db.dispose_engine()
        return int(linked or 0), int(syn_carries or 0)

    linked, syn_carries = asyncio.run(_q())
    # every analysis row is a real Jira story: the 14,406 corpus carries + the catalogue's own
    # resolved story refs (multi-subcap links, via='catalogue_ref') — synthetic never enters
    assert linked == 14406 + carried["catalogue_ref_links"]
    assert syn_carries > 0  # synthetic carries exist (visible in the library) yet never leak


@needs_db
def test_delivery_drilldown_clients_and_clusters(client: TestClient) -> None:
    """The drilldown UNDER a subcap's story count: clients parsed from Jira project keys, story
    clusters with related clients, and totals that reconcile EXACTLY with n_stories/heatmap
    (same story_catalogue_link join — traceability)."""
    # pick the most-delivered subcap so clients + clusters are non-trivial
    top = client.get("/api/catalogue/v7/lifecycle").json()["top"][0]
    sid = top["id"]
    drill = client.get(f"/api/catalogue/v7/subcaps/{sid}/delivery").json()
    detail = client.get(f"/api/catalogue/v7/subcaps/{sid}").json()

    assert drill["subcap_id"] == sid
    assert drill["total_stories"] == detail["n_stories"] == top["stories"]  # numbers reconcile
    assert drill["n_clients"] >= 1
    assert len(drill["clients"]) >= 1

    c0 = drill["clients"][0]  # most-active client first
    assert c0["stories"] >= drill["clients"][-1]["stories"]
    assert 0 < c0["share"] <= 1
    assert sum(c["stories"] for c in drill["clients"]) <= drill["total_stories"]
    # per-client drilldown: its strongest stories ride along, keyed for the story library
    assert len(c0["top"]) >= 1
    assert c0["top"][0]["story_key"]

    # clusters: every member count + sample + related-client list is internally consistent
    for cl in drill["clusters"]:
        assert cl["stories"] >= 3  # _MIN_CLUSTER — no fake themes
        assert cl["label"]
        assert len(cl["sample"]) >= 1
        assert len(cl["clients"]) >= 1
    assert drill["clustered_over"] <= 600

    # unknown subcap is an honest 404, not an empty panel
    assert client.get("/api/catalogue/v7/subcaps/NOPE.1/delivery").status_code == 404
