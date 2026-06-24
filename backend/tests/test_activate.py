"""G1 approval toggle: POST /api/admin/versions/{v}/activate — exactly ONE active version.

DB-backed, self-cleaning. Covers the single-active invariant across two provisioned versions,
the 409 for an uploaded-but-unprovisioned version, the 404 for an unknown one, and the
append-only audit trail (actor = users.uid, the FK the live 500 regression was about).
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app import db
from app.main import create_app
from app.services import provision

needs_db = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"), reason="DATABASE_URL not set (DB-backed test)"
)


@pytest.fixture(scope="module")
def two_versions() -> Iterator[None]:
    from app import migrate

    migrate.run()

    async def _setup() -> None:
        db.init_engine()
        await provision.bring_version_online("v7")
        await provision.bring_version_online("v5")
        engine = db.get_engine()
        assert engine is not None
        async with engine.begin() as conn:
            # an uploaded-only row (parse committed, no cat_<v> schema) for the 409 path
            await conn.execute(
                text(
                    "INSERT INTO control.catalogue_version (version_id, label, status, "
                    "schema_name) VALUES ('v9', 'Catalogue v9.0', 'uploaded', 'cat_v9') "
                    "ON CONFLICT (version_id) DO UPDATE SET status = 'uploaded'"
                )
            )
        await db.dispose_engine()

    async def _teardown() -> None:
        db.init_engine()
        engine = db.get_engine()
        assert engine is not None
        async with engine.begin() as conn:
            await conn.execute(text("DROP SCHEMA IF EXISTS cat_v5 CASCADE"))
            await conn.execute(text("DROP SCHEMA IF EXISTS cat_v7 CASCADE"))
            await conn.execute(
                text(
                    "DELETE FROM control.version_crosswalk "
                    "WHERE from_version IN ('v5', 'v7') OR to_version IN ('v5', 'v7')"
                )
            )
            await conn.execute(
                text("DELETE FROM control.catalogue_version WHERE version_id IN ('v5', 'v7', 'v9')")
            )
        await db.dispose_engine()

    asyncio.run(_setup())
    yield
    asyncio.run(_teardown())


@pytest.fixture
def client(two_versions: None) -> Iterator[TestClient]:
    with TestClient(create_app()) as c:
        yield c


def _statuses(client: TestClient) -> dict[str, str]:
    return {v["version_id"]: v["status"] for v in client.get("/api/versions").json()}


@needs_db
def test_activate_enforces_single_active(client: TestClient) -> None:
    r = client.post("/api/admin/versions/v5/activate")
    assert r.status_code == 200 and r.json()["active"] == "v5"
    st = _statuses(client)
    assert st["v5"] == "active"
    assert [v for v, s in st.items() if s == "active"] == ["v5"]

    # switching promotes the target and demotes the previous active — never two actives
    r = client.post("/api/admin/versions/v7/activate")
    assert r.status_code == 200 and r.json()["active"] == "v7"
    st = _statuses(client)
    assert st["v7"] == "active" and st["v5"] == "provisioned"
    assert [v for v, s in st.items() if s == "active"] == ["v7"]


@needs_db
def test_activate_uploaded_409_unknown_404(client: TestClient) -> None:
    r = client.post("/api/admin/versions/v9/activate")
    assert r.status_code == 409  # parse committed but not provisioned — approve after provision
    assert client.post("/api/admin/versions/v0/activate").status_code == 404
    assert client.post("/api/admin/versions/BAD;DROP/activate").status_code == 400


@needs_db
def test_activate_writes_audit_row(client: TestClient) -> None:
    client.post("/api/admin/versions/v7/activate")
    # fresh SYNC connection — the app's async engine is bound to the TestClient's event loop
    sync_eng = create_engine(os.environ["DATABASE_URL"].replace("+asyncpg", "+psycopg"))
    with sync_eng.connect() as conn:
        n = conn.execute(
            text(
                "SELECT count(*) FROM control.audit_log a "
                "JOIN control.users u ON u.uid = a.actor "  # actor is a REAL uid (FK)
                "WHERE a.action = 'version_activated' AND a.target_ref = 'v7'"
            )
        ).scalar()
    sync_eng.dispose()
    assert int(n or 0) >= 1
