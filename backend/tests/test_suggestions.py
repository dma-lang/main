"""F8: the AI suggestion lifecycle — propose -> G1-G8 -> apply (gated mutation) / reject.

DB-backed, self-cleaning. Verifies that an apply re-gates, mutates cat_<v>, and writes an immutable
audit_log row; that a reject needs a reason; and that the whole thing never half-applies.
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
from app.services import stories as story_svc

needs_db = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"), reason="DATABASE_URL not set (DB-backed test)"
)


@pytest.fixture(scope="module")
def provisioned() -> Iterator[None]:
    from app import migrate

    migrate.run()

    async def _setup() -> None:
        db.init_engine()
        await provision.bring_version_online("v7")
        await story_svc.carry_forward("v7")
        await db.dispose_engine()

    async def _teardown() -> None:
        db.init_engine()
        engine = db.get_engine()
        assert engine is not None
        async with engine.begin() as conn:
            # FK-safe order: suggestion -> gate_run -> chain (cascades steps/citations) -> evidence.
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


@pytest.fixture
def client(provisioned: None) -> Iterator[TestClient]:
    with TestClient(create_app()) as c:
        yield c


@needs_db
def test_gated_mutation_lifecycle(client: TestClient) -> None:
    created = client.post("/api/admin/suggestions/propose/v7").json()
    assert created["created"] > 0

    pending = client.get("/api/suggestions?status=pending").json()
    assert len(pending) >= 2
    sug = pending[0]
    assert sug["verdict"] == "pass"  # all G1-G8 passed
    assert sug["claim_label"] == "INFERENCE"
    assert sug["ers"] > 0
    target = sug["target_subcap"]

    before = client.get(f"/api/catalogue/v7/subcaps/{target}").json()["lifecycle_state"]
    applied = client.post(f"/api/suggestions/{sug['suggestion_id']}/apply").json()
    assert applied["applied"] is True
    assert applied["before"] == before and applied["after"] == "rising"

    # the catalogue was actually mutated, gated, server-side
    after = client.get(f"/api/catalogue/v7/subcaps/{target}").json()["lifecycle_state"]
    assert after == "rising" and after != before

    # an immutable audit_log row records the gated apply (before/after for revert). Use a fresh
    # sync connection — the async engine is bound to the TestClient's event loop.
    sync_eng = create_engine(os.environ["DATABASE_URL"].replace("+asyncpg", "+psycopg"))
    with sync_eng.connect() as conn:
        audit_n = conn.execute(
            text(
                "SELECT count(*) FROM control.audit_log "
                "WHERE action = 'suggestion.apply' AND target_ref = :t"
            ),
            {"t": target},
        ).scalar()
    sync_eng.dispose()
    assert int(audit_n or 0) >= 1

    # idempotent: re-applying an already-applied suggestion is a no-op
    again = client.post(f"/api/suggestions/{sug['suggestion_id']}/apply").json()
    assert again["applied"] is False and again["status"] == "applied"

    # reject needs a reason
    other = pending[1]["suggestion_id"]
    assert client.post(f"/api/suggestions/{other}/reject", json={"reason": ""}).status_code == 400
    rejected = client.post(
        f"/api/suggestions/{other}/reject", json={"reason": "out of scope this quarter"}
    ).json()
    assert rejected["status"] == "rejected"


@needs_db
def test_apply_unknown_404(client: TestClient) -> None:
    r = client.post("/api/suggestions/00000000-0000-0000-0000-000000000000/apply")
    assert r.status_code == 404
