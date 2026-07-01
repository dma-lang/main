"""The single canonical subcap -> reference-version mapping.

Every cross-version enrichment path resolves a subcap to its counterpart in the reference
catalogue (v7) the SAME way, so a base-only or id-drifted version enriches identically everywhere
and the deep-dive stat tiles never disagree with the tabs. Used by:
  * provision-time inheritance         (services/provision._inherit_enrichment)
  * read-time enrichment fallback      (routers/catalogue._map_to_reference)
  * story-ref borrowing                (services/stories._catalogue_ref_pass)
  * value-chain cascade                (services/provision._seed_value_chain)

The rule, most-specific first (stops at the first hit):
  1. exact subcap id present in the reference
  2. id-governance crosswalk (this version -> reference)
  3. exact L2-capability name + near description (token Jaccard >= 0.5)
  4. exact L2-capability name only (same capability)
  5. SEMANTIC (deep-learning) tier — only when the lexical rules find nothing AND embeddings are
     supplied: map the drifted L2 name to the nearest reference L2 by MEANING, then pick the
     reference subcap whose embedding is nearest this one. This is how a legacy version (v1-4)
     whose ids AND L1/L2 names drifted still enriches from the standard versions (v5/v7).
Otherwise the subcap is genuinely UNMAPPED -> None (callers count it; never fabricated).

Pure functions over plain dicts (no DB / no I/O) so the rule is unit-tested directly and reused
from both the provisioned-schema context and the committed-seed context. Rules 1-4 are unchanged;
rule 5 is purely additive (skipped unless ``semantic_min`` + per-row embeddings are passed), so
every existing id/crosswalk/L2 match resolves exactly as before.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

# Raised from the old 0.25 — a single shared generic token ("strategy", "policy") must NOT be
# enough to claim two different subcaps are the same capability instance.
_DESC_NEAR = 0.5


def _toks(s: str | None) -> set[str]:
    return {t for t in re.sub(r"[^a-z0-9 ]", " ", (s or "").lower()).split() if len(t) > 2}


def _norm_l2(name: str | None) -> str:
    return (name or "").strip().lower()


def _desc_near(a: str | None, b: str | None) -> bool:
    ta, tb = _toks(a), _toks(b)
    if not ta or not tb:  # need a real description on both sides to claim similarity
        return False
    return len(ta & tb) / len(ta | tb) >= _DESC_NEAR


def _cosine(a: list[float] | None, b: list[float] | None) -> float:
    """Cosine similarity of two vectors (0 when either is missing or degenerate)."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


@dataclass
class ReferenceIndex:
    """The reference catalogue's subcaps, indexed for the mapping rule (+ optional embeddings for
    the semantic tier: a drifted legacy version whose ids AND L1/L2 names differ still resolves by
    MEANING)."""

    ids: set[str]
    by_l2: dict[str, list[tuple[str, str | None]]]  # l2-name (normalised) -> [(ref_id, descr)]
    emb: dict[str, list[float]]  # ref subcap id -> vector(768) (empty when embeddings absent)
    l2_by_id: dict[str, str]  # ref subcap id -> normalised L2 name (semantic-L2 scoping)
    l2_emb: dict[str, list[float]]  # normalised L2 name -> vector (empty when absent)

    @classmethod
    def build(
        cls,
        rows: Iterable[dict[str, Any]],
        subcap_emb: dict[str, list[float]] | None = None,
        l2_emb: dict[str, list[float]] | None = None,
    ) -> ReferenceIndex:
        """rows: {id, l2, descr}. Candidate lists id-sorted so resolution is deterministic. Optional
        ``subcap_emb`` (ref id -> vector) + ``l2_emb`` (norm L2 name -> vector) light up the
        semantic tier; omit them and resolution is purely lexical (identical to before)."""
        ids: set[str] = set()
        by_l2: dict[str, list[tuple[str, str | None]]] = {}
        l2_by_id: dict[str, str] = {}
        for r in rows:
            rid = str(r["id"])
            ids.add(rid)
            l2n = _norm_l2(r.get("l2"))
            by_l2.setdefault(l2n, []).append((rid, r.get("descr")))
            l2_by_id[rid] = l2n
        for v in by_l2.values():
            v.sort(key=lambda t: t[0])
        return cls(
            ids=ids,
            by_l2=by_l2,
            emb={str(k): list(v) for k, v in (subcap_emb or {}).items()},
            l2_by_id=l2_by_id,
            l2_emb={_norm_l2(k): list(v) for k, v in (l2_emb or {}).items()},
        )


