"""Value-chain inheritance + graceful SV scoping (user reports on the deployed v5).

A version provisioned BEFORE the VC cascade has an empty subcap_vcc. This must NOT (a) derive ad-hoc
L1 cluster names on the atlas, nor (b) collapse the mission-control tiles / workbench tree to zero.
Instead the atlas INHERITS the reference version's (v7) real named chains, and the SV scope falls
back to actual delivery (story_sv_code). The fixture reproduces that stale state by emptying v5's
VC mapping after provisioning, so the assertions exercise the read-time fallbacks (no re-provision).
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
from app.services import stories as story_svc

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
        await provision.bring_version_online("v5", label="Catalogue v5.0")
        await story_svc.carry_forward("v7")
        await story_svc.carry_forward("v5")
        engine = db.get_engine()
        assert engine is not None
        async with engine.begin() as conn:
            # simulate v5 provisioned BEFORE the cascade: NO enrichment of its own, so the atlas,
            # the value-chain/vendor lenses, AND the B-group pages (platforms / use cases / KG) must
            # all INHERIT v7 at read time. FK-safe order: subcap_platform -> l3_platform -> vendor.
            await conn.execute(text("DELETE FROM cat_v5.subcap_vcc"))
            await conn.execute(text("DELETE FROM cat_v5.value_chain_cluster"))
            await conn.execute(text("DELETE FROM cat_v5.subcap_platform"))
            await conn.execute(text("DELETE FROM cat_v5.l3_platform"))
            await conn.execute(text("DELETE FROM cat_v5.use_case"))
        await db.dispose_engine()

    async def _teardown() -> None:
        db.init_engine()
        engine = db.get_engine()
        assert engine is not None
        async with engine.begin() as conn:
            # the auto-run detector writes reasoning_chain + many FK dependents (suggestion, change_
            # flag, citation, pending_edge, trend, …) — TRUNCATE CASCADE clears them all FK-safe.
            await conn.execute(text("TRUNCATE control.reasoning_chain CASCADE"))
            await conn.execute(text("DELETE FROM control.evidence_item WHERE kind = 'catalogue'"))
            await conn.execute(text("DELETE FROM control.story_subcap_carry"))
            await conn.execute(text("DELETE FROM control.story"))
            await conn.execute(text("DROP SCHEMA IF EXISTS cat_v5 CASCADE"))
            await conn.execute(text("DROP SCHEMA IF EXISTS cat_v7 CASCADE"))
            await conn.execute(
                text(
                    "DELETE FROM control.version_crosswalk "
                    "WHERE from_version IN ('v5','v7') OR to_version IN ('v5','v7')"
                )
            )
            await conn.execute(
                text("DELETE FROM control.catalogue_version WHERE version_id IN ('v5','v7')")
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
def test_v5_without_vc_mapping_inherits_v7_chains(client: TestClient) -> None:
    """The atlas shows v7's REAL named stages (inherited), never ad-hoc L1 cluster names."""
    vc = client.get("/api/catalogue/v5/value-chain?sv=CL").json()
    assert vc["source"] == "catalogue_vc_mapping_inherited"
    assert vc["inherited_from"] == "v7"
    assert len(vc["chains"]) == 1 and vc["chains"][0]["sv"] == "CL"
    names = [c["name"] for c in vc["clusters"]]
    assert names and all(not n.startswith("VCC-") for n in names)  # real names, not codes
    # the chain is the real CL pipeline (a market-intelligence-style lead stage), not L1 clusters
    assert any("MARKET" in n.upper() or "BUSINESS DEVELOPMENT" in n.upper() for n in names)
    # verbose "Indirect: …" stages are merged into one clean stage, never shown raw
    assert not any(n.lower().startswith("indirect") and n != "Indirect linkages" for n in names)


@needs_db
def test_v5_all_sv_consolidates_inherited_real_stages(client: TestClient) -> None:
    """A mapping-less v5 'All SV' consolidates the REAL named stages INHERITED from v7 (not a
    derived/L1 chain) — one chain, no subvert tag, P1C1.1.1 reads MARKET + BACK OFFICE OPS."""
    allv = client.get("/api/catalogue/v5/value-chain").json()
    assert allv["source"] == "catalogue_vc_mapping_inherited" and allv["inherited_from"] == "v7"
    assert allv["sv"] == "all" and allv["resolved_sv"] == "" and len(allv["chains"]) == 1
    all_names = [c["name"] for c in allv["clusters"]]
    assert "MARKET" in all_names  # real stage names, inherited from v7
    p_stages = [
        c["name"] for c in allv["clusters"] if any(s["id"] == "P1C1.1.1" for s in c["subcaps"])
    ]
    assert p_stages == ["MARKET", "BACK OFFICE OPS, COMPLIANCE & PLATFORM"]
    assert allv["subverticals"]  # the picker still lists every subvertical


@needs_db
def test_v5_heatmap_lenses_inherit_enrichment(client: TestClient) -> None:
    """The value-chain + vendor heatmap lenses INHERIT v7's enrichment when v5 has none of its own,
    so Mission Control renders automatically — no 'run carry-forward' empty state, no button."""
    for lens in ("value-chain", "vendor"):
        h = client.get(f"/api/catalogue/v5/heatmap?lens={lens}").json()
        assert len(h["rows"]) > 0, f"{lens} lens should inherit and render, not be empty"
        assert sum(r["total"] for r in h["rows"]) > 0


