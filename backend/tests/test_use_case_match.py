"""Story -> use-case matcher (services/use_case_match) — real per-use-case delivery, grounded.

Pure-unit coverage of the TF-IDF discrimination (a term common to all of a subcap's use cases is
dropped, so only discriminating terms match — nothing is fabricated), plus a DB-backed end-to-end
run proving the per-use-case counts DIFFER within a subcap (no longer the flat subcap total), never
exceed the subcap's delivery, a single-use-case subcap takes its whole delivery, the matcher is
idempotent, and the read endpoints expose the matched counts + the matched-stories drawer.
"""

from __future__ import annotations

import asyncio
import math
import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app import db
from app.main import create_app
from app.services import provision, use_case_match
from app.services import stories as story_svc

needs_db = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"), reason="DATABASE_URL not set (DB-backed test)"
)


# --------------------------------------------------------------------------- pure unit


def test_tfidf_drops_common_terms_keeps_discriminating() -> None:
    """A term shared by ALL of a subcap's use cases (df == n) gets weight 0 and is dropped, so only
    DISCRIMINATING terms drive the match — a story overlapping only the common word matches NEITHER
    (grounded: no fabricated attribution)."""
    docs = [
        use_case_match._tokens("case backlog dashboard executive view"),
        use_case_match._tokens("case triage routing sla queue"),
    ]
    vecs, norms = use_case_match._tfidf(docs)
    assert "case" not in vecs[0] and "case" not in vecs[1]  # common -> dropped
    assert "dashboard" in vecs[0] and "triage" in vecs[1]  # discriminating -> kept

    def score(textval: str, vec: dict[str, float], norm: float) -> float:
        s = use_case_match._tokens(textval)
        return use_case_match._score(s, math.sqrt(sum(n * n for n in s.values())), vec, norm)

    # a dashboard story scores the dashboard use case, not the triage one
    assert score("add an executive dashboard", vecs[0], norms[0]) > 0
    assert score("add an executive dashboard", vecs[1], norms[1]) == 0
    # a story sharing only the common term "case" matches NEITHER use case
    assert score("open a case", vecs[0], norms[0]) == 0
    assert score("open a case", vecs[1], norms[1]) == 0


# --------------------------------------------------------------------------- DB-backed


@pytest.fixture(scope="module")
def carried() -> Iterator[None]:
    from app import migrate

    migrate.run()

    async def _setup() -> None:
        db.init_engine()
        await provision.bring_version_online("v7")
        await story_svc.carry_forward("v7")  # runs the use-case matcher
        await db.dispose_engine()

    async def _teardown() -> None:
        db.init_engine()
        engine = db.get_engine()
        assert engine is not None
        async with engine.begin() as conn:
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


def _sync() -> object:
    return create_engine(os.environ["DATABASE_URL"].replace("+asyncpg", "+psycopg"))


@needs_db
def test_per_use_case_counts_differ_and_are_grounded(carried: None) -> None:
    """The whole point: within a subcap the per-use-case matched counts DIFFER (not the flat subcap
    total), and the matched stories never exceed the subcap's delivery (single best match,
    grounded — nothing fabricated)."""
    eng = _sync()
    with eng.connect() as conn:  # type: ignore[attr-defined]
        # a subcap whose use cases carry at least two DISTINCT matched counts (proves "not static")
        sub = conn.execute(
            text(
                "SELECT subcap_id FROM ("
                "  SELECT subcap_id, use_case_id, count(DISTINCT story_key) n "
                "  FROM control.story_use_case_link WHERE version_id = 'v7' "
                "  GROUP BY subcap_id, use_case_id) t "
                "GROUP BY subcap_id HAVING count(DISTINCT n) >= 2 LIMIT 1"
            )
        ).scalar()
        assert sub is not None, "expected a subcap with differentiated per-use-case counts"
        per_uc = [
            r[0]
            for r in conn.execute(
                text(
                    "SELECT count(DISTINCT story_key) FROM control.story_use_case_link "
                    "WHERE version_id = 'v7' AND subcap_id = :s GROUP BY use_case_id"
                ),
                {"s": sub},
            ).all()
        ]
        assert len(set(per_uc)) >= 2  # the counts are NOT all identical
        matched = conn.execute(
            text(
                "SELECT count(DISTINCT story_key) FROM control.story_use_case_link "
                "WHERE version_id = 'v7' AND subcap_id = :s"
            ),
            {"s": sub},
        ).scalar()
        subtotal = conn.execute(
            text(
                "SELECT count(*) FROM control.story_catalogue_link "
                "WHERE version_id = 'v7' AND subcap_id = :s"
            ),
            {"s": sub},
        ).scalar()
        assert 0 < matched <= subtotal  # grounded: a real subset of the subcap's delivery


@needs_db
def test_single_use_case_subcap_takes_all_its_delivery(carried: None) -> None:
    """A subcap with exactly ONE use case attributes its whole delivery to that use case (no
    discrimination needed) — so the use case's matched count equals the subcap total."""
    eng = _sync()
    with eng.connect() as conn:  # type: ignore[attr-defined]
        row = conn.execute(
            text(
                "SELECT scl.subcap_id, count(*) AS subtotal FROM control.story_catalogue_link scl "
                "JOIN (SELECT subcap_id FROM cat_v7.use_case GROUP BY subcap_id "
                "      HAVING count(*) = 1) u ON u.subcap_id = scl.subcap_id "
                "WHERE scl.version_id = 'v7' GROUP BY scl.subcap_id LIMIT 1"
            )
        ).first()
        if row is None:
            pytest.skip("no single-use-case subcap with carried delivery in this corpus")
        sub, subtotal = row[0], row[1]
        matched = conn.execute(
            text(
                "SELECT count(DISTINCT story_key) FROM control.story_use_case_link "
                "WHERE version_id = 'v7' AND subcap_id = :s"
            ),
            {"s": sub},
        ).scalar()
        assert matched == subtotal


@needs_db
def test_matcher_is_idempotent(carried: None) -> None:
    """Re-running the matcher rebuilds the same link set (version-scoped DELETE + rebuild)."""

    async def _rerun() -> dict[str, object]:
        db.init_engine()
        out = await use_case_match.match_use_cases("v7")
        await db.dispose_engine()
        return out

    before = _sync()
    with before.connect() as conn:  # type: ignore[attr-defined]
        n0 = conn.execute(
            text("SELECT count(*) FROM control.story_use_case_carry WHERE target_version = 'v7'")
        ).scalar()
    summary = asyncio.run(_rerun())
    after = _sync()
    with after.connect() as conn:  # type: ignore[attr-defined]
        n1 = conn.execute(
            text("SELECT count(*) FROM control.story_use_case_carry WHERE target_version = 'v7'")
        ).scalar()
    assert n0 == n1 == summary["matched"]


@needs_db
def test_endpoint_matched_delivery_and_drawer(carried: None) -> None:
    """The Use Case Explorer endpoint ranks by MATCHED delivery and the drawer endpoint returns that
    use case's own matched stories (reconciling exactly with its count)."""
    with TestClient(create_app()) as c:
        body = c.get("/api/catalogue/v7/use-cases?sort=delivery&size=1").json()
        top = body["items"][0]
        assert top["n_stories"] > 0 and top["n_stories"] <= top["subcap_stories"]
        # the L1-capability facet carries real matched-story totals
        assert any(cat["n_stories"] > 0 for cat in body["categories"])
        st = c.get(f"/api/catalogue/v7/use-cases/{top['use_case_id']}/stories").json()
        assert st["total"] == top["n_stories"]  # drawer == the use case's matched count
        assert st["items"] and st["items"][0]["story_key"]
