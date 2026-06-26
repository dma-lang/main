"""Config-driven subvertical-code aliases (services/sv_aliases) — the PEN -> RIA autocorrect.

Unit: the normaliser folds a legacy code + a tier's SV suffix, and passes unknown/empty through
(never dropped). It also flows through the story ingest + carry-forward row builders.

DB: provisioning v5 — which tags 5 RIA / broker-dealer subcaps with the LEGACY tier ``T2-PEN`` —
folds them to ``T2-RIA``, so the catalogue reconciles with v7 + the nine modelled subverticals and
none of that delivery lands as 'unscoped'.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, text

from app import db
from app.services import provision, stories
from app.services.sv_aliases import normalize_sv_code, normalize_tier, reload_aliases

needs_db = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"), reason="DATABASE_URL not set (DB-backed test)"
)


def test_normalize_sv_code_folds_alias_and_passes_unknown_through() -> None:
    reload_aliases()
    assert normalize_sv_code("PEN") == "RIA"  # the alias
    assert normalize_sv_code("pen") == "RIA"  # case-insensitive
    assert normalize_sv_code("RIA") == "RIA"  # canonical pass-through
    assert normalize_sv_code("RB") == "RB"  # a modelled code, unchanged
    assert normalize_sv_code("zz") == "ZZ"  # unknown -> uppercased, never dropped
    assert normalize_sv_code(None) is None
    assert normalize_sv_code("") == ""


def test_normalize_tier_rewrites_only_the_sv_suffix() -> None:
    assert normalize_tier("T2-PEN") == "T2-RIA"
    assert normalize_tier("T2-RB") == "T2-RB"
    assert normalize_tier("T1") == "T1"  # no SV suffix
    assert normalize_tier("T2") == "T2"
    assert normalize_tier(None) is None


def test_story_ingest_and_carry_rows_normalize_the_sv() -> None:
    ing = stories._ingest_row(
        {"k": "X-1", "sc": "P3C1.8", "sv": "PEN", "psv": "pen", "tier": "T2-PEN"}, "v7"
    )
    assert ing["story_sv_code"] == "RIA"
    assert ing["project_sv_code"] == "RIA"
    assert ing["tier"] == "T2-RIA"
    carry = stories._carry_row({"k": "X-1", "sc": "P3C1.8", "sv": "PEN"}, {"P3C1.8"}, "v7", "v7")
    assert carry["subvertical"] == "RIA"


@pytest.fixture(scope="module")
def v5_provisioned() -> Iterator[None]:
    from app import migrate

    migrate.run()

    async def _setup() -> None:
        db.init_engine()
        await provision.bring_version_online("v5")
        await db.dispose_engine()

    async def _teardown() -> None:
        db.init_engine()
        engine = db.get_engine()
        assert engine is not None
        async with engine.begin() as conn:
            await conn.execute(text("DROP SCHEMA IF EXISTS cat_v5 CASCADE"))
            await conn.execute(
                text("DELETE FROM control.catalogue_version WHERE version_id = 'v5'")
            )
        await db.dispose_engine()

    asyncio.run(_setup())
    yield
    asyncio.run(_teardown())


@needs_db
def test_v5_legacy_pen_tier_folds_to_ria(v5_provisioned: None) -> None:
    sync = create_engine(os.environ["DATABASE_URL"].replace("+asyncpg", "+psycopg"))
    with sync.connect() as conn:
        q = text("SELECT count(*) FROM cat_v5.subcap WHERE tier = :t")
        pen = conn.execute(q, {"t": "T2-PEN"}).scalar()
        ria = conn.execute(q, {"t": "T2-RIA"}).scalar()
    sync.dispose()
    assert pen == 0  # the legacy code is gone after the fold
    assert ria == 19  # 14 native RIA + 5 folded from the legacy T2-PEN