def _semantic_resolve(
    this_emb: list[float] | None,
    this_l2_emb: list[float] | None,
    ref: ReferenceIndex,
    subcap_min: float,
    l2_min: float,
) -> str | None:
    """RULE 5 — the DEEP-LEARNING tier: when the lexical rules find no capability match (a drifted
    legacy version whose L1/L2 names differ from the reference), resolve by MEANING. If the drifted
    L2 name embeds near a reference L2 (>= l2_min), scope to that capability's subcaps; then pick
    the reference subcap whose embedding is nearest this one (>= subcap_min). Meaning over spelling.
    """
    if not this_emb or not ref.emb:
        return None
    # Semantic L1/L2 understanding: map the drifted L2 name to the nearest reference L2 (if any) and
    # prefer subcaps under it — so "Digital Enablement" resolves against "Digital Transformation".
    scope: set[str] | None = None
    if this_l2_emb and ref.l2_emb and l2_min > 0:
        best_l2, best_l2_cos = None, l2_min
        for l2n, vec in ref.l2_emb.items():
            c = _cosine(this_l2_emb, vec)
            if c >= best_l2_cos:
                best_l2, best_l2_cos = l2n, c
        if best_l2 is not None:
            scope = {rid for rid, l2n in ref.l2_by_id.items() if l2n == best_l2}
    best_id, best_cos = None, subcap_min
    for rid, vec in ref.emb.items():
        if scope is not None and rid not in scope:
            continue
        c = _cosine(this_emb, vec)
        if c >= best_cos:
            best_id, best_cos = rid, c
    # Scoped search found nothing above the floor -> retry unscoped (the L2 guess may be wrong).
    if best_id is None and scope is not None:
        for rid, vec in ref.emb.items():
            c = _cosine(this_emb, vec)
            if c >= best_cos:
                best_id, best_cos = rid, c
    return best_id


def resolve(
    this_id: str,
    this_l2: str | None,
    this_descr: str | None,
    ref: ReferenceIndex,
    crosswalk: dict[str, str] | None = None,
    *,
    this_emb: list[float] | None = None,
    this_l2_emb: list[float] | None = None,
    semantic_min: float = 0.0,
    l2_semantic_min: float = 0.0,
) -> str | None:
    """Resolve one subcap to its reference id, or None if genuinely unmapped. Rules 1-4 are the
    deterministic lexical tiers (unchanged); rule 5 is the semantic (embedding) tier, applied ONLY
    when the lexical rules find nothing AND embeddings are supplied — purely additive, zero
    regression for id / crosswalk / L2 matches."""
    if this_id in ref.ids:
        return this_id
    if crosswalk:
        x = crosswalk.get(this_id)
        if x and x in ref.ids:
            return x
    cands = ref.by_l2.get(_norm_l2(this_l2))
    if cands:
        near = next((rid for rid, d in cands if _desc_near(this_descr, d)), None)
        if near:
            return near
        return cands[0][0]  # same L2 capability, no description signal — the deterministic first
    # RULE 5 (semantic): no capability-name match — resolve by meaning if embeddings are available.
    if semantic_min > 0:
        return _semantic_resolve(this_emb, this_l2_emb, ref, semantic_min, l2_semantic_min)
    return None


def resolve_map(
    rows: Iterable[dict[str, Any]],
    ref: ReferenceIndex,
    crosswalk: dict[str, str] | None = None,
    *,
    semantic_min: float = 0.0,
    l2_semantic_min: float = 0.0,
) -> tuple[dict[str, str], list[str]]:
    """Resolve many subcaps. rows: {id, l2, descr, emb?, l2_emb?}. Returns (this_id -> ref_id,
    unmapped_ids). Pass ``semantic_min`` (+ per-row ``emb`` / ``l2_emb``) to enable the semantic
    tier for a drifted legacy version."""
    mapping: dict[str, str] = {}
    unmapped: list[str] = []
    for r in rows:
        sid = str(r["id"])
        tgt = resolve(
            sid,
            r.get("l2"),
            r.get("descr"),
            ref,
            crosswalk,
            this_emb=r.get("emb"),
            this_l2_emb=r.get("l2_emb"),
            semantic_min=semantic_min,
            l2_semantic_min=l2_semantic_min,
        )
        if tgt:
            mapping[sid] = tgt
        else:
            unmapped.append(sid)
    return mapping, sorted(unmapped)
