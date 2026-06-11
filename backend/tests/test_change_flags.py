"""G3: the change-flags inbox — the human-review choke-point.

DB-backed, self-cleaning. A scan turns lifecycle-vs-delivery contradictions into change flags (each
with a failing G6 gate run + reasoning chain). approve RE-GATES the proposed correction server-side
and, on pass, mutates cat_<v> + writes an immutable audit_log row; reject needs a reason; defer
snoozes. Nothing auto-acts and nothing half-applies.
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
            # FK-safe order: change_flag (-> chain) first, then gate_run -> chain -> evidence.
            await conn.execute(text("DELETE FROM control.change_flag"))
            await conn.execute(text("DELETE FROM control.validation_gate_run"))
            await conn.execute(text("DELETE FROM control.reasoning_chain"))
            await conn.execute(
                text("DELETE FROM control.audit_log WHERE action LIKE 'change_flag%'")
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
def test_change_flag_lifecycle(client: TestClient) -> None:
    scanned = client.post("/api/admin/change-flags/scan/v7").json()
    assert scanned["created"] > 0

    body = client.get("/api/change-flags?status=open").json()
    flags = body["flags"]
    assert len(flags) >= 2
    assert sum(body["counts"].values()) == len(flags)
    f = flags[0]
    assert f["kind"] == "contradicted_evidence"
    assert f["gate_failed"] == "G6_contradiction"
    assert f["before"] in ("declining", "fading", "dead")
    assert f["after"] == "stable"
    assert f["sev"] in ("BLOCKING", "HIGH", "MED", "LOW")

    # The detection gate run failed G6 (a real contradiction, surfaced not dropped).
    chain = client.get(f"/api/reasoning/{f['chain']}").json()
    assert chain["verdict"] == "fail"
    g6 = next(c for c in chain["checks"] if c["name"] == "G6_contradiction")
    assert g6["state"] == "Needs review"

    target = f["target"]
    before = client.get(f"/api/catalogue/v7/subcaps/{target}").json()["lifecycle_state"]
    approved = client.post(f"/api/change-flags/{f['id']}/approve").json()
    assert approved["resolved"] is True
    assert approved["before"] == before and approved["after"] == "stable"

    # the catalogue was actually corrected, re-gated, server-side
    after = client.get(f"/api/catalogue/v7/subcaps/{target}").json()["lifecycle_state"]
    assert after == "stable" and after != before

    # an immutable audit_log row records the gated approval (before/after for revert)
    sync_eng = create_engine(os.environ["DATABASE_URL"].replace("+asyncpg", "+psycopg"))
    with sync_eng.connect() as conn:
        audit_n = conn.execute(
            text(
                "SELECT count(*) FROM control.audit_log "
                "WHERE action = 'change_flag.approve' AND target_ref = :t"
            ),
            {"t": target},
        ).scalar()
    sync_eng.dispose()
    assert int(audit_n or 0) >= 1

    # idempotent: re-approving a resolved flag is a no-op
    again = client.post(f"/api/change-flags/{f['id']}/approve").json()
    assert again["resolved"] is False and again["status"] == "approved"

    # reject needs a reason; defer snoozes out of the open inbox
    second, third = flags[1]["id"], flags[2]["id"]
    assert client.post(f"/api/change-flags/{second}/reject", json={"reason": ""}).status_code == 400
    rejected = client.post(
        f"/api/change-flags/{second}/reject", json={"reason": "legacy wind-down, expected"}
    ).json()
    assert rejected["status"] == "rejected"
    assert client.post(f"/api/change-flags/{third}/defer").json()["status"] == "deferred"

    open_ids = {x["id"] for x in client.get("/api/change-flags?status=open").json()["flags"]}
    assert f["id"] not in open_ids and second not in open_ids and third not in open_ids

    # re-scan is idempotent — existing flags are not duplicated
    rescan = client.post("/api/admin/change-flags/scan/v7").json()
    assert rescan["created"] == 0


@needs_db
def test_decay_no_delivery_flags_let_admin_mark_inactive(client: TestClient) -> None:
    """Decay (user definition): a subcap with no real Jira story is flagged for the admin, who can
    APPROVE to mark it inactive (lifecycle -> 'dead'), gated + audited. v7's corpus covers ~87 of
    851 subcaps, so the scan raises hundreds of these candidates."""
    client.post("/api/admin/change-flags/scan/v7")
    flags = client.get("/api/change-flags?status=open").json()["flags"]
    decay = [f for f in flags if f["kind"] == "decay_no_delivery"]
    assert len(decay) > 100  # almost all of v7 is decayed — flags reflect that
    f = next(x for x in decay if x["before"] != "dead")
    target = f["target"]
    assert f["after"] == "dead"  # proposed correction: mark inactive

    detail = client.get(f"/api/catalogue/v7/subcaps/{target}").json()
    assert detail["n_stories"] == 0  # genuinely zero real Jira delivery
    before = detail["lifecycle_state"]

    approved = client.post(f"/api/change-flags/{f['id']}/approve").json()
    assert approved["resolved"] is True and approved["after"] == "dead"
    after = client.get(f"/api/catalogue/v7/subcaps/{target}").json()["lifecycle_state"]
    assert after == "dead" and after != before  # marked INACTIVE, gated server-side

    sync_eng = create_engine(os.environ["DATABASE_URL"].replace("+asyncpg", "+psycopg"))
    with sync_eng.connect() as conn:
        n = conn.execute(
            text(
                "SELECT count(*) FROM control.audit_log "
                "WHERE action = 'change_flag.approve' AND target_ref = :t"
            ),
            {"t": target},
        ).scalar()
    sync_eng.dispose()
    assert int(n or 0) >= 1  # the inactivation is audited (before/after for revert)


@needs_db
def test_approve_unknown_404(client: TestClient) -> None:
    r = client.post("/api/change-flags/00000000-0000-0000-0000-000000000000/approve")
    assert r.status_code == 404
