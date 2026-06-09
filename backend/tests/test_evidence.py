"""F7 increment 1: the News watch (D1) — ingest -> enrich -> map -> gate -> persist.

DB-backed, self-cleaning. A hermetic scan fetches the deterministic fixture of real public
sources, maps each item onto the provisioned v7 catalogue via stored-evidence retrieval, gates it
(G1/G3/G5/G6/G7), and persists the full trust envelope. A gate-failing item is queued to Change
Flags — never dropped, never shown as mapped. The consultant loop stages a GATED suggestion only;
apply re-gates server-side and mutates cat_<v> + audit_log in one transaction.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app import db
from app.intelligence import gates
from app.jobs import schedule
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
            # FK-safe order: suggestion/flag/gate-run/impact reference chains; chains cascade
            # steps + citations; news_item -> evidence_item; ers -> evidence_item.
            await conn.execute(text("DELETE FROM control.suggestion"))
            await conn.execute(text("DELETE FROM control.change_flag"))
            await conn.execute(text("DELETE FROM control.validation_gate_run"))
            await conn.execute(
                text(
                    "DELETE FROM control.news_subcap_impact WHERE news_id IN "
                    "(SELECT news_id FROM control.news_item)"
                )
            )
            await conn.execute(text("DELETE FROM control.reasoning_chain"))
            await conn.execute(
                text(
                    "DELETE FROM control.news_item WHERE evidence_id IN "
                    "(SELECT evidence_id FROM control.evidence_item WHERE kind = 'news')"
                )
            )
            await conn.execute(
                text(
                    "DELETE FROM control.ers WHERE evidence_id IN "
                    "(SELECT evidence_id FROM control.evidence_item WHERE kind = 'news')"
                )
            )
            await conn.execute(
                text("DELETE FROM control.evidence_item WHERE kind IN ('news', 'catalogue')")
            )
            await conn.execute(text("DELETE FROM control.ingest_run WHERE source = 'news'"))
            await conn.execute(
                text("DELETE FROM control.audit_log WHERE action LIKE 'suggestion%'")
            )
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


def _gate_run_count() -> int:
    sync_eng = create_engine(os.environ["DATABASE_URL"].replace("+asyncpg", "+psycopg"))
    with sync_eng.connect() as conn:
        n = conn.execute(text("SELECT count(*) FROM control.validation_gate_run")).scalar()
    sync_eng.dispose()
    return int(n or 0)


@needs_db
def test_news_scan_and_read_model(client: TestClient) -> None:
    scanned = client.post("/api/admin/evidence/scan/news/v7").json()
    assert scanned["fetched"] == 6 and scanned["created"] == 6 and scanned["deduped"] == 0
    # every fetched item is accounted for: mapped or queued to review — never dropped
    assert scanned["mapped"] + scanned["flagged"] == 6
    assert scanned["flagged"] >= 1  # the retire-vs-delivery contradiction (G6)

    # idempotent re-scan: dedupe on (source, headline), nothing duplicated
    rescan = client.post("/api/admin/evidence/scan/news/v7").json()
    assert rescan["created"] == 0 and rescan["deduped"] == 6

    body = client.get("/api/evidence?kind=news").json()
    items = body["items"]
    assert len(items) == scanned["mapped"]  # gate-failed items are NOT listed as mapped
    first = items[0]
    # newest first; full trust envelope on every AI value
    assert first["title"].startswith("Fed publishes")
    assert set(first["source"]) == {"name", "type", "tier", "url", "ers", "fetched_at"}
    for i in items:
        assert i["mag"] in ("HIGH", "MEDIUM", "LOW")
        assert i["tier"] in ("T1", "T2", "T3", "T4", "T5")
        assert i["label"] in ("FACT", "INFERENCE", "HYPOTHESIS")
        assert 0.0 < i["reliability"] <= 1.0 and 0.0 < i["source"]["ers"] <= 1.0
        assert i["chain"]  # reasoning backlink is mandatory
        assert i["affects"], "a mapped item must name its affected subcaps"
        for sub_id, score, name, mag in i["affects"]:
            assert sub_id and name and 0.0 < score <= 1.0 and mag in ("HIGH", "MEDIUM", "LOW")

    # the weekly cadence indicator comes from config/schedules.yaml — never implies real-time
    assert body["scan"]["cadence"] == "weekly" and body["scan"]["cron"] == "0 6 * * MON"
    assert body["scan"]["last_scan"] and body["scan"]["next_scan"]
    assert {o["v"] for o in body["impacts"]} == {
        "descriptor_revision",
        "new_use_case",
        "net_new_subcap",
        "watchlist",
    }

    # server-side filters
    t1 = client.get("/api/evidence?kind=news&tier=T1").json()["items"]
    assert len(t1) == 3 and all(i["tier"] == "T1" for i in t1)
    dr = client.get("/api/evidence?kind=news&impact=descriptor_revision").json()["items"]
    assert len(dr) == 2 and all(i["impact"] == "descriptor_revision" for i in dr)

    # only the wired kind is served
    r = client.get("/api/evidence?kind=sow_chunk")
    assert r.status_code == 400 and "sow_chunk" in r.json()["error"]["message"]


@needs_db
def test_gate_failed_item_queued_not_dropped(client: TestClient) -> None:
    flags = client.get("/api/change-flags?status=open").json()["flags"]
    evf = [f for f in flags if f["kind"] == "evidence_gate_failure"]
    assert len(evf) == 1
    f = evf[0]
    assert f["gate_failed"] == "G6_contradiction"  # retire claim vs 200+ delivered stories
    assert f["sev"] == "MED"  # T2 source; T1 would be HIGH
    assert f["target"].startswith("news:")
    assert "Forrester" in f["title"]

    # the failing gate run is on the record (Gates log lights up), chain backlink intact
    chain = client.get(f"/api/reasoning/{f['chain']}").json()
    assert chain["verdict"] == "fail"
    g6 = next(c for c in chain["checks"] if c["name"] == "G6_contradiction")
    assert g6["state"] == "Needs review"

    # approve has no lifecycle correction to apply for an evidence flag: it stays open with
    # the failing gate named, and NO re-gate run is written
    runs_before = _gate_run_count()
    res = client.post(f"/api/change-flags/{f['id']}/approve").json()
    assert res["resolved"] is False and res["status"] == "open"
    assert res["gate_failed"] == "G6_contradiction"
    assert _gate_run_count() == runs_before

    # a gate-failed item cannot seed a suggestion either
    news_id = f["target"].removeprefix("news:")
    loop = client.post(f"/api/evidence/news/{news_id}/loop").json()
    assert loop["staged"] is False and loop["status"] == "refused"
    assert "Change Flags" in loop["reason"]


@needs_db
def test_consultant_loop_stages_gated_suggestions(client: TestClient) -> None:
    items = client.get("/api/evidence?kind=news").json()["items"]
    by_impact = {i["impact"]: i for i in items}

    # monitored-only and taxonomy-shaping classes are refused, with the reason stated
    watch = client.post(f"/api/evidence/news/{by_impact['watchlist']['id']}/loop").json()
    assert watch["staged"] is False and "monitored only" in watch["reason"]
    net_new = client.post(f"/api/evidence/news/{by_impact['net_new_subcap']['id']}/loop").json()
    assert net_new["staged"] is False and "mapping studio" in net_new["reason"]

    # descriptor_revision -> a pending descriptor_update suggestion (never a live edit)
    fed = next(i for i in items if i["source"]["name"] == "Federal Reserve")
    staged = client.post(f"/api/evidence/news/{fed['id']}/loop").json()
    assert staged["staged"] is True and staged["kind"] == "descriptor_update"
    target = staged["target"]
    dup = client.post(f"/api/evidence/news/{fed['id']}/loop").json()
    assert dup["staged"] is False and dup["status"] == "duplicate"

    pending = client.get("/api/suggestions?status=pending").json()
    row = next(s for s in pending if s["suggestion_id"] == staged["suggestion_id"])
    assert row["kind"] == "descriptor_update" and row["claim_label"] == "INFERENCE"
    assert row["source_tier"] == "T1" and row["chain_id"]

    # apply re-gates server-side, mutates cat_<v>.subcap.description + audit, atomically
    before = client.get(f"/api/catalogue/v7/subcaps/{target}").json()["description"]
    applied = client.post(f"/api/suggestions/{staged['suggestion_id']}/apply").json()
    assert applied["applied"] is True
    after = client.get(f"/api/catalogue/v7/subcaps/{target}").json()["description"]
    assert after != before and "2026 update (Federal Reserve, T1)" in after

    # new_use_case -> a pending new_use_case suggestion; apply INSERTs into cat_<v>.use_case
    uc_staged = client.post(f"/api/evidence/news/{by_impact['new_use_case']['id']}/loop").json()
    assert uc_staged["staged"] is True and uc_staged["kind"] == "new_use_case"
    uc_applied = client.post(f"/api/suggestions/{uc_staged['suggestion_id']}/apply").json()
    assert uc_applied["applied"] is True and uc_applied["after"].startswith("UC-NEWS-")

    sync_eng = create_engine(os.environ["DATABASE_URL"].replace("+asyncpg", "+psycopg"))
    with sync_eng.connect() as conn:
        uc = conn.execute(
            text("SELECT subcap_id, archetype FROM cat_v7.use_case " "WHERE use_case_id = :id"),
            {"id": uc_applied["after"]},
        ).first()
        audits = conn.execute(
            text(
                "SELECT meta->>'field' FROM control.audit_log "
                "WHERE action = 'suggestion.apply' ORDER BY at"
            )
        ).scalars()
        fields = list(audits)
    sync_eng.dispose()
    assert uc is not None and uc[0] == uc_staged["target"] and uc[1] == "Emerging"
    assert "description" in fields and "use_case" in fields


def test_evaluate_evidence_gates() -> None:
    ok, verdict = gates.evaluate_evidence(
        targets_exist=True, source_tier="T1", retrieval_count=3, cited=True, contradicts=False
    )
    assert verdict == "pass" and set(ok) == {
        "G1_identity_schema",
        "G3_source_tier_floor",
        "G5_similarity_grounding",
        "G6_contradiction",
        "G7_citation_verification",
    }
    low_tier, verdict = gates.evaluate_evidence(
        targets_exist=True, source_tier="T4", retrieval_count=3, cited=True, contradicts=False
    )
    assert verdict == "fail" and gates.first_failing(low_tier) == "G3_source_tier_floor"
    contradicted, verdict = gates.evaluate_evidence(
        targets_exist=True, source_tier="T2", retrieval_count=3, cited=True, contradicts=True
    )
    assert verdict == "fail" and gates.first_failing(contradicted) == "G6_contradiction"


def test_next_run_cron_forms() -> None:
    tue = datetime(2026, 6, 9, 12, 0, tzinfo=UTC)  # a Tuesday
    assert schedule.next_run("0 6 * * MON", tue) == datetime(2026, 6, 15, 6, 0, tzinfo=UTC)
    # same weekday before the hour fires today; after the hour fires next week
    mon_early = datetime(2026, 6, 15, 5, 0, tzinfo=UTC)
    assert schedule.next_run("0 6 * * MON", mon_early) == datetime(2026, 6, 15, 6, 0, tzinfo=UTC)
    mon_late = datetime(2026, 6, 15, 7, 0, tzinfo=UTC)
    assert schedule.next_run("0 6 * * MON", mon_late) == datetime(2026, 6, 22, 6, 0, tzinfo=UTC)
    # monthly, month-list, hourly, daily
    assert schedule.next_run("0 5 1 * *", tue) == datetime(2026, 7, 1, 5, 0, tzinfo=UTC)
    assert schedule.next_run("0 5 1 1,4,7,10 *", tue) == datetime(2026, 7, 1, 5, 0, tzinfo=UTC)
    assert schedule.next_run("15 * * * *", tue.replace(minute=30)) == datetime(
        2026, 6, 9, 13, 15, tzinfo=UTC
    )
    assert schedule.next_run("30 4 * * *", tue) == datetime(2026, 6, 10, 4, 30, tzinfo=UTC)
    with pytest.raises(ValueError):
        schedule.next_run("bad cron")
