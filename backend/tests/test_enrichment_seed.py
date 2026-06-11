"""Cross-version enrichment fallback seed accessor — pure (no DB), deterministic.

A base-only version (e.g. an uploaded catalogue with no enrichment) serves a subcap's platforms /
use cases / maturity / personas / offerings from the reference catalogue (v7) seed BY SUBCAP ID,
so the deep dive is never empty.
"""

from __future__ import annotations

from app.services import enrichment_seed


def test_reference_version_is_the_richest_seed() -> None:
    # the bundled reference is v7 (the highest version that ships an enrichment seed)
    assert enrichment_seed.reference_version() == "v7"


def test_enrichment_for_known_subcap_is_populated() -> None:
    e = enrichment_seed.enrichment_for("P1C1.1.1")
    assert len(e["platforms"]) > 0
    assert len(e["use_cases"]) > 0
    assert len(e["maturity"]) > 0
    # shapes match the API models the endpoint validates against
    assert {"l3_id", "name", "vendor", "category"} <= set(e["platforms"][0])
    assert {"use_case_id", "archetype", "name", "description"} <= set(e["use_cases"][0])
    assert {"level", "descriptor", "features"} <= set(e["maturity"][0])
    # counts_for agrees with enrichment_for
    c = enrichment_seed.counts_for("P1C1.1.1")
    assert c["platforms"] == len(e["platforms"]) and c["use_cases"] == len(e["use_cases"])


def test_enrichment_for_unknown_subcap_is_empty_not_error() -> None:
    e = enrichment_seed.enrichment_for("P9C9.9.NOPE")
    assert e == {
        "platforms": [],
        "use_cases": [],
        "maturity": [],
        "personas": [],
        "offerings": [],
    }


def test_deterministic() -> None:
    assert enrichment_seed.enrichment_for("P1C1.1.1") == enrichment_seed.enrichment_for("P1C1.1.1")
