"""R7 cross-version propagation + provision-time inheritance gate — save it where it BELONGS.

DB-backed over a provisioned v7 (source) + v5 (target). Proves the escalation the user asked for:
an approved use case AUTO-SAVES into another version when the deep-NLP necessity gate says it fits
there (a UC-PROP row + an audit row), is SKIPPED where it does not (a duplicate / poor fit / no
home), is idempotent (the deterministic id + the cached verdict make a re-run a no-op), and that the
provision-time inheritance gate DROPS an irrelevant use case copied onto a drifted subcap. Finally
the change-flags approve endpoint carries the ``propagated`` summary end-to-end.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app import db
from app.main import create_app
from app.services import enrichment_propagation, provision
from app.services import stories as story_svc

needs_db = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"), reason="DATABASE_URL not set (DB-backed test)"
)


@pytest.fixture(scope="module")
def two_versions() -> Iterator[None]:
    from app import migrate

    migrate.run()

    async def _setup() -> None:
        db.init_engine()
        engine = db.get_engine()
        assert engine is not None
        async with engine.begin() as conn:
            # audit_log.actor is a FK to control.users(uid); the direct propagate calls audit as
            # this uid, so it must be a real user (the API path uses the authenticated uid).
            await conn.execute(
                text(
                    "INSERT INTO control.users (uid, email, is_admin) "
                    "VALUES ('tester', 'tester@zennify.com', true) ON CONFLICT (uid) DO NOTHING"
                )
            )
        await provision.bring_version_online("v7")
        await provision.bring_version_online("v5")
        await story_svc.carry_forward("v7")  # so the use-case-gap detector has delivery to mine
        await db.dispose_engine()

    async def _teardown() -> None:
        db.init_engine()
        engine = db.get_engine()
        assert engine is not None
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM control.enrichment_relevance"))
            await conn.execute(
                text("DELETE FROM control.audit_log WHERE action LIKE 'change_flag%'")
            )
            await conn.execute(text("DELETE FROM control.change_flag"))
            # KG proposals (carry_forward re-mines) FK reasoning_chain + kg_node -> drop first
            await conn.execute(text("DELETE FROM control.kg_edge"))
            await conn.execute(text("DELETE FROM control.pending_edge"))
            await conn.execute(text("DELETE FROM control.validation_gate_run"))
            await conn.execute(text("DELETE FROM control.citation"))
            await conn.execute(text("DELETE FROM control.reasoning_step"))
            await conn.execute(text("DELETE FROM control.reasoning_chain"))
            await conn.execute(text("DELETE FROM control.kg_node"))
            await conn.execute(text("DELETE FROM control.evidence_item WHERE kind = 'catalogue'"))
            await conn.execute(text("DELETE FROM control.story_use_case_carry"))
            await conn.execute(text("DELETE FROM control.story_subcap_carry"))
            await conn.execute(text("DELETE FROM control.story"))
            for s in ("v5", "v7"):
                await conn.execute(text(f"DROP SCHEMA IF EXISTS cat_{s} CASCADE"))
            await conn.execute(
                text(
                    "DELETE FROM control.version_crosswalk "
                    "WHERE from_version IN ('v5', 'v7') OR to_version IN ('v5', 'v7')"
                )
            )
            # ingest_run FKs catalogue_version -> clear before deleting the version rows
            await conn.execute(
                text("DELETE FROM control.ingest_run WHERE version_id IN ('v5', 'v7')")
            )
            await conn.execute(
                text("DELETE FROM control.catalogue_version WHERE version_id IN ('v5', 'v7')")
            )
            await conn.execute(text("DELETE FROM control.users WHERE uid = 'tester'"))
        await db.dispose_engine()

    asyncio.run(_setup())
    yield
    asyncio.run(_teardown())


def _run[T](op: Callable[[], Awaitable[T]]) -> T:
    async def _wrap() -> T:
        db.init_engine()
        try:
            return await op()
        finally:
            await db.dispose_engine()

    return asyncio.run(_wrap())


async def _shared_subcap(offset: int) -> dict[str, Any]:
    """A subcap present in BOTH v5 and v7 (the shared core -> an exact-id map), by a stable offset
    so each test operates on its own subcap and never trips over another's mutations."""
    engine = db.require_engine()
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT s7.subcap_id, s7.name, coalesce(s7.description, '') "
                    "FROM cat_v7.subcap s7 JOIN cat_v5.subcap s5 USING (subcap_id) "
                    "ORDER BY s7.subcap_id OFFSET :k LIMIT 1"
                ),
                {"k": offset},
            )
        ).first()
    assert row is not None, "expected a subcap shared by v5 and v7"
    return {"id": str(row[0]), "name": str(row[1]), "desc": str(row[2])}


