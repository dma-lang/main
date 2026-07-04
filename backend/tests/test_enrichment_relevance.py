"""R7 deep-NLP necessity gate (services/enrichment_relevance) — is an enrichment relevant HERE?

Pure-unit coverage of the deterministic hermetic verdict (relevant iff it fits the subcap AND is not
a near-duplicate of an existing enrichment), plus a DB-backed run over a provisioned v7 proving the
gate: a mapped subcap that is ABSENT is no home (skip); a gibberish enrichment is a poor fit (skip);
a clear fit with the overlap cleared is relevant; and the verdict is CACHED on the content hash so a
re-run reuses it with no second decision (the "no repeat spend" idempotency the plan requires).
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable, Iterator
from typing import Any

import pytest
from sqlalchemy import text

from app import db
from app.intelligence.gemini import Gemini
from app.services import enrichment_relevance, provision

needs_db = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"), reason="DATABASE_URL not set (DB-backed test)"
)


# --------------------------------------------------------------------------- pure unit


def test_hermetic_stub_relevant_when_fits_and_distinct() -> None:
    """A high subcap fit that is distinct from the existing enrichments is RELEVANT."""
    v = Gemini._hermetic_infer_relevance(
        {"subcap_cosine": 0.9, "overlap_cosine": 0.1, "subcap_name": "Fraud detection"}
    )
    assert v.relevant is True and v.confidence > 0.5 and v.cost_usd == 0.0


def test_hermetic_stub_not_relevant_when_duplicate() -> None:
    """A near-duplicate (closer to an existing enrichment than to the subcap) is NOT relevant —
    the necessity check that stops us "enriching the wrong things"."""
    v = Gemini._hermetic_infer_relevance(
        {"subcap_cosine": 0.5, "overlap_cosine": 0.8, "subcap_name": "Fraud detection"}
    )
    assert v.relevant is False


# --------------------------------------------------------------------------- DB-backed


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
            await conn.execute(text("DELETE FROM control.enrichment_relevance"))
            await conn.execute(text("DROP SCHEMA IF EXISTS cat_v7 CASCADE"))
            await conn.execute(
                text("DELETE FROM control.catalogue_version WHERE version_id = 'v7'")
            )
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


async def _a_subcap() -> dict[str, Any]:
    engine = db.require_engine()
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT subcap_id, name, coalesce(description, '') FROM cat_v7.subcap "
                    "ORDER BY subcap_id LIMIT 1"
                )
            )
        ).first()
    assert row is not None
    return {"id": str(row[0]), "name": str(row[1]), "desc": str(row[2])}


@needs_db
def test_absent_subcap_has_no_home(provisioned: None) -> None:
    """A mapped subcap that does not exist in the target version is no home for the enrichment —
    NOT relevant, decided by the prefilter with zero spend."""

    async def _op() -> Any:
        engine = db.require_engine()
        async with engine.begin() as conn:
            return await enrichment_relevance.relevance(
                conn,
                kind="use_case",
                enrichment_key="k-absent",
                enrichment_text="Anything at all",
                target_version="v7",
                target_schema="cat_v7",
                target_subcap="ZZZ-NOT-A-REAL-SUBCAP",
            )

    v = _run(_op)
    assert v.relevant is False and v.model == "prefilter" and v.cost_usd == 0.0


@needs_db
def test_gibberish_is_a_poor_fit(provisioned: None) -> None:
    """An enrichment whose text shares nothing with the subcap sits below the fit floor -> the
    prefilter auto-rejects it (no model call), so a loose mapping never imports an off-topic UC."""
    sub = _run(_a_subcap)

    async def _op() -> Any:
        engine = db.require_engine()
        async with engine.begin() as conn:
            return await enrichment_relevance.relevance(
                conn,
                kind="use_case",
                enrichment_key="k-gib",
                enrichment_text="zzqx wibble frobnicate quux garble snorf",
                target_version="v7",
                target_schema="cat_v7",
                target_subcap=sub["id"],
            )

    v = _run(_op)
    assert v.relevant is False and v.model == "prefilter"


@needs_db
def test_clear_fit_with_no_overlap_is_relevant(provisioned: None) -> None:
    """The subcap's OWN text, with its existing use cases cleared (no overlap), is a clear fit ->
    relevant. Runs in a rolled-back transaction so the shared v7 use cases are left intact."""
    sub = _run(_a_subcap)

    async def _op() -> Any:
        engine = db.require_engine()
        async with engine.connect() as conn:
            trans = await conn.begin()
            await conn.execute(
                text("DELETE FROM cat_v7.use_case WHERE subcap_id = :s"), {"s": sub["id"]}
            )
            v = await enrichment_relevance.relevance(
                conn,
                kind="use_case",
                enrichment_key="k-fit",
                enrichment_text=f"{sub['name']} {sub['desc']}",
                target_version="v7",
                target_schema="cat_v7",
                target_subcap=sub["id"],
            )
            await trans.rollback()  # keep v7 untouched for the other tests
            return v

    v = _run(_op)
    assert v.relevant is True and v.confidence >= 0.5


@needs_db
def test_verdict_is_cached_and_reused(provisioned: None) -> None:
    """The verdict is persisted on the content hash and a second call with the SAME inputs reuses it
    — exactly one cache row, no second decision (the re-provision "no repeat spend" idempotency)."""
    sub = _run(_a_subcap)
    key = "k-cache"
    txt = "zzqx wibble frobnicate quux (cache probe)"

    async def _call() -> Any:
        engine = db.require_engine()
        async with engine.begin() as conn:
            return await enrichment_relevance.relevance(
                conn,
                kind="use_case",
                enrichment_key=key,
                enrichment_text=txt,
                target_version="v7",
                target_schema="cat_v7",
                target_subcap=sub["id"],
            )

    first = _run(_call)
    second = _run(_call)
    assert first.relevant == second.relevant and first.rationale == second.rationale

    async def _count() -> int:
        engine = db.require_engine()
        async with engine.connect() as conn:
            n = (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM control.enrichment_relevance "
                        "WHERE kind = 'use_case' AND enrichment_key = :k AND target_version = 'v7'"
                    ),
                    {"k": key},
                )
            ).scalar()
        return int(n or 0)

    assert _run(_count) == 1  # ON CONFLICT DO NOTHING -> a single cached decision
