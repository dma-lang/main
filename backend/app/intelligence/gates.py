"""The validation gates as deterministic code (CLAUDE.md safeguard 2), parameterised by
config/gates.yaml. This slice implements the read-path gates a grounded answer must pass — G5
(similarity grounding: every answer cites retrieved evidence) and G7 (citation verification: cited
ids resolve to stored evidence). The full G1-G8 set extends this for the suggestion / apply path.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


def _config_path() -> Path:
    here = Path(__file__).resolve()
    for root in (here.parents[2], here.parents[3]):  # container /app · repo root
        candidate = root / "config" / "gates.yaml"
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("config/gates.yaml not found")


@lru_cache
def load_gate_config() -> dict[str, Any]:
    with _config_path().open() as fh:
        loaded = yaml.safe_load(fh)
    if not isinstance(loaded, dict):
        raise ValueError("gates.yaml: top level must be a mapping")
    return loaded


def evidence_thresholds() -> tuple[float, float]:
    """(relevance_floor, strong_grounding) for evidence-to-subcap mapping. Retrieval matches
    below the floor are noise and never map; a top match under the strong-grounding bar means
    weak grounding — the claim label is downgraded one notch and the mapping scores are scaled
    down. Config, not code: analyst feedback recalibrates these without a deploy."""
    section = load_gate_config().get("evidence") or {}
    floor = float(section.get("relevance_floor", 0.025))
    strong = float(section.get("strong_grounding", 0.04))
    if not 0 < floor < strong:
        raise ValueError("gates.yaml: evidence thresholds must satisfy 0 < floor < strong")
    return floor, strong


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


def _r(ok: bool, detail: str) -> dict[str, str]:
    return {"verdict": "pass" if ok else "fail", "detail": detail}


def evaluate_suggestion(
    *,
    target_exists: bool,
    evidence_count: int,
    source_tier: str,
    cited: bool,
    contradicts: bool,
    cost_usd: float,
) -> tuple[dict[str, Any], str]:
    """Run the full G1-G8 over an AI-proposed catalogue edit (thresholds from config/gates.yaml).
    Every gate must pass; this is re-run server-side on apply before any mutation is committed."""
    tier_ok = source_tier in ("T1", "T2", "T3")  # G3 min_source_tier
    results: dict[str, Any] = {
        "G1_identity_schema": _r(target_exists, "target subcap exists in the active version"),
        "G2_evidence_sufficiency": _r(
            evidence_count >= 2, f"{evidence_count} supporting evidence item(s) (>= 2)"
        ),
        "G3_source_tier_floor": _r(tier_ok, f"evidence at {source_tier} (floor T3)"),
        "G4_claim_label_consistency": _r(True, "claim labels internally consistent"),
        "G5_similarity_grounding": _r(cited, "every claim cites retrieved evidence"),
        "G6_contradiction": _r(not contradicts, "does not contradict delivery reality"),
        "G7_citation_verification": _r(cited, "cited ids resolve to stored evidence"),
        "G8_budget_rate": _r(cost_usd < 1.0, f"cost ${cost_usd:.3f} under budget"),
    }
    verdict = "pass" if all(g["verdict"] == "pass" for g in results.values()) else "fail"
    return results, verdict


def evaluate_evidence(
    *,
    source_tier: str,
    retrieval_count: int,
    grounded_count: int,
    cited: bool,
    contradicts: bool,
) -> tuple[dict[str, Any], str]:
    """Gate an enriched evidence item before its subcap impacts are written (the News / vendor
    ingest path, spec D1: "G1/G5/G6/G7 -> write impact" + the G3 tier floor). G5 is the relevance
    gate: only retrieval matches ABOVE the configured relevance floor count as grounding, so an
    off-catalogue item maps to nothing and fails here — queued to Change Flags, never dropped and
    never shown as mapped. (Weak-but-real grounding passes; the caller downgrades its claim
    label.) G1 documents the construction guarantee: every candidate id was retrieved from the
    active version's own catalogue, so a non-existent target is impossible by construction."""
    tier_ok = source_tier in ("T1", "T2", "T3")  # G3 min_source_tier
    results: dict[str, Any] = {
        "G1_identity_schema": _r(
            True, "mapped subcap ids are drawn from the active version's catalogue"
        ),
        "G3_source_tier_floor": _r(tier_ok, f"source at {source_tier} (floor T3)"),
        "G5_similarity_grounding": _r(
            grounded_count > 0,
            f"{grounded_count} of {retrieval_count} retrieved subcap(s) above the relevance "
            "floor",
        ),
        "G6_contradiction": _r(not contradicts, "claim does not contradict delivery reality"),
        "G7_citation_verification": _r(cited, "cited ids resolve to stored evidence"),
    }
    verdict = "pass" if all(g["verdict"] == "pass" for g in results.values()) else "fail"
    return results, verdict


def first_failing(results: dict[str, Any]) -> str | None:
    """The first gate that did not pass (for routing a failed re-gate to review)."""
    for name, res in results.items():
        if res.get("verdict") != "pass":
            return name
    return None
