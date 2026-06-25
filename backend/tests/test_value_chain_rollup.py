"""Pure unit tests for the value-chain ROLLUP (A3 'Rollup' view) — bucket mapping + aggregation.

No DB: ``bucket_for`` / ``build_rollup`` are pure over config/value_chain.yaml + plain dicts, so the
8-bucket taxonomy, the DISTINCT story/project counts, the pillar tally, top-8 ordering and the
per-quarter trend are verified directly (the endpoint only supplies the per-subcap maps). The trend
stays empty unless a story->quarter map is supplied (the corpus carries no date; we never synthesize
one), which these tests pin explicitly.
"""

from __future__ import annotations

from typing import Any

from app.services.value_chain import bucket_for, build_rollup, load_rollup_config


def test_config_has_eight_canonical_stages() -> None:
    cfg = load_rollup_config()
    codes = [s["code"] for s in cfg["stages"]]
    assert codes == [f"VCC-{i:02d}" for i in range(1, 9)]
    assert all(s.get("blurb") for s in cfg["stages"])  # every canonical stage has a blurb


def test_bucket_for_maps_raw_stage_names() -> None:
    assert bucket_for("MARKET INTELLIGENCE & VERTICAL TARGETING") == "VCC-01"
    assert bucket_for("AML / KYC (Wealth)") == "VCC-01"  # KYC wins precedence (onboarding)
    assert bucket_for("Loan Origination & Underwriting") == "VCC-03"
    assert bucket_for("AG PAYMENT / DISBURSEMENT OPS") == "VCC-04"
    assert bucket_for("Portfolio Analytics & Reporting") == "VCC-07"
    assert bucket_for("Cloud Platform & Data Governance") == "VCC-08"


def test_bucket_for_unknown_falls_to_default() -> None:
    cfg = load_rollup_config()
    assert bucket_for("Zzz Totally Unknown Stage") == cfg["default_bucket"]


def _stages() -> list[dict[str, Any]]:
    return [
        {
            "name": "MARKET INTELLIGENCE",  # -> VCC-01
            "subcaps": [
                {"id": "P2C1.1", "name": "A", "pillar": "P2"},
                {"id": "P2C1.2", "name": "B", "pillar": "P2"},
            ],
        },
        {
            "name": "BACK OFFICE OPS",  # -> VCC-06 (no higher-precedence token like SERVIC/RISK)
            "subcaps": [{"id": "P3C1.1", "name": "C", "pillar": "P3"}],
        },
    ]


def test_build_rollup_returns_all_eight_buckets() -> None:
    roll = build_rollup(_stages(), {}, {}, {})
    assert [b["code"] for b in roll] == [f"VCC-{i:02d}" for i in range(1, 9)]
    assert all("blurb" in b and "pillars" in b and "top" in b for b in roll)


def test_build_rollup_distinct_stories_and_projects() -> None:
    story = {"P2C1.1": {"s1", "s2"}, "P2C1.2": {"s2", "s3"}, "P3C1.1": {"s4"}}
    proj = {"P2C1.1": {"PRJ1"}, "P2C1.2": {"PRJ1", "PRJ2"}, "P3C1.1": {"PRJ3"}}
    roll = {b["code"]: b for b in build_rollup(_stages(), story, proj, {})}
    acq = roll["VCC-01"]
    assert acq["subcaps"] == 2
    assert acq["stories"] == 3  # {s1,s2,s3} distinct (s2 shared across subcaps, counted once)
    assert acq["projects"] == 2  # {PRJ1,PRJ2} distinct
    assert acq["pillars"] == {"P1": 0, "P2": 2, "P3": 0, "P4": 0}
    ops = roll["VCC-06"]
    assert ops["subcaps"] == 1 and ops["stories"] == 1 and ops["projects"] == 1


def test_build_rollup_top_ordered_by_story_count() -> None:
    story = {"P2C1.1": {"a"}, "P2C1.2": {"a", "b", "c"}}
    roll = {b["code"]: b for b in build_rollup(_stages(), story, {}, {})}
    top = roll["VCC-01"]["top"]
    assert [t["id"] for t in top] == ["P2C1.2", "P2C1.1"]  # 3 stories rank above 1
    assert top[0]["n"] == 3 and top[1]["n"] == 1


def test_build_rollup_quarter_trend_and_empty_default() -> None:
    story = {"P2C1.1": {"s1", "s2"}, "P2C1.2": {"s3"}}
    # no dates -> all quarters zero (grounded: a trend is never synthesized)
    roll0 = {b["code"]: b for b in build_rollup(_stages(), story, {}, {})}
    assert roll0["VCC-01"]["quarters"] == [0, 0, 0, 0, 0, 0]
    # with a story->quarter map, DISTINCT stories bin into the trend
    sq = {"s1": 5, "s2": 5, "s3": 0}
    roll1 = {b["code"]: b for b in build_rollup(_stages(), story, {}, sq)}
    assert roll1["VCC-01"]["quarters"] == [1, 0, 0, 0, 0, 2]
