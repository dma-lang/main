"""F2: Vendor intelligence — weekly developments -> eight typed events -> subcap impact.

Pure-unit coverage of the deterministic helpers, plus a DB-backed end-to-end run: the hermetic
scan types the recorded fixture, maps gated events onto the provisioned catalogue, queues the
honesty paths (untypable -> review; unknown vendor -> registry flag; deprecation-vs-delivery ->
G6) and the consultant loop enforces the G3 tier floor (T5 refused, T3 stages).
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app import db
from app.main import create_app
from app.services import provision
from app.services import stories as story_svc
from app.services import vendors as vn

needs_db = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"), reason="DATABASE_URL not set (DB-backed test)"
)


# --------------------------------------------------------------------------- pure unit tests


def test_slug_is_stable() -> None:
    assert vn._slug("Salesforce / MuleSoft") == "VEN-salesforce-mulesoft"
    assert vn._slug("Okta Inc.") == "VEN-okta-inc"


def test_recency_weight_decays() -> None:
    now = datetime(2026, 6, 10, tzinfo=UTC)
    assert vn._recency_weight(now - timedelta(days=10), now) == 1.0
    assert vn._recency_weight(now - timedelta(days=60), now) == 0.85
    assert vn._recency_weight(now - timedelta(days=150), now) == 0.6
    assert vn._recency_weight(now - timedelta(days=400), now) == 0.4


def test_type_magnitudes_cover_all_eight() -> None:
    assert set(vn._TYPE_MAG) == set(vn._TYPE_LABEL)
    assert vn._TYPE_MAG["deprecation"] == "HIGH" and vn._TYPE_MAG["executive_move"] == "LOW"


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
            await conn.execute(text("DELETE FROM control.suggestion"))
            await conn.execute(text("DELETE FROM control.change_flag"))
            await conn.execute(text("DELETE FROM control.validation_gate_run"))
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
            await conn.execute(text("DELETE FROM control.reasoning_chain"))
            await conn.execute(
                text(
                    "DELETE FROM control.ers WHERE evidence_id IN "
                    "(SELECT evidence_id FROM control.evidence_item "
                    "WHERE kind IN ('vendor_event', 'catalogue'))"
                )
            )
            await conn.execute(
                text(
                    "DELETE FROM control.evidence_item "
                    "WHERE kind IN ('vendor_event', 'catalogue')"
                )
            )
            await conn.execute(text("DELETE FROM control.ingest_run WHERE source = 'vendor'"))
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
def test_vendor_scan_and_contract(client: TestClient) -> None:
    scanned = client.post("/api/admin/evidence/scan/vendor/v7").json()
    # 12 fetched: 9 map; the untypable founder letter lands in review (never mis-typed); the two
    # nCino deprecations contradict heavy live delivery (G6) and queue; Anthropic raises a
    # registry flag (and still ingests)
    assert scanned["fetched"] == 12 and scanned["created"] == 12
    assert scanned["mapped"] == 9 and scanned["review"] == 1 and scanned["flagged"] == 2
    assert scanned["registry_flags"] == 1

    rescan = client.post("/api/admin/evidence/scan/vendor/v7").json()
    assert rescan["created"] == 0 and rescan["deduped"] == 12  # idempotent, typing never re-run

    body = client.get("/api/evidence?kind=vendor_event").json()
    items = body["items"]
    assert len(items) == scanned["mapped"]  # gate-failed/review events are NOT listed as mapped
    assert body["scan"]["cadence"] == "weekly" and body["scan"]["cron"] == "0 7 * * MON"
    # seven of the eight classes map (both deprecations queued at G6)
    assert {t["v"] for t in body["types"]} == {
        "product_launch",
        "partnership",
        "pricing_change",
        "executive_move",
        "security_incident",
        "regulatory_action",
        "case_study",
    }
    for i in items:
        assert i["tier"] in ("T3", "T4", "T5")  # vendor signal is honestly low-tier
        assert i["label"] in ("FACT", "INFERENCE", "HYPOTHESIS")
        assert i["mag"] in ("HIGH", "MEDIUM", "LOW")
        assert set(i["source"]) == {"name", "type", "tier", "url", "ers", "fetched_at"}
        assert i["affects"] and i["chain"]

    # vendor profiles: every vendor with a mapped event gets a card; catalogue platform counts
    profiles = {p["name"]: p for p in body["vendors"]}
    assert profiles["Salesforce"]["platforms"] > 0  # known catalogue vendor
    assert profiles["Anthropic"]["platforms"] == 0  # unknown vendor — registry-flagged
    assert all(p["developments_90d"] >= 1 and p["subcaps_touched"] >= 1 for p in profiles.values())

    # the heatmap is evidence-driven (frequency x recency), every cell scored and named
    assert body["heat"] and all(c["score"] > 0 and c["vendor"] and c["name"] for c in body["heat"])

    # server-side event-type filter
    sec = client.get("/api/evidence?kind=vendor_event&event_type=security_incident").json()
    assert sec["items"] and all(i["event_type"] == "security_incident" for i in sec["items"])

    # honesty queues: untypable -> review flag; deprecation-vs-delivery -> G6; unknown vendor ->
    # registry flag — never dropped, never mis-typed, never silently mapped
    flags = client.get("/api/change-flags?status=open").json()["flags"]
    titles = " | ".join(f["title"] for f in flags)
    assert "could not be typed" in titles
    assert "failed G6" in titles
    assert "not in the catalogue registry: Anthropic" in titles


@needs_db
def test_vendor_loop_enforces_tier_floor(client: TestClient) -> None:
    client.post("/api/admin/evidence/scan/vendor/v7")
    items = client.get("/api/evidence?kind=vendor_event").json()["items"]
    t3 = next(i for i in items if i["tier"] == "T3")
    t5 = next(i for i in items if i["tier"] == "T5")

    # independent T3 coverage stages a gated suggestion
    loop = client.post(f"/api/evidence/vendor/{t3['id']}/loop").json()
    assert loop["staged"] is True and loop["target"]
    assert client.post(f"/api/evidence/vendor/{t3['id']}/loop").json()["status"] == "duplicate"
    # vendor-published T5 signal alone is refused at the G3 floor
    refused = client.post(f"/api/evidence/vendor/{t5['id']}/loop").json()
    assert refused["staged"] is False and refused["status"] == "refused"
    assert "G3" in (refused["reason"] or "")


@needs_db
def test_disabled_source_scan_refuses_with_409(client: TestClient) -> None:
    # the persisted registry switch is ENFORCED: a disabled source refuses to scan, readably
    assert client.patch("/api/admin/sources/vendor", json={"enabled": False}).json()["ok"]
    r = client.post("/api/admin/evidence/scan/vendor/v7")
    assert r.status_code == 409
    assert "disabled in the source registry" in r.json()["error"]["message"]
    assert client.patch("/api/admin/sources/vendor", json={"enabled": True}).json()["enabled"]
    assert client.post("/api/admin/evidence/scan/vendor/v7").status_code == 200
