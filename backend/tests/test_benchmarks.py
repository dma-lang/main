"""F7: Benchmarks studio (D4) — monthly ingest -> bootstrap CI -> adversarial verdict.

Pure-unit coverage of the deterministic CI maths and config, plus a DB-backed end-to-end run:
the hermetic scan ingests the curated fixture, maps each panel onto the provisioned catalogue,
and the read model serves the spec contract (observations + CI band + adversary verdict +
reasoning) with the honesty rails — thin coverage suppresses the band and shows the gap, a
missing methodology renders "not documented", an EXPLORATORY benchmark refuses the loop.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app import db
from app.intelligence import gates
from app.main import create_app
from app.services import benchmarks as bm
from app.services import provision
from app.services import stories as story_svc

needs_db = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"), reason="DATABASE_URL not set (DB-backed test)"
)


# --------------------------------------------------------------------------- pure unit tests


def test_benchmarks_config_valid() -> None:
    cfg = gates.benchmarks_config()
    assert cfg.min_observations >= 1
    assert cfg.bootstrap_resamples >= 100
    assert 0 < cfg.ci_level < 1


def test_bootstrap_ci_is_deterministic_and_ordered() -> None:
    obs = [14.0, 16.5, 18.0, 19.5, 21.0, 22.3, 23.7, 25.5, 27.0, 29.4]
    a = bm.bootstrap_ci(obs, resamples=500, ci_level=0.95, seed="m|10")
    b = bm.bootstrap_ci(obs, resamples=500, ci_level=0.95, seed="m|10")
    assert a == b, "seeded bootstrap must reproduce bit-for-bit (idempotent re-scan)"
    lo, hi = a
    assert lo <= hi
    assert min(obs) <= lo and hi <= max(obs)  # the median's CI lives inside the data range
    # a different seed shifts the resamples (still inside the range)
    c = bm.bootstrap_ci(obs, resamples=500, ci_level=0.95, seed="other|10")
    assert min(obs) <= c[0] <= c[1] <= max(obs)


def test_quartiles_ordered() -> None:
    p25, p50, p75 = bm.quartiles([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0])
    assert p25 < p50 < p75
    assert p50 == 4.5


def test_verdict_maps_to_claim_label() -> None:
    # the adversary verdict drives the claim label; anything unknown/pending stays HYPOTHESIS
    assert bm._VERDICT_LABEL["BENCHMARK"] == "FACT"
    assert bm._VERDICT_LABEL["INDICATIVE"] == "INFERENCE"
    assert bm._VERDICT_LABEL["EXPLORATORY"] == "HYPOTHESIS"
    assert bm._VERDICT_LABEL.get("anything-else", "HYPOTHESIS") == "HYPOTHESIS"


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
            await conn.execute(text("DELETE FROM control.benchmark"))
            await conn.execute(text("DELETE FROM control.reasoning_chain"))
            await conn.execute(
                text(
                    "DELETE FROM control.ers WHERE evidence_id IN "
                    "(SELECT evidence_id FROM control.evidence_item "
                    "WHERE kind IN ('benchmark', 'catalogue'))"
                )
            )
            await conn.execute(
                text("DELETE FROM control.evidence_item WHERE kind IN ('benchmark', 'catalogue')")
            )
            await conn.execute(text("DELETE FROM control.ingest_run WHERE source = 'benchmarks'"))
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
def test_benchmark_scan_and_contract(client: TestClient) -> None:
    scanned = client.post("/api/admin/evidence/scan/benchmarks/v7").json()
    assert scanned["fetched"] == 4 and scanned["created"] == 4 and scanned["deduped"] == 0
    assert scanned["mapped"] == 4 and scanned["flagged"] == 0

    # idempotent re-scan: dedupe on (source, metric); the adversary is never re-run
    rescan = client.post("/api/admin/evidence/scan/benchmarks/v7").json()
    assert rescan["created"] == 0 and rescan["deduped"] == 4

    body = client.get("/api/evidence?kind=benchmark").json()
    items = body["items"]
    assert len(items) == 4
    # the monthly cadence indicator comes from config/schedules.yaml
    assert body["scan"]["cadence"] == "monthly" and body["scan"]["cron"] == "0 8 1 * *"
    assert set(body["segments"]) == {"BK", "CL"}

    cfg = gates.benchmarks_config()
    for b in items:
        # spec contract: observations, the CI band, the adversary verdict and reasoning
        assert b["observations"] and b["n"] == len(b["observations"])
        assert b["p25"] <= b["p50"] <= b["p75"]
        assert b["verdict"] in ("BENCHMARK", "INDICATIVE", "EXPLORATORY", "pending")
        assert b["verdict_note"] and b["chain"]
        # trust envelope is complete
        assert b["label"] in ("FACT", "INFERENCE", "HYPOTHESIS")
        assert b["tier"] == "T2" and 0 < b["ers"] <= 1
        assert set(b["source"]) == {"name", "type", "tier", "url", "ers", "fetched_at"}
        assert b["affects"], "a mapped benchmark names its affected subcaps"
        # thin coverage suppresses the band — no false precision, the gap is named
        if b["n"] < cfg.min_observations:
            assert b["thin"] and b["ci_low"] is None and b["ci_high"] is None
            assert b["coverage_note"] and str(cfg.min_observations) in b["coverage_note"]
        else:
            assert not b["thin"] and b["ci_low"] is not None and b["ci_high"] is not None
            assert b["ci_low"] <= b["p50"] <= b["ci_high"]

    # the honesty rails are present in the fixture: one thin panel, one undocumented methodology
    assert any(b["thin"] for b in items)
    assert any(b["methodology"] == "not documented" for b in items)
    thin = next(b for b in items if b["thin"])
    assert thin["verdict"] == "EXPLORATORY" and thin["label"] == "HYPOTHESIS"

    # the chain explains the band and records the adversary critique verbatim
    strong = next(b for b in items if b["verdict"] == "BENCHMARK")
    chain = client.get(f"/api/reasoning/{strong['chain']}").json()
    assert chain["verdict"] == "pass"
    assert any(s["kind"] == "adversarial" for s in chain["steps"])
    assert any("bootstrap 95% CI" in s["text"] for s in chain["steps"])

    # segment filter is server-side
    cl = client.get("/api/evidence?kind=benchmark&segment=CL").json()["items"]
    assert len(cl) == 1 and cl[0]["segment"] == "CL"


@needs_db
def test_benchmark_loop_gated_and_honest(client: TestClient) -> None:
    client.post("/api/admin/evidence/scan/benchmarks/v7")
    items = client.get("/api/evidence?kind=benchmark").json()["items"]
    strong = next(b for b in items if b["verdict"] == "BENCHMARK")
    thin = next(b for b in items if b["thin"])

    # a defensible benchmark stages a gated suggestion (never a live edit)
    loop = client.post(f"/api/evidence/benchmark/{strong['id']}/loop").json()
    assert loop["staged"] is True and loop["kind"] == "descriptor_update" and loop["target"]
    sug = client.get("/api/suggestions?status=pending").json()
    assert any(x["suggestion_id"] == loop["suggestion_id"] for x in sug)
    # idempotent: re-running is a duplicate, not a second suggestion
    assert client.post(f"/api/evidence/benchmark/{strong['id']}/loop").json()["status"] == (
        "duplicate"
    )
    # an EXPLORATORY benchmark refuses — the adversary found the band unsupportable
    refused = client.post(f"/api/evidence/benchmark/{thin['id']}/loop").json()
    assert refused["staged"] is False and refused["status"] == "refused"
    assert "EXPLORATORY" in (refused["reason"] or "")
