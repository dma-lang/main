"""G4/G5: validation gates log + QA & audit, over the gate-run / audit data the trust layer writes.

DB-backed, self-cleaning. Provisions v7, runs a propose + apply (which writes gate runs + an audit
row), then asserts the gates/qa/audit endpoints reflect it.
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
from app.services import provision, users
from app.services import stories as story_svc
from app.services import suggestions as sug_svc


@pytest.fixture(scope="module")
def provisioned() -> Iterator[None]:
    from app import migrate

    migrate.run()

    async def _setup() -> None:
        db.init_engine()
        await provision.bring_version_online("v7")
        await story_svc.carry_forward("v7")
        await users.upsert_user("dev-user", "dev@zennify.com", True)
        await sug_svc.propose("v7")
        pending = await sug_svc.list_suggestions("pending")
        await sug_svc.apply(pending[0].suggestion_id, "dev-user")  # writes gate runs + audit row
        await db.dispose_engine()

    async def _teardown() -> None:
        db.init_engine()
        engine = db.get_engine()
        assert engine is not None
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM control.suggestion WHERE target_version = 'v7'"))
            await conn.execute(text("DELETE FROM control.validation_gate_run"))
            await conn.execute(text("DELETE FROM control.reasoning_chain"))
            await conn.execute(
                text("DELETE FROM control.audit_log WHERE action LIKE 'suggestion%'")
            )
            await conn.execute(text("DELETE FROM control.evidence_item WHERE kind = 'catalogue'"))
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


needs_db = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"), reason="DATABASE_URL not set (DB-backed test)"
)


@pytest.fixture
def client(provisioned: None) -> Iterator[TestClient]:
    with TestClient(create_app()) as c:
        yield c


@needs_db
def test_gates_log(client: TestClient) -> None:
    body = client.get("/api/gates").json()
    assert body["total_runs"] > 0
    assert body["pass_runs"] == body["total_runs"]  # everything passed
    ids = {g["id"] for g in body["gates"]}
    assert {"G1", "G5", "G8"} <= ids  # suggestion runs exercise the full G1-G8 set
    assert all(0 <= g["pass_pct"] <= 100 for g in body["gates"])


@needs_db
def test_qa_metrics(client: TestClient) -> None:
    body = client.get("/api/qa/metrics").json()
    assert body["gate_pass_rate"] == 100.0
    assert body["reasoning_chains"] > 0
    assert body["applied"] >= 1
    assert body["spend_usd"] == 0.0  # hermetic spend, admin-visible
    assert body["envelope_usd"] == 8000


@needs_db
def test_audit_log(client: TestClient) -> None:
    rows = client.get("/api/audit-log").json()
    assert len(rows) >= 1
    apply_rows = [r for r in rows if r["action"] == "suggestion.apply"]
    assert apply_rows
    meta = apply_rows[0]["meta"]
    assert meta["after"] == "rising" and meta["before"] != meta["after"]
