"""Dynamic value-chain derivation (A3) — DATA-DRIVEN, not the old hardcoded VCC-01..08.

The pillar workbooks carry no explicit "value chain" column, but they DO carry, per subcap, the L1
capability cluster it belongs to (e.g. "Strategy Foundation & Alignment"). Those clusters ARE the
value-chain segments. This module derives them per provisioned version — so v5 and v7 each get
their own chain from their own data (the derivation "cascades" by construction, never copied) — and
is SMART about it:

  * DEDUPE — clusters whose names are the same once normalised (case, punctuation, &/and, word
    order, stop-words) collapse into one. "Strategy Foundation & Alignment" and "Strategy
    Foundation and Alignment" are one segment, not two.
  * CLUSTER — near-duplicate names (high token-overlap, e.g. "Loan Origination" vs "Loan
    Origination & Underwriting") merge under a single canonical label, recorded in ``merged_from``
    so the merge is transparent and auditable, never silent.

Pure functions over plain rows (no DB) so the logic is unit-tested directly; the router supplies
the rows from ``cat_<version>``.
"""

from __future__ import annotations

import re
from typing import Any

# tokens that carry no discriminating meaning for cluster identity
_STOP = {"and", "the", "of", "for", "to", "a", "an", "&", "in", "on", "management", "mgmt"}
_MERGE_JACCARD = 0.6  # >= this token overlap => the same value-chain segment

# trailing parenthetical "explanation" on a VC stage label, e.g. "(SV-Specific: P3C1.8.IB1)",
# "(applicable via …)", "(Indirect: …)", "(Ag)" — noise the atlas/lens must not show.
_TRAIL_PAREN = re.compile(r"\s*\([^()]*\)\s*$")


def clean_stage_name(name: str) -> str:
    """Strip trailing parenthetical explanations from a value-chain stage label, leaving the bare
    stage name (e.g. "AUTOMATION COE (SV-Specific: P3C1.3.RB1)" -> "AUTOMATION COE"). Repeats so
    multiple trailing groups are removed; idempotent; never returns empty (keeps the original if
    stripping would empty it). Used at provision (canonical) and read (defensive) so the atlas page
    and the mission-control value-chain lens both show clean, mergeable stage names."""
    out = (name or "").strip()
    while True:
        nxt = _TRAIL_PAREN.sub("", out).strip()
        if nxt == out or not nxt:
            break
        out = nxt
    return out or (name or "").strip()


def _tokens(name: str) -> frozenset[str]:
    """Normalised, meaning-bearing token set for a cluster name."""
    s = name.lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return frozenset(t for t in s.split() if t and t not in _STOP)


def _norm_key(name: str) -> tuple[str, ...]:
    """Order-insensitive normalised key — equal keys are exact duplicates."""
    return tuple(sorted(_tokens(name)))


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def derive_value_chain(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """rows: [{subcap_id, name, pillar, cluster, category}] -> a deduped, clustered value chain.

    Returns {clusters:[{code, name, pillar, count, subcaps:[...], merged_from:[...]}],
    raw_clusters, deduped, total_subcaps} — clusters ordered by pillar then size, coded VCC-NN."""
    # 1) bucket subcaps by (pillar, exact-normalised cluster name) — segments are per-pillar, so the
    # same name in two pillars stays two segments (dedupe pass within a pillar)
    buckets: dict[tuple[str, ...], dict[str, Any]] = {}
    for r in rows:
        cluster = (r.get("cluster") or r.get("category") or "Uncategorised").strip()
        pillar = str(r.get("pillar") or (str(r.get("subcap_id") or "")[:2]) or "?")
        key = (pillar, *(_norm_key(cluster) or (cluster.lower(),)))
        b = buckets.setdefault(
            key,
            {"names": {}, "tokens": _tokens(cluster), "pillars": {}, "subcaps": []},
        )
        b["names"][cluster] = b["names"].get(cluster, 0) + 1  # tally surface spellings
        b["pillars"][pillar] = b["pillars"].get(pillar, 0) + 1
        b["subcaps"].append(
            {
                "id": r.get("subcap_id"),
                "name": r.get("name"),
                "pillar": pillar,
                "stage": (r.get("category") or "—"),  # the finer capability = a stage in the chain
            }
        )
    raw_count = len(buckets)

    # 2) merge near-duplicate buckets WITHIN a pillar (token overlap >= threshold)
    items = list(buckets.values())
    for it in items:
        it["pillar"] = max(it["pillars"], key=lambda p: it["pillars"][p])  # dominant pillar
    merged: list[dict[str, Any]] = []
    for it in sorted(items, key=lambda x: -len(x["subcaps"])):  # larger absorbs smaller
        target = None
        for m in merged:
            if (
                m["pillar"] == it["pillar"]
                and _jaccard(m["tokens"], it["tokens"]) >= _MERGE_JACCARD
            ):
                target = m
                break
        if target is None:
            merged.append(
                {
                    "names": dict(it["names"]),
                    "tokens": set(it["tokens"]),
                    "pillar": it["pillar"],
                    "pillars": dict(it["pillars"]),
                    "subcaps": list(it["subcaps"]),
                }
            )
        else:
            for n, c in it["names"].items():
                target["names"][n] = target["names"].get(n, 0) + c
            target["tokens"] |= it["tokens"]
            target["subcaps"].extend(it["subcaps"])
            for p, c in it["pillars"].items():
                target["pillars"][p] = target["pillars"].get(p, 0) + c

    # 3) finalise: canonical name = most common surface spelling; order; code VCC-NN
    clusters: list[dict[str, Any]] = []
    for m in merged:
        canonical = max(m["names"], key=lambda n: (m["names"][n], len(n)))
        merged_from = sorted(n for n in m["names"] if n != canonical)
        subcaps = sorted(m["subcaps"], key=lambda s: str(s["id"]))
        # stages within the segment = the finer capability groupings, in subcap order
        stage_order: list[str] = []
        stage_counts: dict[str, int] = {}
        for sc in subcaps:
            st = str(sc["stage"])
            if st not in stage_counts:
                stage_order.append(st)
            stage_counts[st] = stage_counts.get(st, 0) + 1
        clusters.append(
            {
                "name": canonical,
                "pillar": max(m["pillars"], key=lambda p: m["pillars"][p]),
                "count": len(subcaps),
                "subcaps": subcaps,
                "stages": [{"name": st, "count": stage_counts[st]} for st in stage_order],
                "merged_from": merged_from,
            }
        )
    clusters.sort(key=lambda c: (c["pillar"], -c["count"], c["name"]))
    for i, c in enumerate(clusters, 1):
        c["code"] = f"VCC-{i:02d}"

    return {
        "clusters": clusters,
        "raw_clusters": raw_count,
        "deduped": raw_count - len(clusters),
        "total_subcaps": sum(c["count"] for c in clusters),
    }