@needs_db
def test_v5_b_group_pages_inherit_enrichment(client: TestClient) -> None:
    """The B-group catalogue tools — Platform catalog, Use case explorer, Knowledge graph — INHERIT
    v7's enrichment when v5 has none of its own, so they're never empty (no re-provision needed)."""
    plats = client.get("/api/catalogue/v5/platforms").json()
    assert len(plats) > 50 and any(p["subcap_count"] > 0 for p in plats)  # inherited platforms
    vendors = client.get("/api/catalogue/v5/vendors").json()
    assert len(vendors) > 10
    ucs = client.get("/api/catalogue/v5/use-cases").json()
    assert ucs["total"] > 100 and ucs["items"]  # inherited use cases
    # vendor delivery totals (new) + a platform's top use-case archetypes (new) + the cell drilldown
    from urllib.parse import quote

    assert any(v.get("stories", 0) > 0 for v in vendors)
    pid = next(p["l3_id"] for p in plats if p["subcap_count"] > 0)
    det = client.get(f"/api/catalogue/v5/platforms/{pid}").json()
    assert isinstance(det.get("use_cases"), list)
    vname = quote(max(vendors, key=lambda v: v["subcap_count"])["vendor"])
    cell = client.get(f"/api/catalogue/v5/vendors/{vname}/cell?pillar=P4").json()
    assert isinstance(cell, list)
    # KG Layer A for a real subcap: platform/sibling nodes + edges inherited
    kg = client.get("/api/catalogue/v5/kg?subcap=P4C1.1.1").json()
    assert len(kg["nodes"]) > 1 and kg["edges"]  # subcap + inherited platform/offering nodes
    conns = client.get("/api/catalogue/v5/subcaps/P4C1.1.1/connections").json()
    assert conns["siblings"]  # shared-platform siblings inherited


@needs_db
def test_v5_sv_count_inherits_full_tier_set(client: TestClient) -> None:
    """The mission-control SV count must span ALL tiers (T1 + T2), not just delivered subcaps. A
    mapping-less v5 inherits the reference's full subcap_vcc membership, so the count is the whole
    chain (hundreds of subcaps), not the handful with delivery."""
    s = client.get("/api/catalogue/v5/summary?sv=CL").json()
    assert s["total_subcaps"] > 500  # full T1+T2 chain, not the ~100 delivered (delivery-only bug)
    assert sum(p["subcap_count"] for p in s["pillars"]) == s["total_subcaps"]
    none = client.get("/api/catalogue/v5/summary?sv=ZZ").json()
    assert none["total_subcaps"] == 0  # an unknown subvertical still scopes to nothing


@needs_db
def test_v5_without_vc_mapping_still_loads_subcaps(client: TestClient) -> None:
    """Mission-control tiles + workbench tree must NOT collapse to zero when there is no VC mapping;
    the SV scope falls back to actual delivery (story_sv_code)."""
    s = client.get("/api/catalogue/v5/summary?sv=CL").json()
    assert s["total_subcaps"] > 0  # delivery-scoped, not a subcap_vcc zero
    assert sum(p["subcap_count"] for p in s["pillars"]) == s["total_subcaps"]
    tree = client.get("/api/catalogue/v5/subcaps?sv=CL").json()
    assert len(tree) > 0
    # an unknown subvertical still scopes to nothing (no false membership)
    none = client.get("/api/catalogue/v5/summary?sv=ZZ").json()
    assert none["total_subcaps"] == 0


def test_lead_stage_key_folds_overlapping_stages() -> None:
    """Pure: overlapping stage names key to the same lead token (fold), distinct ones don't."""
    from app.services.value_chain import lead_stage_key

    assert lead_stage_key("MARKET") == "market"
    assert lead_stage_key("MARKET INTELLIGENCE & VERTICAL TARGETING") == "market"
    assert lead_stage_key("AG MARKET INTELLIGENCE & SEASONAL FORECASTING") == "market"
    assert lead_stage_key("AGENCY MGMT SYSTEM & DATA") == "agency"  # distinct -> own key
    assert lead_stage_key("MARKETING & LEAD GENERATION") == "marketing"  # not 'market'


@needs_db
def test_v7_value_chain_includes_canonical_rollup(client: TestClient) -> None:
    """The atlas response carries the 8-stage canonical Rollup + per-stage delivery (stories/pillars
    /top) for Pipeline/Radial, plus a real HIGH/MEDIUM/LOW delivery-confidence split per stage."""
    vc = client.get("/api/catalogue/v7/value-chain").json()
    roll = vc["rollup"]
    assert [s["code"] for s in roll] == [f"VCC-{i:02d}" for i in range(1, 9)]
    assert sum(s["stories"] for s in roll) > 0  # real Jira delivery, aggregated per bucket
    assert sum(s["projects"] for s in roll) > 0
    # delivery-confidence split is grounded: bands sum to at most the stage's distinct stories
    assert all(set(s["confidence"]) == {"HIGH", "MEDIUM", "LOW"} for s in roll)
    assert all(sum(s["confidence"].values()) <= s["stories"] for s in roll)
    assert sum(sum(s["confidence"].values()) for s in roll) > 0
    # per-stage delivery enrichment on the Pipeline clusters
    cl = vc["clusters"]
    assert any(c.get("stories", 0) > 0 for c in cl)
    assert all("pillars" in c and "top" in c for c in cl)
    top_stage = max(cl, key=lambda c: c.get("stories", 0))
    assert top_stage["top"] and top_stage["top"][0]["n"] >= top_stage["top"][-1]["n"]
