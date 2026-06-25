"""R2 Phase B (hermetic): the shared embedding space, dense retrieval, and the AI semantic KG
Layer-B — all exercised with the deterministic token-hash stub (no spend).

The embeddings job fills ``cat_<v>.subcap.embedding``; dense retrieval ranks by pgvector cosine; the
semantic builder proposes ``semantically_similar`` ``pending_edge``s (cosine >= floor), gated by the
SAME Change-Flags flow as the structural layer. To make a semantic edge deterministic at the
PRODUCTION 0.85 floor we force one cross-capability pair to share an embedding (token-hash cosine
of genuinely-distinct subcaps is honestly conservative), then propose with structural mins disabled
so every proposal is semantic.
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
from app.services import embeddings as embeddings_svc
from app.services import kg as kg_svc
from app.services import provision

needs_db = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"), reason="DATABASE_URL not set (DB-backed test)"
)
_A, _B = "P1C1.1.1", "P4C1.1.1"  # two real v7 subcaps in different pillars (distinct capabilities)


@pytest.fixture(scope="module")
def provisioned() -> Iterator[None]:
    from app import migrate

    migrate.run()

    async def _setup() -> None:
        db.init_engine()
        await provision.bring_version_online("v7")
        await embeddings_svc.build_embeddings("v7")
        engine = db.get_engine()
        assert engine is not None
        async with engine.begin() as conn:
            # force a cross-capability identical-embedding pair -> cosine 1.0 -> a semantic edge is
            # proposed deterministically even at the production 0.85 floor.
            await conn.execute(
                text(
                    "UPDATE cat_v7.subcap SET embedding = "
                    "(SELECT embedding FROM cat_v7.subcap WHERE subcap_id = :a) "
                    "WHERE subcap_id = :b"
                ),
                {"a": _A, "b": _B},
            )
        # structural mins disabled (999) so every proposal here is the semantic kind
        await kg_svc.propose_structural_edges("v7", shares_platform_min=999, shares_feature_min=999)
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
def test_embeddings_populated_and_idempotent(client: TestClient) -> None:
    """Every subcap is embedded; re-running the build is a no-op (idempotent on NULL embedding)."""
    with _sync().connect() as c:
        nulls = c.execute(
            text("SELECT count(*) FROM cat_v7.subcap WHERE embedding IS NULL")
        ).scalar_one()
        filled = c.execute(
            text("SELECT count(*) FROM cat_v7.subcap WHERE embedding IS NOT NULL")
        ).scalar_one()
    assert nulls == 0 and filled > 800
    again = client.post("/api/admin/embeddings/build/v7").json()
    assert again["embedded"] == 0


@needs_db
def test_dense_retrieval_ranks_by_cosine(client: TestClient) -> None:
    """The stored vectors + HNSW cosine work: querying with a subcap's own embedding ranks it #1."""
    with _sync().connect() as c:
        top = (
            c.execute(
                text(
                    "SELECT s.subcap_id, 1 - (s.embedding <=> q.embedding) AS cosine "
                    "FROM cat_v7.subcap s, "
                    "(SELECT embedding FROM cat_v7.subcap WHERE subcap_id = :x) q "
                    "WHERE s.embedding IS NOT NULL "
                    "ORDER BY s.embedding <=> q.embedding ASC, s.subcap_id LIMIT 1"
                ),
                {"x": "P3C1.1.1"},
            )
            .mappings()
            .first()
        )
    assert top is not None and top["subcap_id"] == "P3C1.1.1"
    assert round(float(top["cosine"]), 3) == 1.0


@needs_db
def test_semantic_edges_are_gated_proposals(client: TestClient) -> None:
    """The forced cross-capability pair surfaces as a gated ``semantically_similar`` proposal
    carrying its cosine, and every queued semantic proposal passed G1-G8."""
    with _sync().connect() as c:
        sem = c.execute(
            text(
                "SELECT count(*) FROM control.change_flag "
                "WHERE kind = 'kg_edge_proposal' AND detail->>'kind_edge' = 'semantically_similar'"
            )
        ).scalar_one()
        passed = c.execute(
            text(
                "SELECT count(*) FROM control.change_flag cf "
                "JOIN control.validation_gate_run g ON g.chain_id = cf.chain_id "
                "WHERE cf.kind = 'kg_edge_proposal' "
                "AND cf.detail->>'kind_edge' = 'semantically_similar' AND g.verdict = 'pass'"
            )
        ).scalar_one()
        forced = c.execute(
            text(
                "SELECT (detail->>'cosine')::float AS cosine FROM control.change_flag "
                "WHERE kind = 'kg_edge_proposal' AND target_ref = :ref"
            ),
            {"ref": f"{_A}>{_B}:ss"},
        ).scalar_one()
    assert sem > 0 and passed == sem  # nothing ungated leaks
    assert round(forced, 2) == 1.0  # the forced identical-embedding pair -> cosine 1.0


@needs_db
def test_semantic_edge_approve_promotes(client: TestClient) -> None:
    """Approving a semantic proposal promotes its pending_edge to an accepted Layer-B kg_edge."""
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
            text("SELECT count(*) FROM control.kg_edge WHERE version_id = 'v7'")
        ).scalar_one()
    assert st == "accepted" and edges > 0
