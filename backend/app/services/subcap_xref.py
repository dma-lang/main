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
Otherwise the subcap is genuinely UNMAPPED -> None (callers count it; never fabricated).

Pure functions over plain dicts (no DB / no I/O) so the rule is unit-tested directly and reused
from both the provisioned-schema context and the committed-seed context.
"""

from __future__ import annotations

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


@dataclass
class ReferenceIndex:
    """The reference catalogue's subcaps, indexed for the mapping rule."""

    ids: set[str]
    by_l2: dict[str, list[tuple[str, str | None]]]  # l2-name (normalised) -> [(ref_id, descr)]

    @classmethod
    def build(cls, rows: Iterable[dict[str, Any]]) -> ReferenceIndex:
        """rows: {id, l2, descr}. Candidate lists are id-sorted so resolution is deterministic."""
        ids: set[str] = set()
        by_l2: dict[str, list[tuple[str, str | None]]] = {}
        for r in rows:
            rid = str(r["id"])
            ids.add(rid)
            by_l2.setdefault(_norm_l2(r.get("l2")), []).append((rid, r.get("descr")))
        for v in by_l2.values():
            v.sort(key=lambda t: t[0])
        return cls(ids=ids, by_l2=by_l2)


def resolve(
    this_id: str,
    this_l2: str | None,
    this_descr: str | None,
    ref: ReferenceIndex,
    crosswalk: dict[str, str] | None = None,
) -> str | None:
    """Resolve one subcap to its reference id, or None if genuinely unmapped."""
    if this_id in ref.ids:
        return this_id
    if crosswalk:
        x = crosswalk.get(this_id)
        if x and x in ref.ids:
            return x
    cands = ref.by_l2.get(_norm_l2(this_l2))
    if not cands:
        return None
    near = next((rid for rid, d in cands if _desc_near(this_descr, d)), None)
    if near:
        return near
    return cands[0][0]  # same L2 capability, no description signal — the deterministic first


def resolve_map(
    rows: Iterable[dict[str, Any]],
    ref: ReferenceIndex,
    crosswalk: dict[str, str] | None = None,
) -> tuple[dict[str, str], list[str]]:
    """Resolve many subcaps. rows: {id, l2, descr}. Returns (this_id -> ref_id, unmapped_ids)."""
    mapping: dict[str, str] = {}
    unmapped: list[str] = []
    for r in rows:
        sid = str(r["id"])
        tgt = resolve(sid, r.get("l2"), r.get("descr"), ref, crosswalk)
        if tgt:
            mapping[sid] = tgt
        else:
            unmapped.append(sid)
    return mapping, sorted(unmapped)
