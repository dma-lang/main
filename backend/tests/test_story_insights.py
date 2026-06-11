"""Story-insight clustering (delivery drilldown): deterministic, explainable, hermetic-safe."""

from __future__ import annotations

from typing import Any

from app.services.story_insights import cluster_stories, tokenize


def _row(key: str, project: str | None, summary: str, score: float | None = 3.0) -> dict[str, Any]:
    return {"story_key": key, "project_key": project, "summary": summary, "composite_score": score}


def test_tokenize_drops_function_words_keeps_domain_terms() -> None:
    toks = tokenize("Build the data migration pipeline for Salesforce")
    assert "the" not in toks and "for" not in toks
    assert {"data", "migration", "pipeline", "salesforce"} <= toks


def test_clusters_group_similar_stories_and_list_related_clients() -> None:
    rows = [
        _row("A-1", "ACME", "Data migration of legacy accounts to Salesforce", 4.0),
        _row("A-2", "ACME", "Data migration of legacy contacts to Salesforce", 3.5),
        _row("B-1", "BETA", "Data migration of legacy cases to Salesforce", 3.0),
        _row("C-1", "CGLO", "Chatbot intent training for service console", 2.0),
        _row("C-2", "CGLO", "Chatbot intent training for sales console", 2.5),
        _row("D-1", "DLTA", "Chatbot intent training for marketing console", 2.2),
    ]
    out = cluster_stories(rows)
    assert len(out["clusters"]) == 2
    mig = next(c for c in out["clusters"] if "migration" in c["label"])
    bot = next(c for c in out["clusters"] if "chatbot" in c["label"])
    # related clients with similar story characteristics, most-active first
    assert mig["clients"][0] == "ACME" and "BETA" in mig["clients"]
    assert set(bot["clients"]) == {"CGLO", "DLTA"}
    assert mig["stories"] == 3 and bot["stories"] == 3
    assert mig["avg_composite"] == 3.5
    # samples are the strongest stories, with their keys for per-story drilldown
    assert mig["sample"][0]["story_key"] == "A-1"
    assert out["unclustered"] == 0


def test_small_groups_stay_unclustered_not_fake_themes() -> None:
    rows = [
        _row("X-1", "ACME", "Quantum ledger reconciliation spike"),
        _row("X-2", "BETA", "Holiday calendar localisation tweak"),
        _row("X-3", None, ""),
    ]
    out = cluster_stories(rows)
    assert out["clusters"] == []
    assert out["unclustered"] == 3


def test_deterministic_regardless_of_input_order() -> None:
    rows = [
        _row("A-1", "ACME", "Data migration of legacy accounts to Salesforce", 4.0),
        _row("A-2", "ACME", "Data migration of legacy contacts to Salesforce", 3.5),
        _row("B-1", "BETA", "Data migration of legacy cases to Salesforce", 3.0),
    ]
    a = cluster_stories(rows)
    b = cluster_stories(list(reversed(rows)))
    assert a == b
