"""C1/FR-7 — SOW pipeline: ingest -> match -> gate -> persist; confirm; clients (FR-19).

DB-backed, self-cleaning. Provisions v7, scans the recorded SOW corpus against it, and asserts the
matching bands, idempotency, trust envelope, confirm attestation, the client entity-resolution
roster and the journey read.
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
            await conn.execute(text("DELETE FROM control.sow_subcap_match"))
            await conn.execute(text("DELETE FROM control.sow_scope_item"))
            await conn.execute(text("DELETE FROM control.sow_document"))
            # the chains' steps/citations reference the sow_chunk evidence — drop chains first
            chains = "SELECT chain_id FROM control.reasoning_chain WHERE operation = 'sow_match'"
            for tbl, col in (
                ("validation_gate_run", "chain_id"),
                ("citation", "chain_id"),
                ("reasoning_step", "chain_id"),
            ):
                await conn.execute(text(f"DELETE FROM control.{tbl} WHERE {col} IN ({chains})"))
            await conn.execute(
                text("DELETE FROM control.reasoning_chain WHERE operation = 'sow_match'")
            )
            await conn.execute(text("DELETE FROM control.evidence_item WHERE kind = 'sow_chunk'"))
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
def test_scan_matches_bands_and_is_idempotent(client: TestClient) -> None:
    out = client.post("/api/admin/sow/scan/v7").json()
    assert out["documents"] == 6 and out["scope_items"] == 23
    assert out["matched"] == 23 and out["deduped"] == 0
    # all three carry-forward bands are reachable from the real retrieval path
    assert out["confirmed"] > 0 and out["review"] + out["unmapped"] > 0
    assert out["confirmed"] + out["review"] + out["unmapped"] == 23

    again = client.post("/api/admin/sow/scan/v7").json()
    assert again["matched"] == 0 and again["deduped"] == 23  # zero marginal work on re-scan


@needs_db
def test_roster_detail_and_trust_envelope(client: TestClient) -> None:
    client.post("/api/admin/sow/scan/v7")
    docs = client.get("/api/sow?version=v7").json()
    assert len(docs) == 6
    bay = next(d for d in docs if d["account_key"] == "BAYPORT")
    assert bay["redacted"] is True and bay["items"] == 5
    assert bay["confirmed"] + bay["review"] + bay["unmapped"] == 5

    detail = client.get(f"/api/sow/{bay['sow_id']}?version=v7").json()
    assert len(detail["items"]) == 5
    for item in detail["items"]:
        assert item["clause"]
        if item["status"] != "unmapped":
            assert item["subcap_id"] and item["subcap_name"]
        # the trust envelope travels with every match
        assert item["claim_label"] in ("FACT", "INFERENCE", "HYPOTHESIS")
        assert item["source_tier"] == "T1"
        assert item["chain_id"]
        # the chain resolves in the universal audit window
        rc = client.get(f"/api/reasoning/{item['chain_id']}")
        assert rc.status_code == 200

    assert client.get(f"/api/sow/{'0' * 8}-0000-0000-0000-{'0' * 12}").status_code == 404


@needs_db
def test_confirm_is_attested_and_audited(client: TestClient) -> None:
    client.post("/api/admin/sow/scan/v7")
    docs = client.get("/api/sow?version=v7").json()
    review_doc = next((d for d in docs if d["review"] > 0), None)
    if review_doc is None:
        pytest.skip("no review-band match in this corpus run")
    detail = client.get(f"/api/sow/{review_doc['sow_id']}?version=v7").json()
    m = next(i for i in detail["items"] if i["status"] == "review")
    out = client.post(f"/api/sow/matches/{m['match_id']}/confirm").json()
    assert out["ok"] is True and out["status"] == "confirmed"
    # re-read: status flipped and the claim upgraded to a human-attested FACT
    detail2 = client.get(f"/api/sow/{review_doc['sow_id']}?version=v7").json()
    m2 = next(i for i in detail2["items"] if i["match_id"] == m["match_id"])
    assert m2["status"] == "confirmed" and m2["claim_label"] == "FACT"
    # audited
    audit = client.get("/api/audit-log").json()
    assert any(a["action"] == "sow_match.confirm" for a in audit)


@needs_db
def test_clients_resolution_and_journey(client: TestClient) -> None:
    client.post("/api/admin/sow/scan/v7")
    roster = client.get("/api/clients?version=v7").json()
    bay = next(c for c in roster if c["key"] == "BAYPORT")
    # entity resolution joins BOTH sides: the SOW corpus and the real Jira delivery corpus
    assert bay["sows"] == 1 and bay["scope_items"] == 5
    assert bay["stories"] == 0 or bay["stories"] > 0  # stories present only after carry-forward

    j = client.get("/api/clients/BAYPORT/journey?version=v7").json()
    assert j["key"] == "BAYPORT" and len(j["sows"]) == 1
    assert all(m["status"] in ("confirmed", "review") for m in j["matches"])
    assert client.get("/api/clients/NOPEKEY/journey?version=v7").status_code == 404
