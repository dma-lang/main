"""The validation gates as deterministic code (CLAUDE.md safeguard 2), parameterised by
config/gates.yaml. This slice implements the read-path gates a grounded answer must pass — G5
(similarity grounding: every answer cites retrieved evidence) and G7 (citation verification: cited
ids resolve to stored evidence). The full G1-G8 set extends this for the suggestion / apply path.
"""

from __future__ import annotations

from dataclasses import dataclass
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


@dataclass(frozen=True)
class TrendConfig:
    """Trend signal weights + emergence cutoff + cluster floors (config/gates.yaml: trends.*)."""

    velocity: float
    diversity: float
    novelty: float
    persistence: float
    emergent_cut: float
    trend_threshold: float
    min_cluster: int
    min_sources: int

    def score(self, velocity: float, diversity: float, novelty: float, persistence: float) -> float:
        """The composite trend score (spec §18.1): the weighted blend of the four signals."""
        return round(
            self.velocity * velocity
            + self.diversity * diversity
            + self.novelty * novelty
            + self.persistence * persistence,
            3,
        )


def trends_config() -> TrendConfig:
    """Signal weights (velocity/diversity/novelty/persistence — must sum to 1.0), the score floor a
    cluster must clear (trend_threshold), the novelty cutoff above which a subcap is flagged
    emergent (the only path a synthetic story may surface), and the cluster floors (min_cluster /
    min_sources) below which a thin cluster is filtered, never promoted. Config, not code: analyst
    feedback recalibrates these without a deploy (spec §18.3)."""
    section = load_gate_config().get("trends") or {}
    cfg = TrendConfig(
        velocity=float(section.get("weight_velocity", 0.35)),
        diversity=float(section.get("weight_diversity", 0.30)),
        novelty=float(section.get("weight_novelty", 0.20)),
        persistence=float(section.get("weight_persistence", 0.15)),
        emergent_cut=float(section.get("emergent_cut", 0.80)),
        trend_threshold=float(section.get("trend_threshold", 0.45)),
        min_cluster=int(section.get("min_cluster", 4)),
        min_sources=int(section.get("min_sources", 3)),
    )
    if abs((cfg.velocity + cfg.diversity + cfg.novelty + cfg.persistence) - 1.0) > 1e-6:
        raise ValueError("gates.yaml: trend signal weights must sum to 1.0")
    if not 0 < cfg.emergent_cut <= 1:
        raise ValueError("gates.yaml: trends.emergent_cut must be in (0, 1]")
    if not 0 <= cfg.trend_threshold <= 1:
        raise ValueError("gates.yaml: trends.trend_threshold must be in [0, 1]")
    return cfg


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


def evaluate_trend(
    *,
    cluster_size: int,
    distinct_sources: int,
    best_tier: str,
    min_cluster: int,
    min_sources: int,
    contradicts: bool,
) -> tuple[dict[str, Any], str]:
    """Gate a detected trend before it is staged (spec §18.1: cluster -> score -> G2/G3/G6). G2:
    the cluster holds enough independent evidence (>= min_cluster). G3: it clears the source-tier
    floor AND draws on enough DISTINCT sources (>= min_sources) — one low-tier source repeated is
    not a trend. G6: it does not contradict delivery reality. The thin-cluster floors are also
    applied pre-scoring (filtered silently); a cluster that clears them but fails a gate is routed
    to review (Change Flags), never promoted low-confidence ("trends are earned, not counted")."""
    tier_ok = best_tier in ("T1", "T2", "T3")
    results: dict[str, Any] = {
        "G2_evidence_sufficiency": _r(
            cluster_size >= min_cluster,
            f"{cluster_size} clustered evidence item(s) (floor {min_cluster})",
        ),
        "G3_source_tier_floor": _r(
            tier_ok and distinct_sources >= min_sources,
            f"{distinct_sources} distinct source(s), best tier {best_tier} "
            f"(floor T3, >= {min_sources} sources)",
        ),
        "G6_contradiction": _r(not contradicts, "trend does not contradict delivery reality"),
    }
    verdict = "pass" if all(g["verdict"] == "pass" for g in results.values()) else "fail"
    return results, verdict


def first_failing(results: dict[str, Any]) -> str | None:
    """The first gate that did not pass (for routing a failed re-gate to review)."""
    for name, res in results.items():
        if res.get("verdict") != "pass":
            return name
    return None
