"""
carry_forward_subcap_mappings.py
=================================
Carry the canonical Jira story -> subcap mappings forward from the catalogue version they
were mapped against (v5) to the active catalogue version (v7) and to any future version,
confirming semantic similarity before a mapping is maintained.

Design goal: resilience.
  - Deterministic bridge first (the version crosswalk), embeddings only to *confirm*.
  - Every story keeps a continuous link across versions, or is explicitly flagged.
  - Nothing is dropped silently; borderline matches route to human review.
  - Idempotent: re-running re-provisions cleanly and never double-writes.
  - Version-agnostic: works for v5 -> v7 today and v7 -> v8 tomorrow.

The only project-specific pieces are the four adapter functions at the top
(load_canonical_stories, load_catalogue, load_crosswalk, embed). Everything else is generic.
"""

from __future__ import annotations
import re
import math
import json
from dataclasses import dataclass, asdict
from typing import Optional

# ----------------------------------------------------------------------------------
# Thresholds (tunable). Built deliberately conservative so we never silently mis-map.
# ----------------------------------------------------------------------------------
CONFIRM_AT = 0.86   # similarity >= CONFIRM_AT  -> carry forward automatically
REVIEW_AT  = 0.70   # REVIEW_AT <= sim < CONFIRM_AT -> flag for admin confirmation
                    # similarity < REVIEW_AT     -> treat as unmapped, propose nearest


# ----------------------------------------------------------------------------------
# Domain records
# ----------------------------------------------------------------------------------
@dataclass(frozen=True)
class Story:
    story_key: str
    sub_cap_id: str          # subcap id as mapped in the SOURCE version (v5), may carry a SV suffix
    story_sv_code: str       # subvertical context of the story (e.g. CL, CU)
    confidence_level: str    # source match confidence: HIGH / MEDIUM / LOW
    is_synthetic: bool        # True for generated / use-case-derived rows


@dataclass(frozen=True)
class Subcap:
    sub_cap_id: str
    name: str
    description: str


@dataclass
class CarryResult:
    story_key: str
    mapped_in_source: str            # original v5 id (with SV suffix if present)
    base_subcap: str                 # SV suffix stripped
    subvertical: Optional[str]
    carried_to_target: Optional[str] # subcap id in the target version
    similarity: float
    status: str                      # confirmed | review | unmapped
    source_confidence: str
    via: str                         # crosswalk | nearest_neighbour | none


# ----------------------------------------------------------------------------------
# Adapters - the only functions that touch storage or models. Wire to your stack.
# ----------------------------------------------------------------------------------
def load_canonical_stories() -> list[Story]:
    """Read the canonical Jira Full Story Catalog ('Actual (Real Client)').
    Real stories only are canonical; synthetic rows are loaded but flagged."""
    raise NotImplementedError


def load_catalogue(version: str) -> dict[str, Subcap]:
    """Return {sub_cap_id: Subcap} for a catalogue version, from its provisioned
    relational database (the one the schema-mapping studio stood up)."""
    raise NotImplementedError


def load_crosswalk(target_version: str) -> dict[str, str]:
    """Return {source_subcap_id -> target_subcap_id}, e.g. from the target version's
    _R1_Source_Reference tab (which maps each v_next id back to its v5 original)."""
    raise NotImplementedError


def embed(text: str) -> list[float]:
    """Catalogue-tuned embedding of a subcap's name + description.
    Same model used for SOW and story matching, so the space is consistent."""
    raise NotImplementedError


# ----------------------------------------------------------------------------------
# Pure helpers
# ----------------------------------------------------------------------------------
_ID_RE = re.compile(r'^(?P<base>P\d+C\d+(?:\.\d+)*?)(?:\.(?P<sv>[A-Z]{2}\d*))?$')

def normalize_id(sub_cap_id: str) -> tuple[str, Optional[str]]:
    """Split a possibly subvertical-suffixed id, e.g. 'P3C1.8.CL2' -> ('P3C1.8', 'CL2')."""
    m = _ID_RE.match(sub_cap_id.strip())
    if not m:
        return sub_cap_id.strip(), None
    return m.group('base'), m.group('sv')


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def subcap_text(catalogue: dict[str, Subcap], sid: str) -> Optional[str]:
    s = catalogue.get(sid)
    return f"{s.name}. {s.description}" if s else None


def nearest_subcap(text: str, catalogue: dict[str, Subcap],
                   _cache: dict = {}) -> tuple[Optional[str], float]:
    """Best semantic match for `text` among the target catalogue's subcaps."""
    if not text:
        return None, 0.0
    q = embed(text)
    best_id, best_sim = None, 0.0
    for sid, sc in catalogue.items():
        vec = _cache.get(sid) or _cache.setdefault(sid, embed(f"{sc.name}. {sc.description}"))
        sim = cosine(q, vec)
        if sim > best_sim:
            best_id, best_sim = sid, sim
    return best_id, best_sim


