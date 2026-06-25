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
from pathlib import Path
from typing import Any

import yaml

# tokens that carry no discriminating meaning for cluster identity
_STOP = {"and", "the", "of", "for", "to", "a", "an", "&", "in", "on", "management", "mgmt"}
_MERGE_JACCARD = 0.6  # >= this token overlap => the same value-chain segment

# trailing parenthetical "explanation" on a VC stage label, e.g. "(SV-Specific: P3C1.8.IB1)",
# "(applicable via …)", "(Indirect: …)", "(Ag)" — noise the atlas/lens must not show.
_TRAIL_PAREN = re.compile(r"\s*\([^()]*\)\s*$")
# a verbose cross-vertical "Indirect: …" stage (a subcap only INDIRECTLY relevant to this
# subvertical) — there are ~20 of these one-subcap sentences; collapse them all into one clean,
# legit stage instead of cluttering the chain with prose.
_INDIRECT = re.compile(r"^\s*indirect\b", re.IGNORECASE)
INDIRECT_STAGE = "Indirect linkages"


_VC_LEAD_STOP = {
    "ops",
    "mgmt",
    "and",
    "the",
    "of",
    "for",
    "to",
    "in",
    "on",
    "strategy",
    "services",
    "platform",
    "via",
    "management",
}


def lead_stage_key(name: str) -> str:
    """The first distinctive token of a (cleaned) stage name, used to FOLD overlapping stages from
    other subverticals into the canonical chain on 'All SV' — e.g. "MARKET INTELLIGENCE & VERTICAL
    TARGETING" and "MARKET & FIELD-OF-MEMBERSHIP STRATEGY" both key to ``market`` and fold into
    "MARKET". Strips an "AG " industry prefix + stop-words; genuinely distinct stages (agency,
    portfolio, sector …) keep their own key and stay separate."""
    n = re.sub(r"(?i)^ag\b\s*", "", clean_stage_name(name))
    toks = [
        t
        for t in re.sub(r"[^a-z0-9 ]", " ", n.lower()).split()
        if t not in _VC_LEAD_STOP and len(t) > 2
    ]
    return toks[0] if toks else n.lower().strip()


def clean_stage_name(name: str) -> str:
    """Strip trailing parenthetical explanations from a value-chain stage label, leaving the bare
    stage name (e.g. "AUTOMATION COE (SV-Specific: P3C1.3.RB1)" -> "AUTOMATION COE"). Repeats so
    multiple trailing groups are removed; idempotent; never returns empty (keeps the original if
    stripping would empty it). Verbose "Indirect: …" cross-vertical stages collapse into one clean
    "Indirect linkages" stage. Used at provision (canonical) and read (defensive) so the atlas page
    and the mission-control value-chain lens both show clean, mergeable stage names."""
    out = (name or "").strip()
    if _INDIRECT.match(out):
        return INDIRECT_STAGE
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


# ── Canonical value-chain ROLLUP (A3 "Rollup" view) ─────────────────────────────────────────────
# The 8 MECE buckets + their ordered keyword map live in config/value_chain.yaml (DATA, not code) so
# the taxonomy is auditable and re-bucketing needs no deploy. build_rollup is PURE — the router
# supplies the per-subcap story/project/quarter maps from story_catalogue_link → control.story.


def _rollup_config_path() -> Path:
    here = Path(__file__).resolve()
    for root in here.parents:
        candidate = root / "config" / "value_chain.yaml"
        if candidate.exists():
            return candidate
    raise FileNotFoundError("config/value_chain.yaml not found")


def load_rollup_config() -> dict[str, Any]:
    """The canonical 8-stage taxonomy + ordered keyword→bucket map. Re-read each call (like
    model_config) so an edit applies without a deploy."""
    with _rollup_config_path().open() as fh:
        cfg = yaml.safe_load(fh) or {}
    if not isinstance(cfg, dict):
        raise ValueError("value_chain.yaml: top level must be a mapping")
    return cfg


def bucket_for(stage_name: str, cfg: dict[str, Any] | None = None) -> str:
    """Map a raw per-SV stage NAME to one of the 8 canonical buckets by FIRST keyword match
    (case-insensitive, against the cleaned UPPERCASE name); unmatched → default_bucket."""
    cfg = cfg or load_rollup_config()
    name = clean_stage_name(stage_name).upper()
    for entry in cfg.get("bucket_keywords", []):
        kw = str(entry.get("kw", "")).upper()
        if kw and kw in name:
            return str(entry.get("code"))
    return str(cfg.get("default_bucket", "VCC-06"))


def build_rollup(
    stages: list[dict[str, Any]],
    story_by_subcap: dict[str, set[str]],
    project_by_subcap: dict[str, set[str]] | None = None,
    story_quarter: dict[str, int] | None = None,
    *,
    cfg: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Aggregate the per-SV stages into the 8 canonical buckets, in canonical order.

    ``stages`` = [{name, subcaps:[{id,name,pillar}]}] (the endpoint's clusters). Each stage NAME is
    bucketed; a subcap in stages of two buckets counts in BOTH (matches the prototype). Per bucket:
    DISTINCT stories and projects (one spanning several subcaps counts once), a P1-P4 pillar tally,
    the top-8 subcaps by story count, and a per-quarter delivery trend (``story_quarter`` maps
    story_key->quarter index; empty until the corpus carries a real delivery date, never
    synthesized). Returns all 8 buckets (zeros if empty)."""
    cfg = cfg or load_rollup_config()
    qn = int(cfg.get("quarter_count", 6))
    project_by_subcap = project_by_subcap or {}
    story_quarter = story_quarter or {}
    default_bucket = str(cfg.get("default_bucket", "VCC-06"))
    order = [dict(s) for s in cfg.get("stages", [])]
    valid = {str(s["code"]) for s in order}

    # accumulate the UNIQUE subcaps that land in each bucket (a subcap can land in several buckets)
    bucket_subs: dict[str, dict[str, dict[str, Any]]] = {str(s["code"]): {} for s in order}
    for st in stages:
        code = bucket_for(str(st.get("name", "")), cfg)
        if code not in valid:
            code = default_bucket
        for sub in st.get("subcaps", []):
            sid = str(sub["id"])
            bucket_subs[code].setdefault(
                sid, {"id": sid, "name": sub.get("name"), "pillar": sub.get("pillar")}
            )

    out: list[dict[str, Any]] = []
    for s in order:
        code = str(s["code"])
        subs = list(bucket_subs[code].values())
        stories_union: set[str] = set()
        projects_union: set[str] = set()
        pillars = {"P1": 0, "P2": 0, "P3": 0, "P4": 0}
        for x in subs:
            stories_union |= story_by_subcap.get(x["id"], set())
            projects_union |= project_by_subcap.get(x["id"], set())
            p = str(x.get("pillar") or "")[:2]
            if p in pillars:
                pillars[p] += 1
        quarters = [0] * qn
        for sk in stories_union:
            qi = story_quarter.get(sk)
            if qi is not None and 0 <= qi < qn:
                quarters[qi] += 1
        top = sorted(
            (
                {
                    "id": x["id"],
                    "name": x["name"],
                    "n": len(story_by_subcap.get(x["id"], set())),
                    "pillar": x.get("pillar"),
                }
                for x in subs
            ),
            key=lambda t: (-int(t["n"]), str(t["id"])),
        )[:8]
        out.append(
            {
                "code": code,
                "name": s["name"],
                "blurb": s.get("blurb", ""),
                "subcaps": len(subs),
                "stories": len(stories_union),
                "projects": len(projects_union),
                "pillars": pillars,
                "quarters": quarters,
                "top": top,
            }
        )
    return out
