"""H1/H2: catalogue-grounded chat + the reasoning-chain viewer. DB-backed, self-cleaning.

Provisions v7 (for retrieval) and clears the reasoning/evidence rows the chat writes to control.*,
so the suite stays order-independent.
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


@pytest.fixture(scope="module")
def provisioned() -> Iterator[None]:
    from app import migrate

    migrate.run()

    async def _setup() -> None:
        db.init_engine()
        await provision.bring_version_online("v7")
        await db.dispose_engine()

    async def _teardown() -> None:
        db.init_engine()
        engine = db.get_engine()
        assert engine is not None
        async with engine.begin() as conn:
            # gate runs reference the chain (no cascade); delete them first, then the chain
            # (cascades steps + citations), then the catalogue evidence the citations pointed at.
            await conn.execute(
                text("DELETE FROM control.validation_gate_run WHERE target_ref = 'chat'")
            )
            await conn.execute(text("DELETE FROM control.reasoning_chain WHERE operation = 'chat'"))
            await conn.execute(text("DELETE FROM control.evidence_item WHERE kind = 'catalogue'"))
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
def test_chat_grounded(client: TestClient) -> None:
    r = client.post(
        "/api/chat", json={"question": "identity resolution customer profile", "version": "v7"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["grounded"] is True
    assert len(body["citations"]) > 0
    assert body["claim_label"] == "FACT"
    assert body["source_tier"] == "T1"
    assert body["ers"] > 0
    assert body["chain_id"]
    # the answer is auditable end-to-end
    rc = client.get(f"/api/reasoning/{body['chain_id']}").json()
    assert rc["verdict"] == "pass"
    assert len(rc["steps"]) >= 2  # retrieve + conclude at minimum
    assert any("G5" in c["name"] for c in rc["checks"])  # grounding gate ran


@needs_db
def test_chat_refuses_ungrounded(client: TestClient) -> None:
    # G5: nothing retrieved -> refuse; no citations, no chain, never from model memory.
    body = client.post(
        "/api/chat", json={"question": "zzqxnonsensetokenxyz", "version": "v7"}
    ).json()
    assert body["grounded"] is False
    assert body["citations"] == []
    assert body["chain_id"] is None


@needs_db
def test_chat_empty_question_400(client: TestClient) -> None:
    assert client.post("/api/chat", json={"question": "   ", "version": "v7"}).status_code == 400


@needs_db
def test_reasoning_unknown_404(client: TestClient) -> None:
    r = client.get("/api/reasoning/00000000-0000-0000-0000-000000000000")
    assert r.status_code == 404


@needs_db
def test_reasoning_list_indexes_new_chains(client: TestClient) -> None:
    """GET /api/reasoning (H2 index): a chat-created chain appears newest-first with the trust
    fields the viewer renders (claim label, verdict, model, cost, step count)."""
    chain_id = client.post(
        "/api/chat", json={"question": "identity resolution customer profile", "version": "v7"}
    ).json()["chain_id"]
    rows = client.get("/api/reasoning").json()
    assert rows and rows[0]["chain_id"] == chain_id
    top = rows[0]
    assert top["title"]
    assert top["steps"] >= 2
    assert top["cost"].startswith("$")
    assert set(top) >= {"chain_id", "title", "claim_label", "verdict", "model", "created_at"}
    # ?limit= is capped and respected
    assert len(client.get("/api/reasoning?limit=1").json()) == 1