async def _clear_v5_use_cases(subcap_id: str) -> None:
    engine = db.require_engine()
    async with engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM cat_v5.use_case WHERE subcap_id = :s"), {"s": subcap_id}
        )


@needs_db
def test_propagate_saves_to_a_relevant_version(two_versions: None) -> None:
    """An approved use case that clearly fits its subcap in v5 (overlap cleared) AUTO-SAVES there:
    a UC-PROP row under the mapped subcap + an immutable propagate audit row."""
    sub = _run(lambda: _shared_subcap(0))
    _run(lambda: _clear_v5_use_cases(sub["id"]))

    async def _op() -> dict[str, Any]:
        engine = db.require_engine()
        async with engine.begin() as conn:
            return await enrichment_propagation.propagate_use_case(
                conn,
                source_version="v7",
                source_schema="cat_v7",
                subcap_id=sub["id"],
                name=sub["name"],
                description=sub["desc"],
                archetype=None,
                use_case_id="UC-TEST-SAVE",
                actor="tester",
            )

    result = _run(_op)
    assert [s["version"] for s in result["saved"]] == ["v5"]
    saved_id = result["saved"][0]["use_case_id"]

    async def _check() -> tuple[int, int]:
        engine = db.require_engine()
        async with engine.connect() as conn:
            uc = (
                await conn.execute(
                    text("SELECT count(*) FROM cat_v5.use_case WHERE use_case_id = :i"),
                    {"i": saved_id},
                )
            ).scalar()
            au = (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM control.audit_log "
                        "WHERE action = 'change_flag.propagate' AND target_ref = :t"
                    ),
                    {"t": sub["id"]},
                )
            ).scalar()
        return int(uc or 0), int(au or 0)

    uc_n, audit_n = _run(_check)
    assert uc_n == 1 and audit_n >= 1


@needs_db
def test_propagate_skips_an_irrelevant_version(two_versions: None) -> None:
    """A use case whose text is a poor fit for the subcap is judged NOT relevant in v5 and SKIPPED —
    nothing is written (never enrich the wrong things)."""
    sub = _run(lambda: _shared_subcap(1))

    async def _op() -> dict[str, Any]:
        engine = db.require_engine()
        async with engine.begin() as conn:
            return await enrichment_propagation.propagate_use_case(
                conn,
                source_version="v7",
                source_schema="cat_v7",
                subcap_id=sub["id"],
                name="Zzqx Wibble",
                description="frobnicate quux garble snorf",
                archetype=None,
                use_case_id="UC-TEST-SKIP",
                actor="tester",
            )

    result = _run(_op)
    assert result["saved"] == []
    assert [s["version"] for s in result["skipped"]] == ["v5"]

    async def _count() -> int:
        engine = db.require_engine()
        async with engine.connect() as conn:
            n = (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM cat_v5.use_case "
                        "WHERE subcap_id = :s AND use_case_id LIKE 'UC-PROP-%'"
                    ),
                    {"s": sub["id"]},
                )
            ).scalar()
        return int(n or 0)

    assert _run(_count) == 0  # the skip wrote nothing


@needs_db
def test_propagate_is_idempotent(two_versions: None) -> None:
    """Re-approving fans out the SAME deterministic id and reuses the cached verdict, so a second
    run inserts nothing new (ON CONFLICT DO NOTHING) — exactly one propagated row."""
    sub = _run(lambda: _shared_subcap(2))
    _run(lambda: _clear_v5_use_cases(sub["id"]))

    async def _propagate() -> dict[str, Any]:
        engine = db.require_engine()
        async with engine.begin() as conn:
            return await enrichment_propagation.propagate_use_case(
                conn,
                source_version="v7",
                source_schema="cat_v7",
                subcap_id=sub["id"],
                name=sub["name"],
                description=sub["desc"],
                archetype=None,
                use_case_id="UC-TEST-IDEM",
                actor="tester",
            )

    first = _run(_propagate)
    second = _run(_propagate)
    assert first["saved"] and second["saved"]  # relevant both times (cache preserves the verdict)

    async def _count() -> int:
        engine = db.require_engine()
        async with engine.connect() as conn:
            n = (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM cat_v5.use_case "
                        "WHERE subcap_id = :s AND use_case_id LIKE 'UC-PROP-%'"
                    ),
                    {"s": sub["id"]},
                )
            ).scalar()
        return int(n or 0)

    assert _run(_count) == 1  # the second fan-out added nothing


