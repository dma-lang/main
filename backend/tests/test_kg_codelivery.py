"""KG R5: co-delivery latent-relationship mining — the links the catalogue structure hides.

DB-backed, self-cleaning. After v7 is provisioned + the corpus carried, ``kg.discover_latent`` mines
cross-capability subcap pairs delivered together far more than chance (lift), ranks them by NOVELTY
(a strong but cross-pillar / not-already-structural pair rises), and the scan queues the most novel
as gated ``co_delivered`` proposals that pass G1-G8 and, on approval, materialise a ``kg_edge``
carrying the basis. The endpoints surface the weighted/explained edges + the "relationships you may
be missing" discovery. Nothing is fact ungated.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text

from app import db
from app.main import create_app
from app.services import kg as kg_svc
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
        await story_svc.carry_forward("v7")  # the corpus -> co-delivery baskets exist
        await kg_svc.propose_structural_edges("v7")  # one scan -> proposals exist for every test
        await db.dispose_engine()

    async def _teardown() -> None:
        db.init_engine()
        engine = db.get_engine()
        assert engine is not None
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM control.kg_edge"))
            await conn.execute(text("DELETE FROM control.pending_edge"))
            await conn.execute(text("DELETE FROM control.change_flag"))
            await conn.execute(text("DELETE FROM control.citation"))
            await conn.execute(text("DELETE FROM control.validation_gate_run"))
            await conn.execute(text("DELETE FROM control.reasoning_step"))
            await conn.execute(text("DELETE FROM control.reasoning_chain"))
            await conn.execute(text("DELETE FROM control.kg_node"))
            await conn.execute(text("DELETE FROM control.evidence_item WHERE kind = 'catalogue'"))
            await conn.execute(text("DELETE FROM control.story_use_case_carry"))
            await conn.execute(text("DELETE FROM control.story_subcap_carry"))
            await conn.execute(text("DELETE FROM control.story"))
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


def _sync() -> Engine:
    return create_engine(os.environ["DATABASE_URL"].replace("+asyncpg", "+psycopg"))


@needs_db
def test_discover_latent_mines_cross_pillar_above_chance(provisioned: None) -> None:
    """The latent signal is real: every discovered edge is a cross-capability co-delivery above the
    lift floor, grounded INFERENCE, novelty-ranked, and deterministic (same run -> same result)."""

    async def _run() -> list[dict[str, Any]]:
        db.init_engine()
        out = await kg_svc.discover_latent("v7", limit=20)
        await db.dispose_engine()
        return out

    edges = asyncio.run(_run())
    assert edges, "expected co-delivery latent edges from the carried corpus"
    assert all(e["kind"] == "co_delivered" for e in edges)
    assert all(float(e["lift"]) >= 1.5 for e in edges)  # above the configured chance floor
    assert all(e["claim_label"] == "INFERENCE" for e in edges)  # never a committed fact
    assert all(e["crosses"] in ("cross_pillar", "cross_capability") for e in edges)
    # novelty is the ranking, descending; the hidden cross-pillar links surface (the whole point)
    novs = [float(e["novelty"]) for e in edges]
    assert novs == sorted(novs, reverse=True)
    assert any(e["crosses"] == "cross_pillar" for e in edges[:5])
    assert all("co-delivered in" in str(e["basis"]) for e in edges)
    # deterministic: a second mine returns the identical ranked pairs
    again = asyncio.run(_run())
    assert [(e["source"], e["target"]) for e in again] == [
        (e["source"], e["target"]) for e in edges
    ]


@needs_db
def test_propose_codelivery_is_gated_and_idempotent(client: TestClient) -> None:
    """The scan queues ``co_delivered`` pending_edges that PASSED G1-G8 (nothing ungated), bounded
    by the proposal cap, and re-running proposes nothing new (idempotent on the pair key)."""
    with _sync().connect() as c:
        cd = c.execute(
            text(
                "SELECT count(*) FROM control.pending_edge "
                "WHERE version_id='v7' AND status='pending' AND kind='co_delivered'"
            )
        ).scalar_one()
        passed = c.execute(
            text(
                "SELECT count(*) FROM control.change_flag cf "
                "JOIN control.validation_gate_run g ON g.chain_id = cf.chain_id "
                "WHERE cf.kind='kg_edge_proposal' AND (cf.detail->>'kind_edge')='co_delivered' "
                "AND g.verdict='pass'"
            )
        ).scalar_one()
    assert 0 < cd <= 25  # bounded by _CO_DELIVERY_PROPOSAL_CAP
    assert passed == cd  # every co-delivery proposal passed the gates
    again = client.post("/api/admin/kg/propose/v7").json()
    assert again["created"] == 0 and again["already"] > 0


@needs_db
def test_codelivery_approve_carries_basis_onto_edge(client: TestClient) -> None:
    """Approving a co-delivery proposal promotes it to a kg_edge that still carries its basis + the
    cross-pillar flag, so the graph can explain WHY two subcaps are related after approval."""
    flags = client.get("/api/change-flags?status=open").json()["flags"]
    # the co-delivery proposal's target_ref is the pair key with the ':cd' suffix (_SHORT mapping)
    f = next(
        x
        for x in flags
        if x["kind"] == "kg_edge_proposal" and (x.get("target") or "").endswith(":cd")
    )
    approved = client.post(f"/api/change-flags/{f['id']}/approve").json()
    assert approved["resolved"] is True
    with _sync().connect() as c:
        row = (
            c.execute(
                text(
                    "SELECT ke.detail->>'basis' AS basis, ke.detail->>'crosses' AS crosses "
                    "FROM control.kg_edge ke WHERE ke.version_id='v7' AND ke.kind='co_delivered' "
                    "ORDER BY ke.weight DESC LIMIT 1"
                )
            )
            .mappings()
            .first()
        )
    assert row is not None
    assert "co-delivered in" in str(row["basis"])  # the why survives approval
    assert row["crosses"] in ("cross_pillar", "cross_capability")


@needs_db
def test_kg_endpoint_weighted_edges_and_latent_panel(client: TestClient) -> None:
    """The /kg endpoint returns edges with a unified strength + basis and a per-subcap ``latent``
    panel; /kg/discover returns the catalogue-wide discovery ranked by novelty."""
    # a subcap that actually has latent links
    with _sync().connect() as c:
        center = c.execute(
            text(
                "SELECT fn.ref_id FROM control.pending_edge pe "
                "JOIN control.kg_node fn ON fn.node_id = pe.from_node "
                "WHERE pe.version_id='v7' AND pe.kind='co_delivered' LIMIT 1"
            )
        ).scalar_one()
    kg = client.get(f"/api/catalogue/v7/kg?subcap={center}").json()
    assert "latent" in kg and isinstance(kg["latent"], list)
    assert kg["latent"], "expected the centre's hidden co-delivery links"
    assert all(le["kind"] == "co_delivered" and le["basis"] for le in kg["latent"])
    # at least one rendered edge carries a strength (thickness) + a basis (why)
    explained = [e for e in kg["edges"] if e.get("basis")]
    assert explained, "expected explained edges with a basis"
    # the pending co-delivery edge carries strength + the cross flag for the UI
    cd_pending = [e for e in kg["pending"] if e["kind"] == "co_delivered"]
    assert cd_pending and all(e.get("strength") is not None for e in cd_pending)

    disc = client.get("/api/catalogue/v7/kg/discover?limit=10").json()
    assert isinstance(disc, list) and disc
    novs = [d["novelty"] for d in disc]
    assert novs == sorted(novs, reverse=True)  # novelty-ranked discovery
    assert all(d["lift"] >= 1.5 for d in disc)