# ----------------------------------------------------------------------------------
# Core: carry one mapping forward
# ----------------------------------------------------------------------------------
def carry_one(story: Story,
              source_cat: dict[str, Subcap],
              target_cat: dict[str, Subcap],
              crosswalk: dict[str, str]) -> CarryResult:
    base, sv = normalize_id(story.sub_cap_id)

    # 1) Deterministic bridge: try the crosswalk on the full id, then the base id.
    candidate = crosswalk.get(story.sub_cap_id) or crosswalk.get(base)
    via = "crosswalk" if candidate else None

    # If the candidate exists verbatim in the target, similarity may still be checked.
    if candidate and candidate in target_cat:
        src_text = subcap_text(source_cat, base) or subcap_text(source_cat, story.sub_cap_id) or ""
        tgt_text = subcap_text(target_cat, candidate) or ""
        sim = cosine(embed(src_text), embed(tgt_text)) if src_text and tgt_text else 1.0
    else:
        # 2) No usable crosswalk hit: fall back to semantic nearest neighbour.
        src_text = subcap_text(source_cat, base) or subcap_text(source_cat, story.sub_cap_id) or ""
        candidate, sim = nearest_subcap(src_text, target_cat)
        via = "nearest_neighbour" if candidate else "none"

    # 3) Gate on similarity.
    if candidate and sim >= CONFIRM_AT:
        status = "confirmed"
    elif candidate and sim >= REVIEW_AT:
        status = "review"
    else:
        status = "unmapped"

    return CarryResult(
        story_key=story.story_key,
        mapped_in_source=story.sub_cap_id,
        base_subcap=base,
        subvertical=sv or (story.story_sv_code or None),
        carried_to_target=candidate if status != "unmapped" else None,
        similarity=round(sim, 3),
        status=status,
        source_confidence=story.confidence_level,
        via=via or "none",
    )


# ----------------------------------------------------------------------------------
# Orchestration
# ----------------------------------------------------------------------------------
def seed_native(source_version: str = "v5",
                include_synthetic: bool = False) -> list[CarryResult]:
    """Step 1: write the NATIVE links for the version the stories were originally mapped to (v5).
    Each story's sub_cap_id already is a subcap in source_version once the subvertical suffix is
    normalised, so the link is confirmed with similarity 1.0 and via='native'. This is what relates
    the canonical Jira stories to the v5 catalogue; carry_forward() then relates them to v7+."""
    stories = load_canonical_stories()
    if not include_synthetic:
        stories = [s for s in stories if not s.is_synthetic]
    out = []
    for s in stories:
        base, sv = normalize_id(s.sub_cap_id)
        out.append(CarryResult(
            story_key=s.story_key, mapped_in_source=s.sub_cap_id, base_subcap=base,
            subvertical=sv or (s.story_sv_code or None), carried_to_target=base,
            similarity=1.0, status="confirmed", source_confidence=s.confidence_level, via="native"))
    return out


def carry_forward(source_version: str = "v5",
                  target_version: str = "v7",
                  include_synthetic: bool = False) -> list[CarryResult]:
    """Step 2: carry the canonical story->subcap mappings from source_version to target_version.

    Synthetic stories are excluded from the analysis set by default; they are only carried
    when a separate news/trend signal has flagged the relevant subcap as an emergent trend
    (the caller passes include_synthetic=True for that scoped re-run)."""
    if target_version == source_version:
        return seed_native(source_version, include_synthetic)   # native, not a carry

    stories = load_canonical_stories()
    if not include_synthetic:
        stories = [s for s in stories if not s.is_synthetic]

    source_cat = load_catalogue(source_version)
    target_cat = load_catalogue(target_version)
    crosswalk = load_crosswalk(target_version)

    results = [carry_one(s, source_cat, target_cat, crosswalk) for s in stories]
    return results


def summarize(results: list[CarryResult]) -> dict:
    by_status: dict[str, int] = {}
    by_subcap: dict[str, set] = {}
    for r in results:
        by_status[r.status] = by_status.get(r.status, 0) + 1
        if r.carried_to_target:
            by_subcap.setdefault(r.carried_to_target, set()).add(r.story_key)
    return {
        "total": len(results),
        "by_status": by_status,
        "distinct_target_subcaps": len(by_subcap),
        "confirmed_pct": round(100 * by_status.get("confirmed", 0) / max(1, len(results)), 1),
    }


def persist(results: list[CarryResult], target_version: str) -> None:
    """Write the links into control.story_subcap_carry, keyed on (story_key, target_version), so a
    re-run upserts rather than duplicating. 'confirmed' links are written live (via 'native' for the
    source version, 'crosswalk' or 'nearest_neighbour' for later versions); 'review' links are
    written and surfaced in the Story carry-forward UI; 'unmapped' rows are kept in the queue, never
    discarded. carried_to_target is a logical reference into cat_<target_version>.subcap, validated
    here against that version's schema (a hard FK is impossible because the schema name varies)."""
    raise NotImplementedError


if __name__ == "__main__":
    # 1) native links for the version the stories were mapped to
    persist_native = seed_native("v5")
    print("v5 native:", json.dumps(summarize(persist_native), indent=2))
    # persist(persist_native, "v5")

    # 2) carry forward to the active version (and re-run for any future version, e.g. v8)
    carried = carry_forward("v5", "v7", include_synthetic=False)
    print("v7 carried:", json.dumps(summarize(carried), indent=2))
    # persist(carried, "v7")
