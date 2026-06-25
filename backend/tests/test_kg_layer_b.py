"""KG Layer B (R2 A2): deterministic STRUCTURAL edge proposals, gated + human-approved.

DB-backed, self-cleaning. ``propose_structural_edges`` clusters cross-capability subcaps that
co-occur on shared L3 platforms / personas into dashed ``pending_edge``s + Change-Flags proposals
(kind ``kg_edge_proposal``), each gated G1-G8. The KG endpoint surfaces them as Layer B (uuid nodes
resolved back to subcap ref_ids); approve promotes a pending_edge to an accepted ``kg_edge``, reject
marks it rejected. Nothing is written to the graph as fact ungated.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text

from app import db
from app.main import create_app
from app.services import kg as kg_svc
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
        await kg_svc.propose_structural_edges("v7")  # one scan -> proposals exist for every test
        await db.dispose_engine()

    async def _teardown() -> None:
        db.init_engine()
        engine = db.get_engine()
        assert engine is not None
        async with engine.begin() as conn:
            # FK-safe: kg_edge + pending_edge (-> kg_node, chain) first, then the chain group, then
            # kg_node, then evidence.
            await conn.execute(text("DELETE FROM control.kg_edge"))
            await conn.execute(text("DELETE FROM control.pending_edge"))
            await conn.execute(text("DELETE FROM control.change_flag"))
            await conn.execute(text("DELETE FROM control.citation"))
            await conn.execute(text("DELETE FROM control.validation_gate_run"))
            await conn.execute(text("DELETE FROM control.reasoning_step"))
            await conn.execute(text("DELETE FROM control.reasoning_chain"))
            await conn.execute(text("DELETE FROM control.kg_node"))
            await conn.execute(text("DELETE FROM control.evidence_item WHERE kind = 'catalogue'"))
            await conn.execute(
                text("DELETE FROM control.audit_log WHERE action LIKE 'change_flag%'")
            )
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
def test_kg_propose_is_gated_and_idempotent(client: TestClient) -> None:
    """Every proposal is a dashed pending_edge + a kg_node pair + a Change-Flags item that PASSED
    G1-G8; re-running the scan proposes nothing new (idempotent on the pair key)."""
    with _sync().connect() as c:
        pend = c.execute(
            text(
                "SELECT count(*) FROM control.pending_edge "
                "WHERE version_id='v7' AND status='pending'"
            )
        ).scalar_one()
        nodes = c.execute(
            text("SELECT count(*) FROM control.kg_node WHERE version_id='v7'")
        ).scalar_one()
        flags = c.execute(
            text("SELECT count(*) FROM control.change_flag WHERE kind='kg_edge_proposal'")
        ).scalar_one()
        passed = c.execute(
            text(
                "SELECT count(*) FROM control.change_flag cf "
                "JOIN control.validation_gate_run g ON g.chain_id = cf.chain_id "
                "WHERE cf.kind='kg_edge_proposal' AND g.verdict='pass'"
            )
        ).scalar_one()
    assert pend > 0 and nodes > 0 and flags > 0
    assert passed == flags  # every queued proposal passed the gates (nothing ungated leaks)
    again = client.post("/api/admin/kg/propose/v7").json()
    assert again["created"] == 0 and again["already"] > 0


@needs_db
def test_kg_endpoint_surfaces_pending_layer_b(client: TestClient) -> None:
    """The KG endpoint resolves the pending_edge kg_node uuids back to subcap ref_ids and adds the
    proposed neighbour node, so the dashed Layer-B edge connects two rendered nodes."""
    with _sync().connect() as c:
        row = (
            c.execute(
                text(
                    "SELECT fn.ref_id AS a, tn.ref_id AS b FROM control.pending_edge pe "
                    "JOIN control.kg_node fn ON fn.node_id = pe.from_node "
                    "JOIN control.kg_node tn ON tn.node_id = pe.to_node "
                    "WHERE pe.version_id='v7' AND pe.status='pending' LIMIT 1"
                )
            )
            .mappings()
            .first()
        )
    assert row is not None
    kg = client.get(f"/api/catalogue/v7/kg?subcap={row['a']}").json()
    layer_b = [e for e in kg["pending"] if e["layer"] == "B_proposed"]
    assert layer_b, "expected at least one Layer-B pending edge"
    ids = {n["id"] for n in kg["nodes"]}
    edge = next(e for e in layer_b if e["source"] == row["a"] and e["target"] == row["b"])
    assert edge["source"] in ids and edge["target"] in ids  # both endpoints are drawn nodes


@needs_db
def test_kg_approve_promotes_to_kg_edge(client: TestClient) -> None:
    """Approving a proposal re-gates, promotes its pending_edge to 'accepted', and materialises a
    real (still Layer-B) kg_edge — the human-confirmed structural relationship."""
    flags = client.get("/api/change-flags?status=open").json()["flags"]
    f = next(x for x in flags if x["kind"] == "kg_edge_proposal")
    approved = client.post(f"/api/change-flags/{f['id']}/approve").json()
    assert approved["resolved"] is True and approved["status"] == "approved"
    with _sync().connect() as c:
        st = c.execute(
            text(
                "SELECT pe.status FROM control.change_flag cf "
                "JOIN control.pending_edge pe ON pe.pending_id = (cf.detail->>'pending_id')::uuid "
                "WHERE cf.target_ref = :t"
            ),
            {"t": f["target"]},
        ).scalar_one()
        edges = c.execute(
            text(
                "SELECT count(*) FROM control.kg_edge "
                "WHERE version_id='v7' AND layer='B_proposed'"
            )
        ).scalar_one()
    assert st == "accepted" and edges > 0


@needs_db
def test_kg_reject_marks_pending_rejected(client: TestClient) -> None:
    """Rejecting a proposal (reason required) marks its pending_edge 'rejected' — never written."""
    flags = client.get("/api/change-flags?status=open").json()["flags"]
    f = next(x for x in flags if x["kind"] == "kg_edge_proposal")
    rejected = client.post(
        f"/api/change-flags/{f['id']}/reject", json={"reason": "not a meaningful relationship"}
    ).json()
    assert rejected["status"] == "rejected"
    with _sync().connect() as c:
        st = c.execute(
            text(
                "SELECT pe.status FROM control.change_flag cf "
                "JOIN control.pending_edge pe ON pe.pending_id = (cf.detail->>'pending_id')::uuid "
                "WHERE cf.target_ref = :t"
            ),
            {"t": f["target"]},
        ).scalar_one()
    assert st == "rejected"
