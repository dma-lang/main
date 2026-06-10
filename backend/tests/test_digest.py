"""E1 quarterly digest + F12 signed exports.

Pure-unit coverage of the quarter maths and canonical signing, plus a DB-backed end-to-end run:
scans populate the gated substrate, generate composes the digest (pillar priorities with honest
adversarial lines, cross-pillar theme, INFERENCE + chain), export signs the canonical JSON, and
verification is TAMPER-EVIDENT — regenerating the digest invalidates earlier signatures. Also
covers /api/config (the SPA's public auth bootstrap).
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app import db
from app.main import create_app
from app.services import digest as dg
from app.services import provision
from app.services import stories as story_svc

needs_db = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"), reason="DATABASE_URL not set (DB-backed test)"
)


# --------------------------------------------------------------------------- pure unit tests


def test_current_quarter_and_bounds() -> None:
    assert dg.current_quarter(datetime(2026, 6, 10, tzinfo=UTC)) == "2026-Q2"
    assert dg.current_quarter(datetime(2026, 12, 31, tzinfo=UTC)) == "2026-Q4"
    start, end = dg._quarter_bounds("2026-Q2")
    assert start == datetime(2026, 4, 1, tzinfo=UTC) and end == datetime(2026, 7, 1, tzinfo=UTC)
    q4s, q4e = dg._quarter_bounds("2026-Q4")
    assert q4s == datetime(2026, 10, 1, tzinfo=UTC) and q4e == datetime(2027, 1, 1, tzinfo=UTC)


def test_canonical_payload_is_stable() -> None:
    d = {"quarter": "2026-Q2", "summary": "s", "claim": "INFERENCE"}
    prios = [{"pillar": "P4", "title": "t", "body": "b", "adversary_verdict": "a"}]
    one = dg._canonical(d, prios)
    two = dg._canonical(dict(reversed(list(d.items()))), prios)
    assert one == two  # key order never changes the signature input
    assert '"quarter":"2026-Q2"' in one


# --------------------------------------------------------------------------- DB-backed pipeline


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
            await conn.execute(text("DELETE FROM control.export_manifest WHERE kind = 'digest'"))
            await conn.execute(
                text(
                    "DELETE FROM control.digest_priority WHERE digest_id IN "
                    "(SELECT digest_id FROM control.digest)"
                )
            )
            await conn.execute(text("DELETE FROM control.digest WHERE quarter IS NOT NULL"))
            await conn.execute(text("DELETE FROM control.suggestion"))
            await conn.execute(text("DELETE FROM control.change_flag"))
            await conn.execute(text("DELETE FROM control.validation_gate_run"))
            await conn.execute(text("DELETE FROM control.trend_subcap"))
            await conn.execute(text("DELETE FROM control.trend"))
            await conn.execute(
                text(
                    "DELETE FROM control.news_subcap_impact WHERE news_id IN "
                    "(SELECT news_id FROM control.news_item)"
                )
            )
            await conn.execute(
                text(
                    "DELETE FROM control.vendor_subcap_impact WHERE event_id IN "
                    "(SELECT event_id FROM control.vendor_event)"
                )
            )
            await conn.execute(
                text(
                    "DELETE FROM control.vendor_event WHERE vendor_id IN "
                    "(SELECT vendor_id FROM control.vendor)"
                )
            )
            await conn.execute(
                text(
                    "DELETE FROM control.vendor WHERE vendor_id IN "
                    "(SELECT vendor_id FROM control.vendor)"
                )
            )
            await conn.execute(text("DELETE FROM control.benchmark"))
            await conn.execute(text("DELETE FROM control.reasoning_chain"))
            await conn.execute(
                text(
                    "DELETE FROM control.news_item WHERE evidence_id IN "
                    "(SELECT evidence_id FROM control.evidence_item)"
                )
            )
            await conn.execute(
                text(
                    "DELETE FROM control.ers WHERE evidence_id IN "
                    "(SELECT evidence_id FROM control.evidence_item)"
                )
            )
            await conn.execute(
                text(
                    "DELETE FROM control.evidence_item WHERE kind IN "
                    "('news', 'benchmark', 'vendor_event', 'catalogue')"
                )
            )
            await conn.execute(
                text(
                    "DELETE FROM control.ingest_run WHERE source IN "
                    "('news', 'trends', 'benchmarks', 'vendor')"
                )
            )
            await conn.execute(text("DELETE FROM control.audit_log WHERE action LIKE 'digest%'"))
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
def test_config_is_public_and_honest(client: TestClient) -> None:
    r = client.get("/api/config")
    assert r.status_code == 200
    body = r.json()
    # test env runs AUTH_MODE=dev (conftest): the SPA is told so, and no client id is sent
    assert body["auth_mode"] == "dev" and body["google_client_id"] is None
    assert body["auth_email_domain"] == "zennify.com"


@needs_db
def test_digest_generate_read_export_verify_tamper(client: TestClient) -> None:
    # empty quarter -> honest refusal, never a hollow digest
    empty = client.post("/api/admin/digest/generate", json={"quarter": "2031-Q1"}).json()
    assert empty["generated"] is False and "no gated evidence" in empty["reason"]

    # populate the gated substrate, then synthesize
    client.post("/api/admin/evidence/scan/news/v7")
    client.post("/api/admin/trends/scan/v7")
    client.post("/api/admin/evidence/scan/benchmarks/v7")
    client.post("/api/admin/evidence/scan/vendor/v7")
    gen = client.post("/api/admin/digest/generate", json={}).json()
    assert gen["generated"] is True and gen["inputs"] > 0 and gen["priorities"] >= 3

    d = client.get("/api/digest").json()
    assert d["generated"] and d["quarter"] == gen["quarter"]
    assert d["claim_label"] == "INFERENCE" and d["chain"]  # trust envelope
    assert d["summary"] and d["theme"].startswith("Cross-pillar theme")
    assert d["cadence"]["cron"] == "0 10 1 1,4,7,10 *"  # quarterly, from config
    assert len(d["priorities"]) >= 3
    for p in d["priorities"]:
        assert p["pillar"] in ("P1", "P2", "P3", "P4") and p["title"] and p["body"]
        assert p["adversary_verdict"].startswith(("Survives", "Caveat"))
    # corroborated and thin signal are BOTH represented honestly in the fixture-driven run
    verdicts = " ".join(p["adversary_verdict"] for p in d["priorities"])
    assert "Survives" in verdicts

    # the synthesis chain is grounded + cited (G5/G7) and resolvable
    chain = client.get(f"/api/reasoning/{d['chain']}").json()
    assert chain["verdict"] == "pass"
    assert any("GATED substrate" in s["text"] for s in chain["steps"])

    # regenerate is idempotent per quarter: still ONE digest for the quarter
    client.post("/api/admin/digest/generate", json={})
    assert client.get("/api/digest").json()["quarters"].count(gen["quarter"]) == 1

    # export signs; verify passes; REGENERATION invalidates the old signature (tamper-evident)
    exp = client.post("/api/exports/digest", json={}).json()
    assert exp["exported"] and exp["hmac_sig"] and exp["artifact"]["quarter"] == gen["quarter"]
    ver = client.get(f"/api/exports/{exp['export_id']}/verify").json()
    assert ver["valid"] is True
    client.post("/api/admin/digest/generate", json={})
    assert client.get(f"/api/exports/{exp['export_id']}/verify").json()["valid"] is False
    fresh = client.post("/api/exports/digest", json={}).json()
    assert client.get(f"/api/exports/{fresh['export_id']}/verify").json()["valid"] is True
    # the read model surfaces the latest export state
    assert client.get("/api/digest").json()["export"]["valid"] is True

    # unknown export id -> 404 envelope; malformed -> 422
    assert client.get("/api/exports/00000000-0000-0000-0000-000000000000/verify").status_code == 404
    assert client.get("/api/exports/nope/verify").status_code == 422
