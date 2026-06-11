"""A3 dynamic value-chain derivation: dedupe + smart clustering (services/value_chain).

Pure unit tests over plain rows (no DB) — the same function the catalogue endpoint feeds from
``cat_<version>``, so v5 and v7 each derive their own chain from their own data.
"""

from __future__ import annotations

from app.services.value_chain import derive_value_chain


def _row(sid: str, name: str, pillar: str, cluster: str, category: str = "Cap") -> dict[str, str]:
    return {
        "subcap_id": sid,
        "name": name,
        "pillar": pillar,
        "cluster": cluster,
        "category": category,
    }


def test_groups_into_segments_with_codes_and_counts() -> None:
    rows = [
        _row("P1C1.1", "a", "P1", "Strategy & Vision"),
        _row("P1C1.2", "b", "P1", "Strategy & Vision"),
        _row("P2C1.1", "c", "P2", "Servicing"),
    ]
    out = derive_value_chain(rows)
    assert out["total_subcaps"] == 3
    by_name = {c["name"]: c for c in out["clusters"]}
    assert by_name["Strategy & Vision"]["count"] == 2
    assert by_name["Strategy & Vision"]["pillar"] == "P1"
    assert by_name["Servicing"]["count"] == 1
    # ordered by pillar then size, coded VCC-NN
    assert [c["code"] for c in out["clusters"]] == ["VCC-01", "VCC-02"]
    assert out["clusters"][0]["pillar"] == "P1"


def test_dedupes_exact_duplicate_cluster_names() -> None:
    # same segment, different surface spelling (&/and, case, word order) -> ONE segment
    rows = [
        _row("P1C1.1", "a", "P1", "Strategy Foundation & Alignment"),
        _row("P1C2.1", "b", "P1", "strategy foundation and alignment"),
        _row("P1C3.1", "c", "P1", "Alignment & Strategy Foundation"),
    ]
    out = derive_value_chain(rows)
    assert out["raw_clusters"] == 1  # all normalise to one key
    assert len(out["clusters"]) == 1
    seg = out["clusters"][0]
    assert seg["count"] == 3
    # the canonical label is a real surface spelling; the others are recorded transparently
    assert seg["name"] in {
        "Strategy Foundation & Alignment",
        "strategy foundation and alignment",
        "Alignment & Strategy Foundation",
    }
    assert len(seg["merged_from"]) == 2


def test_clusters_near_duplicate_names_within_a_pillar() -> None:
    # high token overlap -> merged under one canonical, recorded in merged_from (auditable)
    rows = [
        _row("P2C1.1", "a", "P2", "Loan Origination & Underwriting"),
        _row("P2C1.2", "b", "P2", "Loan Origination & Underwriting"),
        _row("P2C2.1", "c", "P2", "Loan Origination"),
    ]
    out = derive_value_chain(rows)
    assert len(out["clusters"]) == 1  # "Loan Origination" absorbed into the larger segment
    seg = out["clusters"][0]
    assert seg["count"] == 3
    assert seg["name"] == "Loan Origination & Underwriting"  # the most common surface spelling
    assert "Loan Origination" in seg["merged_from"]
    assert out["deduped"] == 1


def test_does_not_merge_distinct_segments_or_across_pillars() -> None:
    rows = [
        _row("P1C1.1", "a", "P1", "Risk Management"),
        _row("P3C1.1", "b", "P3", "Risk Management"),  # same name, DIFFERENT pillar -> stays apart
        _row("P1C2.1", "c", "P1", "Innovation"),  # clearly distinct -> stays apart
    ]
    out = derive_value_chain(rows)
    names_pillars = {(c["name"], c["pillar"]) for c in out["clusters"]}
    assert ("Risk Management", "P1") in names_pillars
    assert ("Risk Management", "P3") in names_pillars  # not merged across pillars
    assert len(out["clusters"]) == 3


def test_stages_are_the_finer_capabilities_within_a_segment() -> None:
    rows = [
        _row("P2C1.1", "a", "P2", "Servicing", category="Omnichannel"),
        _row("P2C1.2", "b", "P2", "Servicing", category="Omnichannel"),
        _row("P2C2.1", "c", "P2", "Servicing", category="Self-Service"),
    ]
    out = derive_value_chain(rows)
    seg = next(c for c in out["clusters"] if c["name"] == "Servicing")
    stages = {s["name"]: s["count"] for s in seg["stages"]}
    assert stages == {"Omnichannel": 2, "Self-Service": 1}
