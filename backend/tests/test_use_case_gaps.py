"""Use-case gap detector (services/use_case_gaps) — the gated NEW-use-case proposal pipeline.

DB-backed, self-cleaning (mirrors test_subverticals.py). The detector takes each subcap's carried
REAL Jira stories that its EXISTING use cases do not cover, clusters the uncovered summaries by
embedding cosine, overlap-guards each cluster against the subcap's own use cases (strict, to avoid
bloat), infers a candidate use case (hermetic: a deterministic, delivery-grounded proposal; no
spend), gates it G1-G8, and queues it in the Change-Flags / Notifications inbox with the full trust
envelope. Nothing auto-applies; approve re-gates + inserts the use case into cat_<v>.

The real v7 corpus yields plenty of natural gap clusters (many carried stories are not attributed
to a use case), so ``created >= 1`` is grounded in the corpus itself. The fixture also INJECTS a
large "already covered" cluster whose summaries echo an EXISTING use case's own name + description
on the highest-volume-uncovered subcap, so it is evaluated FIRST and must be SKIPPED by the overlap
guard — proving the strict overlap-avoidance deterministically. All injected rows are dropped with
v7.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import Connection

from app import db
from app.intelligence import gates
from app.main import create_app
from app.services import provision
from app.services import stories as story_svc

needs_db = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"), reason="DATABASE_URL not set (DB-backed test)"
)

# The "already covered" cluster is injected large so it is the top uncovered subcap (evaluated
# FIRST, before the per-scan proposal cap) — the overlap guard must skip every one of its stories.
_COVERED_STORIES = 400


def _pick_covered(conn: Connection) -> tuple[str, str, str]:
    """A subcap that HAS a use case with a real description; we echo that use case's own name +
    description as a large uncovered cluster to prove the overlap guard skips it. Returns
    (subcap_id, use_case_name, use_case_description)."""
    covered = conn.execute(
        text(
            "SELECT subcap_id, name, coalesce(description, name) FROM cat_v7.use_case "
            "WHERE coalesce(description, '') <> '' ORDER BY subcap_id, use_case_id LIMIT 1"
        )
    ).first()
    assert covered is not None, "v7 must have at least one described use case"
    return str(covered[0]), str(covered[1]), str(covered[2])


def _inject_cluster(conn: Connection, subcap: str, prefix: str, summary: str, n: int) -> None:
    """Insert ``n`` real (non-synthetic) Jira stories carried onto ``subcap`` with ``summary``, all
    UNMATCHED to any use case (no story_use_case_carry row), so the detector sees an uncovered
    cluster. Mirrors the control.story + control.story_subcap_carry rows carry_forward produces.
    Keys start with '0' so they sort first (survive the per-subcap unmatched cap)."""
    conn.execute(
        text(
            "INSERT INTO control.story (story_key, source_system, sub_cap_id, pillar_id, "
            "cap_name, summary, composite_score, is_synthetic, project_key) "
            "SELECT :p||'-'||g, 'jira', :sub, left(:sub, 2), 'Injected Cap', :sm, 3.0, false, "
            "'ZZUCGAP' FROM generate_series(1, :n) g"
        ),
        {"p": prefix, "sub": subcap, "sm": summary, "n": n},
    )
    conn.execute(
        text(
            "INSERT INTO control.story_subcap_carry (story_key, source_version, mapped_in_source, "
            "base_subcap, target_version, carried_to_subcap, similarity, status, via) "
            "SELECT :p||'-'||g, 'v5', :sub, :sub, 'v7', :sub, 0.95, 'confirmed', 'test' "
            "FROM generate_series(1, :n) g"
        ),
        {"p": prefix, "sub": subcap, "n": n},
    )


@pytest.fixture(scope="module")
def provisioned() -> Iterator[dict[str, str]]:
    from app import migrate

    migrate.run()
    ctx: dict[str, str] = {}

    async def _clean() -> None:
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
            await conn.execute(text("DELETE FROM control.story_use_case_carry"))
            await conn.execute(text("DELETE FROM control.story_subcap_carry"))
            await conn.execute(text("DELETE FROM control.story"))
            await conn.execute(text("DROP SCHEMA IF EXISTS cat_v7 CASCADE"))
            await conn.execute(
                text("DELETE FROM control.catalogue_version WHERE version_id = 'v7'")
            )
        await db.dispose_engine()

    async def _setup() -> None:
        # defensive: a prior interrupted run may have left v7 half-provisioned — clean first so the
        # module is self-contained + re-runnable, then build fresh.
        await _clean()
        db.init_engine()
        await provision.bring_version_online("v7")
        await story_svc.carry_forward("v7")
        await db.dispose_engine()

    async def _teardown() -> None:
        await _clean()

    asyncio.run(_setup())
    # inject the large "already covered" cluster (echoes an existing use case's own name +
    # description), via a sync connection outside the app event loop
    sync_eng = _sync_engine()
    with sync_eng.begin() as conn:
        cov_subcap, cov_name, cov_desc = _pick_covered(conn)
        ctx["covered_subcap"] = cov_subcap
        _inject_cluster(
            conn, cov_subcap, "0ZUCGAP-COV", f"{cov_name}. {cov_desc}", _COVERED_STORIES
        )
    sync_eng.dispose()
    yield ctx
    asyncio.run(_teardown())


@pytest.fixture
def client(provisioned: dict[str, str]) -> Iterator[TestClient]:
    with TestClient(create_app()) as c:
        yield c


def _sync_engine() -> Engine:
    return create_engine(os.environ["DATABASE_URL"].replace("+asyncpg", "+psycopg"))


@needs_db
def test_use_case_gap_proposals_are_gated_and_idempotent(client: TestClient) -> None:
    """The detector proposes real uncovered-delivery clusters, EVERY proposal passes G1-G8 (nothing
    is shown ungated), each surfaces in the inbox with a reasoning backlink + a PASSING gate run,
    and a second scan proposes nothing new (idempotent)."""
    summary = client.post("/api/admin/use-case-gaps/v7").json()
    assert summary["created"] >= 1  # the v7 corpus has real uncovered-delivery clusters
    assert summary["candidates"] >= summary["created"]  # candidates >= what survived the guards

    inbox = client.get("/api/change-flags?status=open").json()["flags"]
    gap_flags = [f for f in inbox if f["kind"] == "use_case_gap"]
    assert gap_flags, "the use-case gap proposals must surface in the inbox"

    # EVERY use_case_gap flag's chain passed G1-G8 (CLAUDE.md safeguard 2: nothing shown ungated).
    for f in gap_flags[:25]:  # bound the assertion cost; the invariant holds for all
        assert f["chain"]  # reasoning backlink present (trust envelope)
        assert f["gate_failed"] is None  # a gated proposal, not a gate failure
        chain = client.get(f"/api/reasoning/{f['chain']}").json()
        assert chain["verdict"] == "pass", f"flag {f['target']} must pass G1-G8"
        assert len(chain["steps"]) >= 3  # retrieve + weigh + conclude (>= 3 grounded steps)
        for check in chain["checks"]:
            assert check["state"] != "Needs review", f"{check['name']} failed on {f['target']}"

    # the target_ref is '<subcap>:<sig>' (subcap + cluster signature) — a versioned, keyed proposal
    assert all(":" in str(f["target"]) for f in gap_flags)

    # idempotent: a second scan proposes nothing new (every cluster is already flagged)
    again = client.post("/api/admin/use-case-gaps/v7").json()
    assert again["created"] == 0 and again["already"] >= 1


@needs_db
def test_overlap_guard_skips_a_cluster_matching_an_existing_use_case(
    client: TestClient, provisioned: dict[str, str]
) -> None:
    """The injected cluster echoes an EXISTING use case's own name + description, so its centroid
    embeds at/above the overlap bar to that use case — the guard SKIPS it, so the catalogue never
    bloats with a near-duplicate use case."""
    covered_subcap = provisioned["covered_subcap"]
    summary = client.post("/api/admin/use-case-gaps/v7").json()
    assert summary["skipped_overlap"] >= 1  # at least the injected echoed cluster is guarded out

    inbox = client.get("/api/change-flags?status=open").json()["flags"]
    # no use_case_gap flag was raised for the injected "already covered" subcap's echoed cluster
    covered_flags = [
        f
        for f in inbox
        if f["kind"] == "use_case_gap" and str(f["target"]).startswith(covered_subcap + ":")
    ]
    assert not covered_flags, "the overlap guard must skip a cluster an existing use case covers"


@needs_db
def test_approving_a_gap_proposal_inserts_a_new_use_case(client: TestClient) -> None:
    """Approving a use-case gap proposal RE-GATES server-side and inserts a NEW row into
    cat_v7.use_case (is_new=true), audited — the only path a proposal reaches the catalogue."""
    client.post("/api/admin/use-case-gaps/v7")
    inbox = client.get("/api/change-flags?status=open").json()["flags"]
    flag = next(f for f in inbox if f["kind"] == "use_case_gap")
    subcap = str(flag["target"]).split(":", 1)[0]  # target_ref is '<subcap>:<sig>'

    sync_eng = _sync_engine()
    with sync_eng.connect() as conn:
        before = conn.execute(
            text("SELECT count(*) FROM cat_v7.use_case WHERE subcap_id = :s"),
            {"s": subcap},
        ).scalar()

    approved = client.post(f"/api/change-flags/{flag['id']}/approve").json()
    assert approved["resolved"] is True and approved["status"] == "approved"

    with sync_eng.connect() as conn:
        after = conn.execute(
            text("SELECT count(*) FROM cat_v7.use_case WHERE subcap_id = :s"),
            {"s": subcap},
        ).scalar()
        new_uc = conn.execute(
            text(
                "SELECT name, is_new FROM cat_v7.use_case "
                "WHERE subcap_id = :s AND use_case_id LIKE 'UC-GAP-%' ORDER BY use_case_id"
            ),
            {"s": subcap},
        ).first()
        audit = conn.execute(
            text(
                "SELECT meta FROM control.audit_log WHERE action = 'change_flag.approve' "
                "AND target_ref = :s ORDER BY at DESC LIMIT 1"
            ),
            {"s": subcap},
        ).first()
    sync_eng.dispose()

    assert int(after or 0) == int(before or 0) + 1  # exactly one new use case inserted
    assert new_uc is not None and new_uc[1] is True  # is_new=true (flagged new in this version)
    assert audit is not None and audit[0].get("accepted") == "use_case_gap"  # gated + audited

    # the flag is resolved out of the open inbox
    still_open = client.get("/api/change-flags?status=open").json()["flags"]
    assert not any(f["id"] == flag["id"] for f in still_open)


def test_use_case_gap_thresholds_come_from_config() -> None:
    """Thresholds live in config/gates.yaml (recalibrated without a deploy), not in code."""
    cfg = gates.use_case_gap_config()
    assert cfg.min_stories >= 2  # G2 needs >= 2 supporting items
    assert 0 < cfg.overlap_max_cosine <= 1
    assert 0 < cfg.cluster_min_cosine <= 1
    assert cfg.max_proposals_per_scan >= 1
