"""The single canonical subcap -> reference mapping rule (used by every enrichment path).

Pure (no DB), so the rule is pinned directly: exact id -> crosswalk -> L2 name + near description
-> L2 name only -> None (genuinely unmapped, never fabricated).
"""

from __future__ import annotations

from typing import Any

from app.services import subcap_xref

# reference catalogue: two subcaps in the same L2 capability, plus a singleton
_REF = subcap_xref.ReferenceIndex.build(
    [
        {"id": "P1C1.1.1", "l2": "Strategy Foundation", "descr": "digital strategy document"},
        {"id": "P1C1.1.2", "l2": "Strategy Foundation", "descr": "innovation funding model"},
        {"id": "P2C3.5.1", "l2": "Case Management", "descr": "case intake and classification"},
    ]
)


def test_exact_id_wins() -> None:
    assert subcap_xref.resolve("P2C3.5.1", "anything", "anything", _REF) == "P2C3.5.1"


def test_crosswalk_when_id_absent() -> None:
    # a renamed id resolves through the id-governance crosswalk
    got = subcap_xref.resolve(
        "P1C9.9.WM1", "Unknown L2", "x", _REF, crosswalk={"P1C9.9.WM1": "P2C3.5.1"}
    )
    assert got == "P2C3.5.1"


def test_l2_plus_near_description() -> None:
    # same L2 capability, description close to P1C1.1.2 -> that one, not the first
    got = subcap_xref.resolve(
        "P1C1.1.9", "Strategy Foundation", "innovation funding approach", _REF
    )
    assert got == "P1C1.1.2"


def test_l2_only_is_deterministic_first() -> None:
    # same L2 capability but no description signal -> the id-sorted first candidate
    got = subcap_xref.resolve("P1C1.1.9", "Strategy Foundation", None, _REF)
    assert got == "P1C1.1.1"


def test_generic_token_overlap_below_threshold_does_not_match_by_description() -> None:
    # only the generic word "strategy" overlaps -> below 0.5 -> falls back to L2-first, not a
    # confident description match
    got = subcap_xref.resolve("P1C1.1.9", "Strategy Foundation", "strategy roadmap quarterly", _REF)
    assert got == "P1C1.1.1"  # deterministic L2-first, not a spurious description hit


def test_unmapped_is_none_never_fabricated() -> None:
    assert subcap_xref.resolve("P4C9.9.9", "Nonexistent Capability", "x", _REF) is None


def test_resolve_map_reports_unmapped() -> None:
    rows: list[dict[str, Any]] = [
        {"id": "P2C3.5.1", "l2": "Case Management", "descr": "x"},  # exact
        {"id": "P1C1.1.9", "l2": "Strategy Foundation", "descr": None},  # L2-first
        {"id": "P9C9.9.9", "l2": "Ghost", "descr": "y"},  # unmapped
    ]
    mapping, unmapped = subcap_xref.resolve_map(rows, _REF)
    assert mapping == {"P2C3.5.1": "P2C3.5.1", "P1C1.1.9": "P1C1.1.1"}
    assert unmapped == ["P9C9.9.9"]


def test_semantic_tier_resolves_drifted_l1_l2_by_meaning() -> None:
    # A legacy version whose ids AND L1/L2 names drifted: the lexical rules (id / crosswalk /
    # L2-name) all MISS, but rule 5 maps it to the nearest reference subcap by embedding meaning.
    ref = subcap_xref.ReferenceIndex.build(
        [
            {"id": "P1C1.1.1", "l2": "Strategy Foundation", "descr": "strategy operating model"},
            {"id": "P2C3.5.1", "l2": "Case Management", "descr": "case intake triage"},
        ],
        subcap_emb={"P1C1.1.1": [1.0, 0.0, 0.0], "P2C3.5.1": [0.0, 1.0, 0.0]},
        l2_emb={"Strategy Foundation": [1.0, 0.0, 0.0], "Case Management": [0.0, 1.0, 0.0]},
    )
    got = subcap_xref.resolve(
        "LEGACY-9",
        "Strategy Fundamentals",  # renamed L2 -> lexical miss on every rule
        "operating model design",
        ref,
        this_emb=[0.98, 0.02, 0.0],  # embeds near the strategy subcap
        this_l2_emb=[0.97, 0.03, 0.0],
        semantic_min=0.6,
        l2_semantic_min=0.6,
    )
    assert got == "P1C1.1.1"  # resolved by MEANING, not spelling
    # additive: without embeddings + threshold the same drifted subcap stays UNMAPPED (rules 1-4)
    assert subcap_xref.resolve("LEGACY-9", "Strategy Fundamentals", "x", ref) is None
