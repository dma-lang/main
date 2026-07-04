"""Story<->capability relatedness gate — validated on the REAL committed corpus + catalogue.

Locks the deterministic scorer that catches the delivery mis-mapping (a Salesforce Knowledge-Base
story auto-confirmed under "Innovation Vision"): a clearly-related story scores far above an
unrelated one, the known P1 mis-maps score ~0 on their assigned capability and classify as not-fit,
and a clear sibling win classifies as ``misrouted`` with a re-route. Pure — no DB, no spend."""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any

from app.services.story_relatedness import RelatednessIndex, definition_doc, story_doc

_SEED = Path(__file__).resolve().parents[1] / "seed"

# a conservative, high-precision gate config (mirrors the gates.yaml default): only demote a carry
# whose story is essentially unrelated to the assigned capability.
_CFG = {"floor": 0.05, "margin": 0.15, "strong_sibling": 0.25}


def _catalogue() -> list[dict[str, Any]]:
    data: dict[str, Any] = json.load(gzip.open(_SEED / "catalogue_v7.json.gz"))
    return list(data["subcaps"])


def _stories() -> dict[str, dict[str, Any]]:
    return {r["k"]: r for r in json.load(gzip.open(_SEED / "stories.json.gz"))}


def test_definition_and_story_docs_are_grounded() -> None:
    sub = {
        "name": "Innovation Vision",
        "cluster": "Innovation Strategy",
        "catName": "Innovation",
        "desc": "pipelines ideas to market through structured experimentation",
        "personas": "['Chief Innovation Officer']",
        "uc": "[{'text': 'draft the vision'}]",
    }
    d = definition_doc(sub)
    assert "Innovation Vision" in d and "Innovation Strategy" in d and "experimentation" in d
    assert "Chief Innovation Officer" in d and "draft the vision" in d
    s = story_doc({"sum": "Enable Salesforce Knowledge", "desc": "configure KB", "act": ""})
    assert s.count("Enable Salesforce Knowledge") == 3  # summary weighted x3


def test_related_story_scores_far_above_unrelated() -> None:
    idx = RelatednessIndex(_catalogue())
    # a story that plainly concerns the digital-strategy capability
    good = story_doc({"sum": "Author the digital strategy document and align it to business goals"})
    bad = story_doc({"sum": "Enable Salesforce Knowledge base article record types"})
    hi = idx.relatedness(good, "P1C1.1.1")  # Digital Strategy Document
    lo = idx.relatedness(bad, "P1C1.1.1")
    assert hi > 0.2 and lo < 0.02 and hi > lo * 10


def test_known_p1_mismaps_score_zero_and_do_not_classify_fit() -> None:
    idx = RelatednessIndex(_catalogue())
    stories = _stories()
    # every one of these is assigned to P1C3.1.1 "Innovation Vision" in the source but is really a
    # Salesforce Knowledge-Base / discovery task — the exact garbage seen in the delivery tab.
    for key in ("BAYPORT-863", "BAYPORT-921", "BAYPORT-922", "BAYPORT-945"):
        r = stories[key]
        rel = idx.relatedness(story_doc(r), "P1C3.1.1")
        assert rel < 0.02, f"{key} scored {rel:.3f} on Innovation Vision"
        v = idx.classify(story_doc(r), "P1C3.1.1", **_CFG)
        assert v.verdict != "fit", f"{key} wrongly classified fit"


def test_misrouted_story_gets_a_reroute_target() -> None:
    idx = RelatednessIndex(_catalogue())
    r = _stories()["BAYPORT-863"]  # "Discovery of Documents to Synergy" -> Synergy Identification
    v = idx.classify(story_doc(r), "P1C3.1.1", **_CFG)
    assert v.verdict == "misrouted" and v.reroute is not None and v.reroute != "P1C3.1.1"
    assert v.best > v.assigned + _CFG["margin"]


def test_dense_half_rescues_a_lexical_gap_match() -> None:
    """A vocabulary-gap TRUE match (low lexical overlap) is NOT demoted when the dense embedding
    half vouches for it — the gate never punishes a real match on wording alone."""
    idx = RelatednessIndex(_catalogue())
    weak = story_doc({"sum": "zzz qqq unrelated tokens only"})
    demoted = idx.classify(weak, "P1C1.1.1", **_CFG)
    assert demoted.verdict in ("review", "misrouted")
    rescued = idx.classify(weak, "P1C1.1.1", **_CFG, dense_assigned=0.9, dense_strong=0.75)
    assert rescued.verdict == "fit"


def test_scorer_is_deterministic() -> None:
    idx = RelatednessIndex(_catalogue())
    r = _stories()["BAYPORT-863"]
    a = idx.classify(story_doc(r), "P1C3.1.1", **_CFG)
    b = idx.classify(story_doc(r), "P1C3.1.1", **_CFG)
    assert a == b


def test_corpus_wide_mismap_rate_is_material() -> None:
    """Sanity floor on the problem itself: a large fraction of native carries are weak-fit on their
    assigned capability (the reason the gate exists). If this ever collapses, the seed or the scorer
    changed and the gate's thresholds must be re-checked."""
    idx = RelatednessIndex(_catalogue())
    subs = {s["id"] for s in _catalogue()}
    rows = json.load(gzip.open(_SEED / "stories.json.gz"))
    scored = [idx.relatedness(story_doc(r), r["sc"]) for r in rows if r.get("sc") in subs]
    weak = sum(1 for x in scored if x < _CFG["floor"])
    assert len(scored) > 12000
    assert weak / len(scored) > 0.30  # measured ~0.69 lexical-only; the dense half narrows it live