@needs_db
def test_propagate_skips_when_no_home(two_versions: None) -> None:
    """A subcap with no home in v5 (not shared, no crosswalk, no embedding match) is skipped with
    the reason recorded — the enrichment is never forced into a version it does not belong to."""

    async def _op() -> dict[str, Any]:
        engine = db.require_engine()
        async with engine.begin() as conn:
            return await enrichment_propagation.propagate_use_case(
                conn,
                source_version="v7",
                source_schema="cat_v7",
                subcap_id="ZZZ-ONLY-IN-SOURCE",
                name="Orphan use case",
                description="a subcap that has no home in v5",
                archetype=None,
                use_case_id="UC-TEST-ORPHAN",
                actor="tester",
            )

    result = _run(_op)
    assert result["saved"] == []
    assert result["skipped"] and result["skipped"][0]["version"] == "v5"
    assert "no home" in result["skipped"][0]["reason"].lower()


@needs_db
def test_inheritance_gate_drops_irrelevant_use_case(two_versions: None) -> None:
    """Workstream D: the provision-time gate DROPS a use case copied onto a drifted subcap that does
    not belong (a loose mapping importing an off-topic UC) and KEEPS the one that fits."""
    sub = _run(lambda: _shared_subcap(3))

    async def _seed_then_gate() -> int:
        engine = db.require_engine()
        async with engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM cat_v7.use_case WHERE subcap_id = :s"), {"s": sub["id"]}
            )
            await conn.execute(
                text(
                    "INSERT INTO cat_v7.use_case (use_case_id, subcap_id, archetype, name, "
                    "description, is_new) VALUES (:i, :s, '', :n, :d, true)"
                ),
                [
                    {
                        "i": "ZZ-IRREL",
                        "s": sub["id"],
                        "n": "zzqx wibble",
                        "d": "frobnicate quux garble snorf",
                    },
                    {"i": "ZZ-REL", "s": sub["id"], "n": sub["name"], "d": sub["desc"]},
                ],
            )
            # treat sub as a DRIFTED subcap so the gate evaluates its inherited use cases
            return await provision._gate_inherited_use_cases(conn, "cat_v7", "v7", {sub["id"]})

    dropped = _run(_seed_then_gate)
    assert dropped == 1  # only the irrelevant one is dropped

    async def _surviving() -> set[str]:
        engine = db.require_engine()
        async with engine.connect() as conn:
            rows = (
                await conn.execute(
                    text("SELECT use_case_id FROM cat_v7.use_case WHERE subcap_id = :s"),
                    {"s": sub["id"]},
                )
            ).all()
        return {str(r[0]) for r in rows}

    survivors = _run(_surviving)
    assert "ZZ-REL" in survivors and "ZZ-IRREL" not in survivors


@needs_db
def test_approve_use_case_gap_returns_propagated_summary(two_versions: None) -> None:
    """End-to-end: the change-flags approve endpoint carries the R7 ``propagated`` summary (saved +
    skipped across the other provisioned versions), so one approval visibly fans out."""

    async def _detect() -> dict[str, Any]:
        from app.services import use_case_gaps

        engine = db.require_engine()
        assert engine is not None  # detector opens its own connections via the shared engine
        return await use_case_gaps.detect_use_case_gaps("v7")

    _run(_detect)
    with TestClient(create_app()) as c:
        flags = c.get("/api/change-flags?status=open").json()["flags"]
        gap = next((f for f in flags if f["kind"] == "use_case_gap"), None)
        if gap is None:
            pytest.skip("no use-case-gap proposal in this corpus run")
        out = c.post(f"/api/change-flags/{gap['id']}/approve").json()
        assert out["resolved"] is True
        prop = out["propagated"]
        assert isinstance(prop, dict) and set(prop) == {"saved", "skipped"}
        assert isinstance(prop["saved"], list) and isinstance(prop["skipped"], list)
        # v5 is the only OTHER provisioned version -> it is accounted for exactly once
        assert len(prop["saved"]) + len(prop["skipped"]) == 1
