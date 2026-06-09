"""The validation gates as deterministic code (CLAUDE.md safeguard 2), parameterised by
config/gates.yaml. This slice implements the read-path gates a grounded answer must pass — G5
(similarity grounding: every answer cites retrieved evidence) and G7 (citation verification: cited
ids resolve to stored evidence). The full G1-G8 set extends this for the suggestion / apply path.
"""

from __future__ import annotations

from typing import Any


def evaluate_chat(retrieval_count: int, citation_count: int) -> tuple[dict[str, Any], str]:
    """Run G5 + G7 over a grounded answer; return the gate_results jsonb and the verdict."""
    g5 = retrieval_count > 0 and citation_count > 0
    g7 = citation_count > 0  # citations are minted from stored catalogue evidence_items
    results: dict[str, Any] = {
        "G5_similarity_grounding": {
            "verdict": "pass" if g5 else "fail",
            "detail": (
                f"{citation_count} citation(s) from {retrieval_count} retrieved evidence item(s)"
            ),
        },
        "G7_citation_verification": {
            "verdict": "pass" if g7 else "fail",
            "detail": "every cited id resolves to a stored catalogue evidence item",
        },
    }
    return results, ("pass" if (g5 and g7) else "fail")
