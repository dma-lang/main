"""Unscoped-subvertical discovery (services/subverticals) — the gated proposal pipeline.

DB-backed, self-cleaning. The detector clusters REAL unscoped Jira delivery by client, infers a
candidate subvertical (hermetic: a deterministic, grounded provisional name; no spend), guards it
against overlap with the nine modelled subverticals, gates it G1-G8, and queues it in the
Change-Flags / Notifications inbox with the full trust envelope. Nothing auto-applies.

The v7 corpus has exactly one substantial unscoped client (PF, ~1,062 real stories) and one noise
client (HE, 1 story), so the detector proposes PF [BLOCKING] and filters HE. A fabricated
majority-classified client proves the overlap guard skips clients that are really an existing SV.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app import db
from app.intelligence import gates
from app.main import create_app
from app.services import provision, subverticals
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


def _sync_engine() -> object:
    return create_engine(os.environ["DATABASE_URL"].replace("+asyncpg", "+psycopg"))


@needs_db
def test_unscoped_subvertical_discovery_lifecycle(client: TestClient) -> None:
    """End-to-end: scan -> orange-heatmap endpoint -> Notifications -> idempotent -> approve."""
    summary = client.post("/api/admin/change-flags/scan-subverticals/v7").json()
    assert summary["candidates"] == 2  # PF (substantial) + HE (noise)
    assert summary["filtered"] >= 1  # HE is below the volume floor
    assert summary["overlapped"] == 0  # neither real client is already an existing SV

    # the mission-control drilldown endpoint: PF as an ORANGE heatmap row + full trust envelope
    drill = client.get("/api/catalogue/v7/unscoped-subverticals").json()
    assert len(drill["axis"]) == 6
    clients = {c["client"] for c in drill["candidates"]}
    assert "PF" in clients and "HE" not in clients  # PF proposed, HE filtered as noise
    pf = next(c for c in drill["candidates"] if c["client"] == "PF")
    assert pf["stories"] > 1000
    assert len(pf["cells"]) == 6 and sum(pf["cells"]) > 0  # banded delivery -> orange cells
    assert pf["claim_label"] == "HYPOTHESIS"  # an AI-proposed NEW entity is never a fact
    assert pf["source_tier"] == "T1" and (pf["ers"] or 0) > 0  # trust envelope
    assert pf["chain_id"] and pf["code"] and pf["name"]
    assert pf["top_capabilities"] and pf["overlap_sv"] and pf["overlap"] < 0.5
    # DEEP cross-check (beyond the semantic name): PF's delivered-subcap FOOTPRINT is structurally
    # compared to all nine modelled subverticals — it is genuinely DISTINCT (Jaccard to its closest
    # modelled SV is below the merge bar), so a real new subvertical, not an existing one's untagged
    # delivery.
    assert pf["distinct"] is True
    assert pf["distinct_closest_sv"] and 0 <= pf["distinct_similarity"] < 0.5
    assert pf["severity"] == "BLOCKING"  # volume-stratified (1,000+ stories)

    # it surfaces in the Notifications inbox with a reasoning backlink + a PASSING gate run
    inbox = client.get("/api/change-flags?status=open").json()["flags"]
    flag = next(f for f in inbox if f["kind"] == "unscoped_subvertical")
    assert flag["sev"] == "BLOCKING" and flag["chain"]
    chain = client.get(f"/api/reasoning/{flag['chain']}").json()
    assert chain["verdict"] == "pass"  # a gated proposal, not a gate failure
    assert len(chain["steps"]) >= 3

    # idempotent: a second scan proposes nothing new (the client is already flagged)
    again = client.post("/api/admin/change-flags/scan-subverticals/v7").json()
    assert again["created"] == 0 and again["already"] >= 1

    # approving ACKNOWLEDGES the candidate (audited); it never auto-creates a subvertical
    approved = client.post(f"/api/change-flags/{flag['id']}/approve").json()
    assert approved["resolved"] is True and approved["status"] == "approved"
    still_open = client.get("/api/change-flags?status=open").json()["flags"]
    assert not any(f["kind"] == "unscoped_subvertical" for f in still_open)

    sync_eng = _sync_engine()
    with sync_eng.connect() as conn:  # type: ignore[attr-defined]
        row = conn.execute(
            text(
                "SELECT meta FROM control.audit_log WHERE action = 'change_flag.approve' "
                "AND target_ref = 'PF' ORDER BY at DESC LIMIT 1"
            )
        ).first()
    assert row is not None and row[0].get("accepted") == "subvertical_proposal"


@needs_db
def test_unscoped_subvertical_scopes_heatmap_and_summary(client: TestClient) -> None:
    """Selecting an AI-detected unscoped subvertical (sv=unscoped:<client>) SCOPES Mission Control —
    the concentration heatmap and the pillar summary restrict to that client's unscoped delivery,
    instead of the EMPTY result a literal story_sv_code='unscoped:PF' filter would return."""
    pf_heat = client.get("/api/catalogue/v7/heatmap?lens=pillar&sv=unscoped:PF").json()
    all_heat = client.get("/api/catalogue/v7/heatmap?lens=pillar&sv=all").json()
    assert pf_heat["rows"], "unscoped scope must return rows (regression: empty when unhandled)"
    pf_total = sum(r["total"] for r in pf_heat["rows"])
    all_total = sum(r["total"] for r in all_heat["rows"])
    assert 0 < pf_total < all_total  # a real, strictly-scoped subset of delivery

    # the pillar summary (the tiles) scopes to PF's delivered subcaps, not the whole catalogue
    pf_sum = client.get("/api/catalogue/v7/summary?sv=unscoped:PF").json()
    all_sum = client.get("/api/catalogue/v7/summary?sv=all").json()
    assert 0 < pf_sum["total_subcaps"] <= all_sum["total_subcaps"]


@needs_db
def test_overlap_guard_skips_majority_classified_client(client: TestClient) -> None:
    """A client whose delivery is MOSTLY an existing subvertical is not proposed as a new one,
    even with enough unscoped volume — the overlap guard folds it into the existing SV."""
    sync_eng = _sync_engine()
    with sync_eng.begin() as conn:  # type: ignore[attr-defined]
        conn.execute(
            text(
                "INSERT INTO control.story (story_key, source_system, sub_cap_id, pillar_id, "
                "cap_name, story_sv_code, summary, composite_score, is_synthetic, project_key) "
                "SELECT 'ZZTEST-RB-'||g, 'jira', 'P1C1.1.1', 'P1', 'Test Cap', 'RB', 'rb', 3.0, "
                "false, 'ZZTEST' FROM generate_series(1, 40) g "
                "UNION ALL SELECT 'ZZTEST-UN-'||g, 'jira', 'P1C1.1.1', 'P1', 'Test Cap', NULL, "
                "'unscoped', 3.0, false, 'ZZTEST' FROM generate_series(1, 30) g"
            )
        )
    try:
        summary = client.post("/api/admin/change-flags/scan-subverticals/v7").json()
        assert summary["overlapped"] >= 1  # ZZTEST is 40 RB / 30 unscoped -> 0.57 overlap, skipped
        drill = client.get("/api/catalogue/v7/unscoped-subverticals").json()
        assert "ZZTEST" not in {c["client"] for c in drill["candidates"]}
    finally:
        with sync_eng.begin() as conn:  # type: ignore[attr-defined]
            conn.execute(text("DELETE FROM control.change_flag WHERE target_ref = 'ZZTEST'"))
            conn.execute(text("DELETE FROM control.story WHERE project_key = 'ZZTEST'"))


def test_dominant_classified_is_the_largest_existing_sv() -> None:
    """Pure unit: the client's most-classified existing subvertical drives the overlap check."""
    assert subverticals._dominant_classified({"CL": 75, "RB": 10}) == ("CL", 75)
    assert subverticals._dominant_classified({}) == (None, 0)


def test_unscoped_thresholds_come_from_config() -> None:
    """Thresholds live in config/gates.yaml (recalibrated without a deploy), not in code."""
    min_stories, overlap_max = gates.unscoped_subverticals_config()
    assert min_stories == 25 and overlap_max == 0.5
