"""Productized-offering -> subcap semantic matcher (services/offerings_match).

Unit: the offerings seed parsed from the GTM doc carries activation offerings + data products, each
with named capabilities + match text.

DB: matching v7 grounds every offering into the catalogue by MEANING (hybrid retrieval) — offerings
+ scored, gated offering_subcap rows populate, idempotently, with every kept match at/above the
config floor and the matching capability recorded as the trust basis.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import create_engine, text

from app import db
from app.intelligence import gates
from app.services import offerings_match, provision, stories

needs_db = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"), reason="DATABASE_URL not set (DB-backed test)"
)


def test_offerings_seed_has_activation_and_data_products() -> None:
    offs = offerings_match.load_offerings()
    assert len(offs) >= 25  # 7 activation + 18+ data products
    fams = {o["family"] for o in offs}
    assert "activation" in fams and "data_product" in fams
    assert all(o.get("match_text") and o.get("name") and o.get("id") for o in offs)
    # the FSC Customer Platform is present with its named Core Capabilities
    fsc = next(o for o in offs if o["id"] == "OFF-FSC-CUSTOMER")
    assert fsc["capabilities"] and any("Household" in c for c in fsc["capabilities"])


@pytest.fixture(scope="module")
def v7_matched() -> Iterator[None]:
    from app import migrate

    migrate.run()

    async def _setup() -> None:
        db.init_engine()
        await provision.bring_version_online("v7")
        await stories.carry_forward("v7")  # auto-runs the offerings matcher
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


@needs_db
def test_carry_forward_populates_doc_grounded_offering_matches(v7_matched: None) -> None:
    floor, _top_k, max_per = gates.offerings_match_config()
    sync = create_engine(os.environ["DATABASE_URL"].replace("+asyncpg", "+psycopg"))
    with sync.connect() as conn:

        def scalar(sql: str, **p: object) -> int:
            return int(conn.execute(text(sql), p).scalar() or 0)

        n_off = scalar("SELECT count(*) FROM cat_v7.offering")
        n_pairs = scalar("SELECT count(*) FROM cat_v7.offering_subcap")
        # every kept match is at/above the gate floor and bounded per offering
        below = scalar(
            "SELECT count(*) FROM cat_v7.offering_subcap WHERE maturity_lift::float < :f", f=floor
        )
        over_cap = scalar(
            "SELECT count(*) FROM (SELECT offering_id, count(*) c "
            "FROM cat_v7.offering_subcap GROUP BY offering_id) q WHERE q.c > :m",
            m=max_per,
        )
        # the doc's offerings replaced the old deterministic seed
        has_lending = scalar(
            "SELECT count(*) FROM cat_v7.offering WHERE offering_id = 'OFF-LENDING'"
        )
        # the trust basis (capability + score) is recorded on every match
        unrationaled = scalar(
            "SELECT count(*) FROM cat_v7.offering_subcap "
            "WHERE mapping_rationale IS NULL OR mapping_rationale NOT LIKE 'semantic match%'"
        )
    sync.dispose()
    assert n_off >= 25  # every productized offering is materialised
    assert n_pairs > 0  # extensive matching produced real coverage
    assert below == 0  # nothing below the gate floor survives (G5-style grounding)
    assert over_cap == 0  # bounded per offering (resilience)
    assert has_lending == 1  # doc-grounded offerings replaced the deterministic seed
    assert unrationaled == 0  # every match carries its capability + score basis


@needs_db
def test_match_offerings_is_idempotent(v7_matched: None) -> None:
    async def _run_twice() -> tuple[dict[str, Any], dict[str, Any]]:
        db.init_engine()  # the fixture disposed the async engine after setup; re-init in THIS loop
        try:
            a = await offerings_match.match_offerings("v7")
            b = await offerings_match.match_offerings("v7")
        finally:
            await db.dispose_engine()
        return a, b

    first, second = asyncio.run(_run_twice())
    assert first["offerings"] == second["offerings"]
    assert first["matched_pairs"] == second["matched_pairs"]  # deterministic rebuild, no drift
    assert second["matched_pairs"] > 0 and second["covered_subcaps"] > 0
