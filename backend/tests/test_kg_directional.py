"""R6 (hermetic, DB-backed + pure unit): NLP DIRECTIONAL relationship engine.

The engine reads two subcaps' descriptions into a TYPED, DIRECTIONAL relation (one enables /
precedes / depends_on / affects the other), DUAL-verifies it — an adversarial refutation AND
corroboration against the Jira delivery corpus — and queues the survivors as gated, dashed
directional ``pending_edge``s. The pure-unit tests pin the deterministic stub taxonomy + both halves
of the verification (a relation the corpus contradicts, and a 'none'/weak one the adversary refutes,
are DROPPED). The DB test proves the whole pipeline: provision + carry v7, mine directional edges,
every survivor carries the full trust envelope (relation + direction + rationale + keywords + a
passing gate run), approval promotes a DIRECTIONAL ``kg_edge``, and a re-run is idempotent. Hermetic
= deterministic + zero spend.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import Engine, create_engine, text

from app import db
from app.intelligence.gemini import Gemini, RelationshipInference
from app.services import embeddings as emb_svc
from app.services import kg as kg_svc
from app.services import provision
from app.services import stories as story_svc

needs_db = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"), reason="DATABASE_URL not set (DB-backed test)"
)


# ── pure unit: deterministic stub taxonomy + dual verification (no DB, no spend) ────────────────
def test_infer_relationship_taxonomy_and_direction() -> None:
    """The deterministic stub reads the grounded signals into the right typed, directional relation:
    value-chain order -> precedes (directed by the ordinals), co-delivery -> complements,
    near-duplicate cosine -> alternative_to (symmetric), shared platforms -> depends_on."""
    g = Gemini()

    async def _infer(sig: dict[str, object]) -> RelationshipInference:
        return await g.infer_relationship(sig)

    precedes = asyncio.run(
        _infer({"a_id": "P2C1.1", "b_id": "P4C2.2", "a_stage_ord": 1, "b_stage_ord": 5})
    )
    assert precedes.relation == "precedes" and precedes.direction == "a_to_b"
    # b earlier than a -> the arrow flips
    flip = asyncio.run(
        _infer({"a_id": "P2C1.1", "b_id": "P4C2.2", "a_stage_ord": 6, "b_stage_ord": 2})
    )
    assert flip.relation == "precedes" and flip.direction == "b_to_a"
    comp = asyncio.run(_infer({"a_id": "P2C1.1", "b_id": "P4C2.2", "lift": 8.0}))
    assert comp.relation == "complements" and comp.direction == "bidirectional"
    alt = asyncio.run(_infer({"a_id": "P2C1.1", "b_id": "P4C2.2", "cosine": 0.95}))
    assert alt.relation == "alternative_to" and alt.direction == "bidirectional"
    dep = asyncio.run(_infer({"a_id": "P2C1.1", "b_id": "P4C2.2", "shared_platforms": 3}))
    assert dep.relation == "depends_on" and dep.direction in ("a_to_b", "b_to_a")
    # cross-pillar (P2 vs P4) is a HYPOTHESIS; keywords are surfaced
    kw = asyncio.run(
        _infer(
            {"a_id": "P2C1.1", "b_id": "P4C2.2", "lift": 8.0, "shared_keywords": ["case", "data"]}
        )
    )
    assert kw.claim_label == "HYPOTHESIS" and kw.keywords == ("case", "data")


def test_adversary_refutes_none_and_weak() -> None:
    """The hermetic adversary refutes a 'none' relation and a low-confidence one, upholds a strong
    one — the semantic half of the dual verification."""
    g = Gemini()
    strong = RelationshipInference("precedes", "a_to_b", 0.6, "why", (), "INFERENCE", "stub", 0.0)
    weak = RelationshipInference("affects", "a_to_b", 0.2, "why", (), "INFERENCE", "stub", 0.0)
    none = RelationshipInference("none", "a_to_b", 0.0, "why", (), "INFERENCE", "stub", 0.0)
    assert asyncio.run(g.verify_relationship(strong, {})).refuted is False
    assert asyncio.run(g.verify_relationship(weak, {})).refuted is True
    assert asyncio.run(g.verify_relationship(none, {})).refuted is True


def test_corroborate_drops_unsupported() -> None:
    """The corpus half drops a relation the delivery data does not support: 'precedes' with no
    value-chain order, 'complements' with no co-delivery — while a corroborated one survives."""
    # precedes needs a value-chain ordering
    ok, _ = kg_svc._corroborate("precedes", "a_to_b", "P2C1.1", "P4C2.2", {}, 1.5)
    assert ok is False
    ok, _ = kg_svc._corroborate(
        "precedes", "a_to_b", "P2C1.1", "P4C2.2", {"a_stage_ord": 1, "b_stage_ord": 5}, 1.5
    )
    assert ok is True  # a before b matches the a_to_b direction
    ok, _ = kg_svc._corroborate(
        "precedes", "a_to_b", "P2C1.1", "P4C2.2", {"a_stage_ord": 9, "b_stage_ord": 2}, 1.5
    )
    assert ok is False  # order contradicts the claimed direction
    # depends_on / complements need co-delivery
    assert kg_svc._corroborate("complements", "bidirectional", "a", "b", {}, 1.5)[0] is False
    assert (
        kg_svc._corroborate("complements", "bidirectional", "a", "b", {"lift": 3.0}, 1.5)[0] is True
    )


def test_directional_strength_blends_signals() -> None:
    """Strength blends NLP confidence, adversary survival, and corpus corroboration; a refuted or
    uncorroborated edge scores strictly lower."""
    full = kg_svc._directional_strength(0.9, 0.0, True)
    no_corrob = kg_svc._directional_strength(0.9, 0.0, False)
    refuted = kg_svc._directional_strength(0.9, 1.0, True)
    assert 0.0 <= refuted < no_corrob < full <= 0.999


# ── DB-backed: the whole gated directional pipeline ─────────────────────────────────────────────
@pytest.fixture(scope="module")
def provisioned() -> Iterator[None]:
    from app import migrate

    migrate.run()

    async def _setup() -> None:
        db.init_engine()
        await provision.bring_version_online("v7")
        await story_svc.carry_forward("v7")
        await emb_svc.build_embeddings("v7")  # semantic candidate layer (hermetic stub vectors)
        await kg_svc.propose_directional_edges("v7")
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


def _sync() -> Engine:
    return create_engine(os.environ["DATABASE_URL"].replace("+asyncpg", "+psycopg"))


@needs_db
def test_directional_edges_are_typed_gated_and_promotable(provisioned: None) -> None:
    """Every proposed directional edge is TYPED + DIRECTED, carries the full trust envelope (a
    passing gate run + reasoning chain + rationale + keywords), the pending_edge stores relation +
    direction, and approving it promotes a DIRECTIONAL kg_edge that keeps its relation/direction."""
    eng = _sync()
    with eng.connect() as conn:
        n = conn.execute(
            text(
                "SELECT count(*) FROM control.change_flag "
                "WHERE kind = 'kg_edge_proposal' AND detail ? 'relation'"
            )
        ).scalar()
        assert (n or 0) > 0  # the engine mined real directional relationships

        # every directional proposal is gated (a validation_gate_run) with relation + direction
        rows = (
            conn.execute(
                text(
                    "SELECT cf.detail->>'relation' rel, cf.detail->>'direction' dir, "
                    "cf.detail->>'rationale' rat, cf.detail->'keywords' kw, vg.verdict "
                    "FROM control.change_flag cf "
                    "JOIN control.validation_gate_run vg ON vg.chain_id = cf.chain_id "
                    "WHERE cf.kind = 'kg_edge_proposal' AND cf.detail ? 'relation'"
                )
            )
            .mappings()
            .all()
        )
        assert rows and all(r["verdict"] == "pass" for r in rows)  # nothing shown ungated
        rels = {r["rel"] for r in rows}
        assert rels <= set(kg_svc._REL_SHORT)  # only the R6 taxonomy
        assert all(r["dir"] in ("forward", "bidirectional") for r in rows)
        assert all(r["rat"] for r in rows)  # a grounded rationale on every edge

        # the pending_edge carries relation + direction (so a promoted edge stays directional)
        pe = (
            conn.execute(
                text(
                    "SELECT pending_id, relation, direction FROM control.pending_edge "
                    "WHERE relation IS NOT NULL LIMIT 1"
                )
            )
            .mappings()
            .first()
        )
        assert pe is not None and pe["relation"] and pe["direction"]

    # approve one -> a directional kg_edge with relation + direction preserved
    async def _approve(pending_id: str) -> bool:
        db.init_engine()
        engine = db.require_engine()
        async with engine.begin() as c:
            ok = await kg_svc.promote_pending_edge(c, pending_id)
        await db.dispose_engine()
        return ok

    assert asyncio.run(_approve(str(pe["pending_id"]))) is True
    with _sync().connect() as conn:
        edge = (
            conn.execute(
                text(
                    "SELECT relation, direction, layer FROM control.kg_edge "
                    "WHERE relation IS NOT NULL LIMIT 1"
                )
            )
            .mappings()
            .first()
        )
        assert edge is not None and edge["relation"] and edge["layer"] == "B_proposed"


@needs_db
def test_directional_mining_is_idempotent(provisioned: None) -> None:
    """A second directional scan over the same corpus proposes nothing new (pair-level idempotency),
    so the weekly schedule / a redeploy never duplicates edges."""

    async def _rescan() -> dict[str, Any]:
        db.init_engine()
        res = await kg_svc.propose_directional_edges("v7")
        await db.dispose_engine()
        return res

    res = asyncio.run(_rescan())
    assert res["created"] == 0 and int(res["already"]) > 0
