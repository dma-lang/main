"""F7: Trends monitor (D2) — multi-signal detection over the 8-week evidence window.

Pure-unit coverage of the deterministic signal maths, clustering and gates (no DB), plus a
DB-backed end-to-end run: a hermetic news scan feeds gated evidence, detection clusters the AI
model-risk block into one earned trend (the single-theme items stay singletons and are filtered),
and the trust envelope + drilldown + feedback + consultant loop all resolve.
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
from app.intelligence import gates
from app.main import create_app
from app.services import provision
from app.services import stories as story_svc
from app.services import trends as ts

needs_db = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"), reason="DATABASE_URL not set (DB-backed test)"
)


# --------------------------------------------------------------------------- pure unit tests


def test_trends_config_valid() -> None:
    cfg = gates.trends_config()
    assert abs((cfg.velocity + cfg.diversity + cfg.novelty + cfg.persistence) - 1.0) < 1e-9
    assert 0 < cfg.emergent_cut <= 1 and 0 <= cfg.trend_threshold <= 1
    assert cfg.min_cluster >= 1 and cfg.min_sources >= 1
    # the composite blends exactly the four weighted signals
    assert cfg.score(1.0, 0.0, 0.0, 0.0) == round(cfg.velocity, 3)
    assert cfg.score(1.0, 1.0, 1.0, 1.0) == 1.0


def test_velocity_is_recent_burst() -> None:
    assert ts._velocity([4, 5, 6, 7]) == 1.0  # all in the recent half -> burst
    assert ts._velocity([0, 1, 2, 3]) == 0.0  # all old -> no burst
    assert ts._velocity([0, 4]) == 0.5
    assert ts._velocity([]) == 0.0


def test_diversity_is_tier_weighted() -> None:
    # one low-tier source repeated is NOT diverse (single distinct source)
    assert ts._diversity({"blog": "T5"}, 3) < 0.2
    # three independent T1 regulators clear the floor strongly
    assert ts._diversity({"a": "T1", "b": "T1", "c": "T1"}, 3) == 0.95
    # five mixed-tier sources saturate (clamped at 1.0)
    assert ts._diversity({s: "T1" for s in "abcde"}, 3) == 1.0


def test_persistence_counts_distinct_weeks() -> None:
    assert ts._persistence([3, 3, 3]) == round(1 / 8, 3)  # a one-week spike fades
    assert ts._persistence([1, 2, 3, 4]) == round(4 / 8, 3)  # sustained strengthens


def _cluster(impacts: list[str], scores: dict[str, float]) -> ts._Cluster:
    return ts._Cluster(
        evidence_ids=["e"],
        news_ids=["n"],
        sources={"s": "T1"},
        impacts=impacts,
        weeks=[5],
        ers_values=[0.9],
        subcap_scores=scores,
        subcap_names={k: k for k in scores},
    )


def test_novelty_low_when_grounded_high_when_net_new() -> None:
    cfg = gates.trends_config()
    # a well-mapped revision cluster is near the catalogue -> low novelty, not emergent
    grounded = _cluster(["descriptor_revision"], {"P4C2.5.3": 0.85})
    assert ts._novelty(grounded) == 0.15
    assert ts._novelty(grounded) <= cfg.emergent_cut
    # a net-new-dominated cluster is far -> high novelty, flagged emergent
    netnew = _cluster(["net_new_subcap", "net_new_subcap"], {"P1C1.1.1": 0.6})
    assert ts._novelty(netnew) == 1.0
    assert ts._novelty(netnew) > cfg.emergent_cut


def test_cluster_evidence_unions_on_shared_subcap() -> None:
    now = datetime(2026, 6, 10, tzinfo=UTC)
    items = [
        {
            "news_id": n,
            "evidence_id": n,
            "source": n,
            "tier": "T1",
            "impact": "descriptor_revision",
            "published_at": now,
            "ers": 0.9,
        }
        for n in ("a", "b", "c")
    ]
    impacts = {
        "a": [{"subcap_id": "P4C2.5.3", "score": 0.8, "name": "x"}],
        "b": [{"subcap_id": "P4C2.5.3", "score": 0.7, "name": "x"}],  # shares with a
        "c": [{"subcap_id": "P9C9.9.9", "score": 0.7, "name": "z"}],  # disjoint
    }
    clusters = ts._cluster_evidence(items, impacts, now)
    sizes = sorted(len(c.evidence_ids) for c in clusters)
    assert sizes == [1, 2]  # {a,b} cluster on the shared subcap; c is a singleton


def test_evaluate_trend_gates() -> None:
    cfg = gates.trends_config()
    ok, verdict = gates.evaluate_trend(
        cluster_size=5,
        distinct_sources=5,
        best_tier="T1",
        min_cluster=cfg.min_cluster,
        min_sources=cfg.min_sources,
        contradicts=False,
    )
    assert verdict == "pass" and all(g["verdict"] == "pass" for g in ok.values())
    # thin cluster fails G2; single-source fails G3; a delivery contradiction fails G6
    thin, v2 = gates.evaluate_trend(
        cluster_size=2,
        distinct_sources=2,
        best_tier="T1",
        min_cluster=4,
        min_sources=3,
        contradicts=False,
    )
    assert v2 == "fail" and gates.first_failing(thin) == "G2_evidence_sufficiency"
    one_src, v3 = gates.evaluate_trend(
        cluster_size=5,
        distinct_sources=1,
        best_tier="T1",
        min_cluster=4,
        min_sources=3,
        contradicts=False,
    )
    assert v3 == "fail" and one_src["G3_source_tier_floor"]["verdict"] == "fail"
    contra, v6 = gates.evaluate_trend(
        cluster_size=5,
        distinct_sources=5,
        best_tier="T1",
        min_cluster=4,
        min_sources=3,
        contradicts=True,
    )
    assert v6 == "fail" and contra["G6_contradiction"]["verdict"] == "fail"


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
            await conn.execute(text("DELETE FROM control.trend_subcap"))
            await conn.execute(text("DELETE FROM control.trend"))
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
            await conn.execute(
                text("DELETE FROM control.ingest_run WHERE source IN ('news', 'trends')")
            )
            await conn.execute(text("DELETE FROM control.audit_log WHERE action LIKE 'trend%'"))
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
def test_trend_detection_pipeline(client: TestClient) -> None:
    client.post("/api/admin/evidence/scan/news/v7")  # gated evidence feeds detection
    stats = client.post("/api/admin/trends/scan/v7").json()
    # one multi-source trend is earned; the single-theme items stay singletons and are filtered
    assert stats["detected"] == 1 and stats["staged"] == 1 and stats["filtered"] >= 1

    body = client.get("/api/trends").json()
    assert body["counts"] == {"staged": 1}
    assert body["scan"]["cadence"] == "weekly" and body["scan"]["cron"] == "30 6 * * MON"
    trend = body["items"][0]

    # the four-signal breakdown is present and the composite is the configured weighted blend
    cfg = gates.trends_config()
    s = trend["signals"]
    expected = cfg.score(s["velocity"], s["diversity"], s["novelty"], s["persistence"])
    assert abs(trend["score"] - expected) < 1e-6 and trend["score"] >= cfg.trend_threshold
    # a corroborated, well-grounded trend: >= min_cluster evidence, multi-source, not emergent
    assert trend["evidence_count"] >= cfg.min_cluster
    assert trend["emergent"] is False and trend["label_claim"] == "INFERENCE"
    # trust envelope is complete (no opaque values)
    assert trend["tier"] in ("T1", "T2", "T3") and 0.0 < trend["ers"] <= 1.0 and trend["chain"]
    assert trend["affects"], "a trend names the subcaps it maps onto"

    # reasoning chain: G2/G3/G6 all pass; the signal weighing and emergent decision are explained
    chain = client.get(f"/api/reasoning/{trend['chain']}").json()
    assert chain["verdict"] == "pass"
    assert {c["name"] for c in chain["checks"]} == {
        "G2_evidence_sufficiency",
        "G3_source_tier_floor",
        "G6_contradiction",
    }
    assert any("emergent cut" in st["text"] for st in chain["steps"])

    # evidence-cluster drilldown lists the gated items behind the trend, each with its source
    drill = client.get(f"/api/trends/{trend['id']}/evidence").json()
    assert drill["evidence_count"] == trend["evidence_count"]
    assert len(drill["evidence"]) == trend["evidence_count"]
    assert all(e["source"] and e["tier"] for e in drill["evidence"])


@needs_db
def test_trend_idempotent_and_decided_not_resurfaced(client: TestClient) -> None:
    client.post("/api/admin/evidence/scan/news/v7")
    client.post("/api/admin/trends/scan/v7")
    # re-detection without analyst action is re-derivable: still exactly one staged trend
    again = client.post("/api/admin/trends/scan/v7").json()
    assert again["detected"] == 1
    assert len(client.get("/api/trends").json()["items"]) == 1

    # an analyst decision sticks: promote, then re-scan must NOT resurface the same cluster
    tid = client.get("/api/trends").json()["items"][0]["id"]
    assert client.post(f"/api/trends/{tid}/feedback", json={"verdict": "promote"}).json()["ok"]
    rescan = client.post("/api/admin/trends/scan/v7").json()
    assert rescan["detected"] == 0 and rescan["decided"] == 1
    counts = client.get("/api/trends").json()["counts"]
    assert counts == {"promoted": 1}  # one trend, not a promoted + a fresh staged duplicate


@needs_db
def test_trend_consultant_loop_stages_gated_suggestion(client: TestClient) -> None:
    client.post("/api/admin/evidence/scan/news/v7")
    client.post("/api/admin/trends/scan/v7")
    tid = client.get("/api/trends").json()["items"][0]["id"]

    loop = client.post(f"/api/trends/{tid}/loop").json()
    assert loop["staged"] is True and loop["kind"] == "descriptor_update" and loop["target"]
    # the staged suggestion is a gated, pending edit on D3 — never a live mutation
    sug = client.get("/api/suggestions?status=pending").json()  # a bare list of suggestions
    staged = [x for x in sug if x["suggestion_id"] == loop["suggestion_id"]]
    assert staged and staged[0]["target_subcap"] == loop["target"]
    # re-running the loop is idempotent (duplicate guard), not a second suggestion
    assert client.post(f"/api/trends/{tid}/loop").json()["status"] == "duplicate"
