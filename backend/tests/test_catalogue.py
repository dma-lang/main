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
def test_heatmap_contract(client: TestClient) -> None:
    """Mission-control concentration heatmap: valid shape for every lens, a 6-band score axis, and
    every row's cells length 6. (Rows are empty until carry-forward seeds stories; the data path is
    exercised against the carried dev DB.) An unknown lens falls back to pillar."""
    for lens in ("pillar", "lifecycle", "maturity", "subvertical", "vendor", "value-chain"):
        body = client.get(f"/api/catalogue/v7/heatmap?lens={lens}").json()
        assert body["lens"] == lens
        assert len(body["axis"]) == 6
        assert isinstance(body["rows"], list)
        for row in body["rows"]:
            assert len(row["cells"]) == 6
            assert row["total"] == sum(row["cells"]) or row["total"] >= max(row["cells"])
    assert client.get("/api/catalogue/v7/heatmap?lens=bogus").json()["lens"] == "pillar"


@needs_db
def test_subcap_timeline_contract(client: TestClient) -> None:
    """Project-subcap trace: a known subcap returns the timeline shape (events list with the trust
    envelope per event + a delivery story count); an unknown subcap 404s, never 500s."""
    sid = client.get("/api/catalogue/v7/subcaps").json()[0]["id"]
    body = client.get(f"/api/catalogue/v7/subcaps/{sid}/timeline").json()
    assert body["subcap_id"] == sid and body["name"]
    assert isinstance(body["events"], list) and isinstance(body["stories"], int)
    for ev in body["events"]:
        assert ev["kind"] in {"news", "vendor", "suggestion", "benchmark", "trend", "sow"}
        assert {"date", "title", "claim", "tier", "chain"} <= set(ev)
    assert client.get("/api/catalogue/v7/subcaps/NOPE.0.0/timeline").status_code == 404


@needs_db
def test_kg_layer_a_projection(client: TestClient) -> None:
    """Knowledge graph: a subcap with platforms projects a deterministic Layer-A neighbourhood —
    the centre node plus platform/offering/sibling edges, every edge a real link-table row. Unknown
    subcap 404s. Pending (Layer B) is a separate list, never mixed into the deterministic edges."""
    # find a subcap that actually has platforms so the projection is non-trivial
    sid = next(
        x["id"]
        for x in client.get("/api/catalogue/v7/subcaps").json()
        if client.get(f"/api/catalogue/v7/subcaps/{x['id']}").json()["n_platforms"] > 0
    )
    body = client.get(f"/api/catalogue/v7/kg?subcap={sid}").json()
    assert body["center"] == sid and body["name"]
    assert any(n["id"] == sid and n["kind"] == "subcap" for n in body["nodes"])
    assert body["stats"]["platforms"] > 0
    assert all(e["layer"] == "A_deterministic" for e in body["edges"])  # never proposed in Layer A
    assert all(e["layer"] == "B_proposed" for e in body["pending"])
    assert client.get("/api/catalogue/v7/kg?subcap=NOPE.0.0").status_code == 404


@needs_db
def test_whatif_cascade_preview(client: TestClient) -> None:
    """What-if: the read-only blast radius of a change to a subcap sums its offering / platform /
    story / use-case / sibling links; blast equals that sum and 404s on an unknown subcap."""
    sid = next(
        x["id"]
        for x in client.get("/api/catalogue/v7/subcaps").json()
        if client.get(f"/api/catalogue/v7/subcaps/{x['id']}").json()["n_platforms"] > 0
    )
    d = client.get(f"/api/catalogue/v7/whatif?subcap={sid}&action=retire").json()
    assert d["subcap"] == sid and d["action"] == "retire" and d["reversible"] is True
    assert (
        d["blast"]
        == len(d["offerings"])
        + len(d["platforms"])
        + len(d["siblings"])
        + d["stories"]
        + d["use_cases"]
    )
    assert d["platforms"] and "Retiring" in d["summary"]
    assert client.get("/api/catalogue/v7/whatif?subcap=NOPE.0.0").status_code == 404


