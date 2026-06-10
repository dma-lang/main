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
            assert report["offerings"] > 0
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


@needs_db
def test_provision_seeds_v5_catalogue_with_id_governance() -> None:
    """The legacy v5 pillar-wise maps provision from their committed seed (837 subcaps), and the
    one real ID collision (P2C3.2.IC1 held both 'Policy Self-Service' and 'AI Claims Estimation')
    is reconciled against the v7 register — ids never reused. The crosswalk record DEFERS while
    v7 is not provisioned (fresh instance, legacy-first order must not fail the transaction) and
    lands, self-healing, the moment v7 comes online."""
    from app import migrate

    migrate.run()

    async def _run() -> None:
        db.init_engine()
        try:
            report = await provision.bring_version_online("v5")
            assert report["subcaps"] == 837
            assert report["pillars"] == 4
            assert report["categories"] == 17
            # v7 (the governing register) is not provisioned yet -> the link defers, not fails
            assert report["id_links_recorded"] == 0
            assert report["id_links_deferred"] == 1
            engine = db.get_engine()
            assert engine is not None
            async with engine.connect() as conn:
                # both colliding subcaps exist, each under its governed id
                rows = (
                    await conn.execute(
                        text(
                            "SELECT subcap_id, name FROM cat_v5.subcap "
                            "WHERE subcap_id IN ('P2C3.2.IC1', 'P2C3.2.IC2')"
                        )
                    )
                ).all()
                names: dict[str, str] = {str(r[0]): str(r[1]) for r in rows}
                assert names["P2C3.2.IC1"] == "Policy Self-Service"
                assert names["P2C3.2.IC2"] == "AI Claims Estimation"
            # provisioning the governing version sweeps the deferred link in
            report7 = await provision.bring_version_online("v7")
            assert report7["id_links_recorded"] == 1
            assert report7["id_links_deferred"] == 0
            async with engine.connect() as conn:
                note = (
                    await conn.execute(
                        text(
                            "SELECT note FROM control.version_crosswalk "
                            "WHERE from_version = 'v5' AND from_subcap = 'P2C3.2.IC2' "
                            "AND to_version = 'v7'"
                        )
                    )
                ).scalar()
                assert note is not None and note.startswith("id-governance:")
                assert "P2C3.2.IC1" in note  # names the source-workbook id it collided under
        finally:
            engine = db.get_engine()
            if engine is not None:
                async with engine.begin() as conn:
                    await conn.execute(text("DROP SCHEMA IF EXISTS cat_v5 CASCADE"))
                    await conn.execute(text("DROP SCHEMA IF EXISTS cat_v7 CASCADE"))
                    await conn.execute(
                        text(
                            "DELETE FROM control.version_crosswalk "
                            "WHERE from_version = 'v5' OR to_version = 'v5'"
                        )
                    )
                    await conn.execute(
                        text(
                            "DELETE FROM control.catalogue_version "
                            "WHERE version_id IN ('v5', 'v7')"
                        )
                    )
            await db.dispose_engine()

    asyncio.run(_run())
