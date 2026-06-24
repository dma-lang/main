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
            # simulate v5 provisioned BEFORE the cascade: no VC mapping AND no platform enrichment
            # of its own, so the atlas + the value-chain/vendor heatmap lenses must INHERIT v7.
            await conn.execute(text("DELETE FROM cat_v5.subcap_vcc"))
            await conn.execute(text("DELETE FROM cat_v5.value_chain_cluster"))
            await conn.execute(text("DELETE FROM cat_v5.subcap_platform"))
        await db.dispose_engine()

    async def _teardown() -> None:
        db.init_engine()
        engine = db.get_engine()
        assert engine is not None
        async with engine.begin() as conn:
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
def test_v5_all_sv_is_one_consolidated_chain(client: TestClient) -> None:
    """'All SV' CONSOLIDATES the whole catalogue into high-level stages — ONE chain, no subvert tag,
    no single industry's stages (the user's "no retail banking, consolidate all")."""
    allv = client.get("/api/catalogue/v5/value-chain").json()
    assert allv["source"] == "derived_consolidated"
    assert allv["sv"] == "all" and allv["resolved_sv"] == "" and len(allv["chains"]) == 1
    assert allv["chains"][0]["sv"] == "all"
    all_names = [c["name"] for c in allv["clusters"]]
    assert 8 <= len(all_names) <= 40  # a clean, consolidated MECE pipeline (not 200+ granular)
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