@needs_db
def test_subcap_detail(client: TestClient) -> None:
    sid = client.get("/api/catalogue/v7/subcaps").json()[0]["id"]
    r = client.get(f"/api/catalogue/v7/subcaps/{sid}")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == sid
    # Catalogue enrichment seeded by provisioning lights up the use-case / platform counts; the
    # story count stays 0 until carry-forward runs (also exercises the cross-schema
    # story_catalogue_link subquery, which must resolve to zero here).
    assert body["n_use_cases"] > 0
    assert body["n_platforms"] > 0
    assert body["n_stories"] == 0


@needs_db
def test_subcap_enrichment(client: TestClient) -> None:
    r = client.get("/api/catalogue/v7/subcaps/P1C1.1.1/enrichment")
    assert r.status_code == 200
    body = r.json()
    # Seeded from the comprehensive pillar workbooks.
    assert len(body["personas"]) > 0
    assert len(body["platforms"]) > 0
    assert len(body["use_cases"]) > 0
    assert [m["level"] for m in body["maturity"]] == ["M1", "M2", "M3", "M4", "M5"]
    assert {"l3_id", "name", "vendor"} <= set(body["platforms"][0])
    assert "offerings" in body  # productized offerings the subcap is mapped to (may be empty)


@needs_db
def test_subcap_connections(client: TestClient) -> None:
    r = client.get("/api/catalogue/v7/subcaps/P1C1.1.1/connections")
    assert r.status_code == 200
    sibs = r.json()["siblings"]
    assert len(sibs) > 0
    assert {"id", "name", "pillar", "shared_platforms"} <= set(sibs[0])
    assert all(s["id"] != "P1C1.1.1" for s in sibs)  # KG siblings exclude self


@needs_db
def test_summary(client: TestClient) -> None:
    r = client.get("/api/catalogue/v7/summary")
    assert r.status_code == 200
    body = r.json()
    assert body["total_subcaps"] == 851
    assert len(body["pillars"]) == 4


@needs_db
def test_platforms_and_vendors(client: TestClient) -> None:
    plats = client.get("/api/catalogue/v7/platforms").json()
    assert len(plats) > 0
    top = plats[0]
    assert top["subcap_count"] > 0
    assert {"l3_id", "name", "vendor", "p1", "p2", "p3", "p4", "stories"} <= set(top)
    detail = client.get(f"/api/catalogue/v7/platforms/{top['l3_id']}").json()
    assert detail["l3_id"] == top["l3_id"]
    assert len(detail["subcaps"]) == top["subcap_count"]
    vendors = client.get("/api/catalogue/v7/vendors").json()
    assert len(vendors) > 0 and vendors[0]["subcap_count"] > 0


@needs_db
def test_use_cases(client: TestClient) -> None:
    r = client.get("/api/catalogue/v7/use-cases?size=5")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] > 0
    assert len(body["items"]) == 5
    assert len(body["archetypes"]) > 0
    assert {"use_case_id", "archetype", "subcap_id", "pillar", "category"} <= set(body["items"][0])
    # pillar filter narrows the set
    p4 = client.get("/api/catalogue/v7/use-cases?pillar=P4&size=1").json()
    assert 0 < p4["total"] < body["total"]
    assert all(left == "P4" for left in [i["pillar"] for i in p4["items"]])


@needs_db
def test_unknown_version_404(client: TestClient) -> None:
    r = client.get("/api/catalogue/v999/subcaps")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


@needs_db
def test_applied_mapping_registry(client: TestClient) -> None:
    """Schema-mapping studio (F4): provisioning registers the mapping it ACTUALLY applied — every
    field row traces to a load statement, relations to the FKs/link tables it created. An
    unprovisioned version is a clear 404."""
    body = client.get("/api/admin/mapping/v7").json()
    assert len(body["fields"]) == 16 and len(body["relations"]) == 7
    f = {x["source_field"]: x for x in body["fields"]}
    assert f["subcaps.id"]["canonical_entity"] == "subcap"
    assert all(x["status"] == "confirmed" and x["confidence"] == 1.0 for x in body["fields"])
    rels = {(r["from_entity"], r["rel_type"], r["to_entity"]) for r in body["relations"]}
    assert ("subcap", "uses_platform", "l3_platform") in rels
    assert ("category", "belongs_to", "pillar") in rels
    assert client.get("/api/admin/mapping/v5").status_code == 404
