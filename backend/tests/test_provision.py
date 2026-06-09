"""F4: provisioning generates cat_<version> and seeds the real v7 catalogue (851 subcaps).

DB-backed (skipped without DATABASE_URL). Self-cleaning so it never leaves a provisioned version
behind (keeps the rest of the suite order-independent).
"""

from __future__ import annotations

import asyncio
import os

import pytest
from sqlalchemy import text

from app import db
from app.services import provision

needs_db = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"), reason="DATABASE_URL not set (DB-backed test)"
)


@needs_db
def test_provision_seeds_v7_catalogue() -> None:
    from app import migrate

    migrate.run()  # ensure the control plane exists (sync, idempotent)

    async def _run() -> None:
        db.init_engine()
        try:
            report = await provision.bring_version_online("v7")
            assert report["subcaps"] == 851
            assert report["pillars"] == 4
            assert report["categories"] == 16
            # Catalogue enrichment (from the comprehensive pillar workbooks) is seeded too.
            assert report["use_cases"] > 0
            assert report["platforms"] > 0
            assert report["maturity"] > 0
            engine = db.get_engine()
            assert engine is not None
            async with engine.connect() as conn:
                subcaps = (await conn.execute(text("SELECT count(*) FROM cat_v7.subcap"))).scalar()
                use_cases = (
                    await conn.execute(text("SELECT count(*) FROM cat_v7.use_case"))
                ).scalar()
                links = (
                    await conn.execute(text("SELECT count(*) FROM cat_v7.subcap_platform"))
                ).scalar()
                version = (
                    await conn.execute(
                        text("SELECT status FROM control.catalogue_version WHERE version_id = 'v7'")
                    )
                ).scalar()
            assert int(subcaps or 0) == 851
            assert int(use_cases or 0) > 0
            assert int(links or 0) > 0
            assert version == "provisioned"
        finally:
            engine = db.get_engine()
            if engine is not None:
                async with engine.begin() as conn:
                    await conn.execute(text("DROP SCHEMA IF EXISTS cat_v7 CASCADE"))
                    await conn.execute(
                        text("DELETE FROM control.catalogue_version WHERE version_id = 'v7'")
                    )
            await db.dispose_engine()

    asyncio.run(_run())
