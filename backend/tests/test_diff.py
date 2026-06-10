"""G2 — catalogue diff between two provisioned versions. DB-backed, self-cleaning.

Provisions v7 plus a scratch second version from the same seed (identical → empty diff), then
mutates the scratch copy (rename one subcap, delete another) and asserts the diff reports exactly
those changes. An unprovisioned version id is a clear 404.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app import db
from app.main import create_app
from app.services import provision

needs_db = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"), reason="DATABASE_URL not set (DB-backed test)"
)

SCRATCH = "vdiff"


@pytest.fixture(scope="module")
def two_versions() -> Iterator[None]:
    from app import migrate

    migrate.run()

    async def _setup() -> None:
        db.init_engine()
        await provision.bring_version_online("v7")
        await provision.bring_version_online(SCRATCH, label="Diff scratch")
        engine = db.get_engine()
        assert engine is not None
        async with engine.begin() as conn:
            # one rename + one removal in the scratch copy
            await conn.execute(
                text(
                    f"UPDATE cat_{SCRATCH}.subcap SET name = 'Renamed For Diff' "
                    "WHERE subcap_id = 'P1C1.1.1'"
                )
            )
            await conn.execute(
                text(f"DELETE FROM cat_{SCRATCH}.use_case WHERE subcap_id = 'P1C1.1.2'")
            )
            await conn.execute(
                text(f"DELETE FROM cat_{SCRATCH}.subcap_persona WHERE subcap_id = 'P1C1.1.2'")
            )
            await conn.execute(
                text(f"DELETE FROM cat_{SCRATCH}.subcap_platform WHERE subcap_id = 'P1C1.1.2'")
            )
            await conn.execute(
                text(f"DELETE FROM cat_{SCRATCH}.maturity_descriptor WHERE subcap_id = 'P1C1.1.2'")
            )
            await conn.execute(
                text(f"DELETE FROM cat_{SCRATCH}.offering_subcap WHERE subcap_id = 'P1C1.1.2'")
            )
            await conn.execute(
                text(f"DELETE FROM cat_{SCRATCH}.subcap WHERE subcap_id = 'P1C1.1.2'")
            )
        await db.dispose_engine()

    async def _teardown() -> None:
        db.init_engine()
        engine = db.get_engine()
        assert engine is not None
        async with engine.begin() as conn:
            for v in ("v7", SCRATCH):
                await conn.execute(text(f"DROP SCHEMA IF EXISTS cat_{v} CASCADE"))
                await conn.execute(
                    text("DELETE FROM control.catalogue_version WHERE version_id = :v"),
                    {"v": v},
                )
        await db.dispose_engine()

    asyncio.run(_setup())
    yield
    asyncio.run(_teardown())


@pytest.fixture
def client(two_versions: None) -> Iterator[TestClient]:
    with TestClient(create_app()) as c:
        yield c


@needs_db
def test_self_compare_is_empty(client: TestClient) -> None:
    d = client.get("/api/diff/v7/v7").json()
    assert d["added"] == [] and d["removed"] == [] and d["modified"] == []
    assert d["unchanged"] == 851


@needs_db
def test_diff_reports_exact_changes(client: TestClient) -> None:
    """a=scratch (mutated), b=v7: the deleted subcap is ADDED in b's direction, the rename is
    MODIFIED naming the field; everything else unchanged."""
    d = client.get(f"/api/diff/{SCRATCH}/v7").json()
    assert [r["id"] for r in d["added"]] == ["P1C1.1.2"]
    assert d["removed"] == []
    assert [m["id"] for m in d["modified"]] == ["P1C1.1.1"]
    assert d["modified"][0]["changes"] == ["name"]
    assert d["unchanged"] == 849

    # and the reverse direction flips added/removed
    rev = client.get(f"/api/diff/v7/{SCRATCH}").json()
    assert [r["id"] for r in rev["removed"]] == ["P1C1.1.2"]
    assert rev["added"] == []


@needs_db
def test_unprovisioned_version_is_clear_404(client: TestClient) -> None:
    r = client.get("/api/diff/v7/v5")
    assert r.status_code == 404
    assert "error" in r.json()
