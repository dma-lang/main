"""Use-case gap detector — surface use cases IMPLIED by delivered Jira stories that the catalogue
does not yet model, and propose each as a gated, human-approved NEW use case (Change Flags).

Modelled EXACTLY on the proven unscoped-subvertical detector (services/subverticals.py): cluster →
infer name/description/archetype → distinctness/overlap guard → gate G1-G8 → reasoning_chain + steps
+ citation + evidence + validation_gate_run → change_flag. Nothing is ever auto-applied.

Grounded only (CLAUDE.md safeguard 4): the raw signal is every carried REAL Jira story on a subcap
(``control.story_catalogue_link`` joins the synthetic-excluded analysis view, so synthetic delivery
never counts) whose summary is NOT already attributed to one of that subcap's use cases
(``control.story_use_case_link`` for the active version). Those unmatched summaries are the delivery
the catalogue's own use cases leave uncovered.

Per subcap the unmatched summaries are embedded (``Gemini().embed`` — hermetic: the deterministic
token-hash stub, no spend) and clustered greedily by cosine >= ``cluster_min_cosine``. A cluster is
a candidate use case only if it holds >= ``min_stories``. The OVERLAP guard (user ask — nothing
bloats): the cluster centroid is compared to that subcap's EXISTING use cases (their name +
description embedded); if it is >= ``overlap_max_cosine`` to any of them the cluster is SKIPPED (the
work is already covered — a near-duplicate would only bloat the catalogue). Surviving clusters are
also deduped against ones already proposed THIS run.

Each survivor is named + described + archetyped by the single Gemini wrapper (hermetic: a
deterministic, delivery-grounded proposal, no spend; live: the pinned enrich model, governed by G8 +
the cost meter), gated G1-G8, and written as a change_flag + reasoning chain + citation + gate run —
the full trust envelope (claim label HYPOTHESIS, source tier T1, ERS, reasoning backlink).
Idempotent on ``(kind, target_ref=<subcap>:<sig>)``. Deterministic + hermetic-safe + zero-spend,
bounded by
``max_proposals_per_scan``.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app import db
from app.intelligence import gates
from app.intelligence.gemini import Gemini
from app.services.change_flags import _severity  # volume->severity, shared with the other flags
from app.services.evidence import compute_ers
from app.versioning import resolve_version

_SCHEMA_RE = re.compile(r"^cat_[a-z0-9_]+$")
_KIND = "use_case_gap"
# Bound the uncovered-delivery embedded + greedily clustered per subcap (resilience: bounded
# everything). Clustering is O(n^2) in the unmatched count, so an unbounded high-volume subcap would
# dominate the scan; the newest stories (ORDER BY story_key) are a representative, deterministic
# sample and any residual gap is caught on the next weekly run.
_MAX_UNMATCHED_PER_SUBCAP = 300
_TOKEN_RE = re.compile(r"[a-z0-9]+")

# Lightweight English/Jira stopwords (mirrors use_case_match) — dropped so the top terms reflect
# CONTENT-word overlap, not boilerplate ("the system shall enable the user to ...").
_STOP = frozenset(
    (
        "a an and are as at be by for from has have in into is it its of on or that the their this "
        "to with will shall can able user users system systems story epic feature support supports "
        "provide provides using use used via per across enable enables allow allows new existing"
    ).split()
)


def _tokens(s: str) -> Counter[str]:
    """Content tokens of a text as a term-frequency vector (mirrors use_case_match): lowercase,
    alphanumeric, stopwords + very short tokens dropped, a light plural/'s' fold."""
    out: Counter[str] = Counter()
    for tok in _TOKEN_RE.findall(s.lower()):
        if len(tok) < 3 or tok in _STOP:
            continue
        if len(tok) > 4 and tok.endswith("s") and not tok.endswith("ss"):
            tok = tok[:-1]
        out[tok] += 1
    return out


def _top_terms(summaries: list[str], k: int = 8) -> list[str]:
    """The cluster's most frequent discriminating content terms (grounds the proposal name)."""
    agg: Counter[str] = Counter()
    for s in summaries:
        agg.update(_tokens(s))
    return [t for t, _ in agg.most_common(k)]


def _cosine(a: list[float], b: list[float]) -> float:
    """Cosine of two dense vectors (both are already the embedding space's output)."""
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def _centroid(vectors: list[list[float]]) -> list[float]:
    """Mean vector of a cluster (its centroid); the overlap guard measures against this."""
    n = len(vectors)
    dim = len(vectors[0])
    acc = [0.0] * dim
    for v in vectors:
        for i, x in enumerate(v):
            acc[i] += x
    return [x / n for x in acc]


def _signature(top_terms: list[str], story_keys: list[str]) -> str:
    """A stable, short signature for a cluster (idempotency key suffix). Derived from the cluster's
    top terms so a re-run over the same delivery yields the same target_ref; the story-key set is
    mixed in so two different clusters under one subcap never collide."""
    basis = "|".join(top_terms[:6]) + "#" + "|".join(sorted(story_keys))
    return hashlib.blake2b(basis.encode(), digest_size=6).hexdigest()


def _greedy_clusters(
    items: list[tuple[str, str, list[float]]], min_cosine: float
) -> list[list[tuple[str, str, list[float]]]]:
    """Greedily cluster (story_key, summary, embedding) items by cosine to the first-seen member of
    each cluster (deterministic, order-stable): an item joins the first cluster whose seed it is >=
    ``min_cosine`` to, else it seeds a new cluster. Mirrors the trend-dedupe style — a real vector
    measure, identical under hermetic and live, zero spend."""
    clusters: list[list[tuple[str, str, list[float]]]] = []
    seeds: list[list[float]] = []
    for item in items:
        placed = False
        for idx, seed in enumerate(seeds):
            if _cosine(item[2], seed) >= min_cosine:
                clusters[idx].append(item)
                placed = True
                break
        if not placed:
            clusters.append([item])
            seeds.append(item[2])
    return clusters


async def detect_use_case_gaps(version: str = "v7") -> dict[str, Any]:
    """Scan each subcap for delivered Jira stories its EXISTING use cases do not cover, cluster the
    uncovered delivery, overlap-guard each cluster against the subcap's own use cases, infer + gate
    a candidate NEW use case for each survivor, and queue it in the Change-Flags / Notifications box
    with the full trust envelope. Thresholds default from config/gates.yaml (recalibrated without a
    deploy). Idempotent on ``(kind, target_ref)``; bounded by ``max_proposals_per_scan``. Returns a
    summary ``{version, created, candidates, skipped_overlap, already}``."""
    cfg = gates.use_case_gap_config()
    v = await resolve_version(version)
    schema = v.schema_name
    if not _SCHEMA_RE.match(schema):
        raise ValueError("invalid version schema")
    engine = db.require_engine()
    gemini = Gemini()

    created = candidates = skipped_overlap = already = 0
    async with engine.begin() as conn:
        ench_s = await _use_case_schema(conn, schema)
        subcaps = await _subcaps_with_unmatched(conn, schema, v.version_id, cfg.min_stories)
        for sub in subcaps:
            if created >= cfg.max_proposals_per_scan:
                break  # resilience: bounded everything — never an unbounded run
            unmatched = await _unmatched_stories(conn, v.version_id, sub["subcap_id"])
            if len(unmatched) < cfg.min_stories:
                continue
            existing = await _existing_use_cases(conn, ench_s, sub["subcap_id"])
            # embed the unmatched summaries + the existing use-case (name + description) texts in
            # ONE batch so the stub is deterministic and the live path spends once per subcap.
            unmatched_vecs = await gemini.embed([s["summary"] for s in unmatched])
            existing_vecs = (
                await gemini.embed([f"{u['name']} {u['description']}" for u in existing])
                if existing
                else []
            )
            items = [
                (unmatched[i]["story_key"], unmatched[i]["summary"], unmatched_vecs[i])
                for i in range(len(unmatched))
            ]
            # centroids that already OCCUPY use-case space for this subcap — a previously proposed
            # cluster (already-flagged) or one created this run. A later near-duplicate is deduped
            # against these so nothing bloats; seeding it with already-flagged clusters keeps the
            # dedup (and therefore ``created``) IDENTICAL across re-runs (true idempotency).
            occupied_centroids: list[list[float]] = []
            for cluster in _greedy_clusters(items, cfg.cluster_min_cosine):
                if len(cluster) < cfg.min_stories:
                    continue
                candidates += 1
                centroid = _centroid([c[2] for c in cluster])
                overlap = max((_cosine(centroid, ev) for ev in existing_vecs), default=0.0)
                if overlap >= cfg.overlap_max_cosine:
                    skipped_overlap += 1  # already covered by an existing use case — avoid bloat
                    continue
                summaries = [c[1] for c in cluster]
                story_keys = [c[0] for c in cluster]
                top_terms = _top_terms(summaries)
                sig = _signature(top_terms, story_keys)
                ref = f"{sub['subcap_id']}:{sig}"
                if await _flag_exists(conn, ref):
                    already += 1  # idempotent: this cluster was proposed in a prior run
                    occupied_centroids.append(centroid)  # still occupies the space (dedup stable)
                    continue
                # dedupe against clusters that already occupy this subcap's use-case space THIS run
                if any(_cosine(centroid, c) >= cfg.overlap_max_cosine for c in occupied_centroids):
                    skipped_overlap += 1
                    continue
                if created >= cfg.max_proposals_per_scan:
                    break
                await _create_use_case_flag(
                    conn, v.version_id, sub, cluster, top_terms, overlap, sig, ref
                )
                occupied_centroids.append(centroid)
                created += 1
    return {
        "version": v.version_id,
        "created": created,
        "candidates": candidates,
        "skipped_overlap": skipped_overlap,
        "already": already,
    }


async def _use_case_schema(conn: AsyncConnection, schema: str) -> str:
    """The schema whose ``use_case`` table this version reads/proposes against — its own, or the
    reference version's when it carries none (a base-only version inherits the reference's use
    cases, the same read-time inheritance the Use Case Explorer + story->use-case matcher use)."""
    own = (await conn.execute(text(f"SELECT count(*) FROM {schema}.use_case"))).scalar() or 0
    if own:
        return schema
    from app.services import enrichment_seed

    ref = enrichment_seed.reference_version()
    if not ref:
        return schema
    try:
        ref_v = await resolve_version(ref)
    except Exception:  # noqa: BLE001 - reference not provisioned -> match against own (empty)
        return schema
    ref_s = ref_v.schema_name
    if ref_s == schema or not _SCHEMA_RE.match(ref_s):
        return schema
    ref_has = (await conn.execute(text(f"SELECT count(*) FROM {ref_s}.use_case"))).scalar() or 0
    return ref_s if ref_has else schema


async def _subcaps_with_unmatched(
    conn: AsyncConnection, schema: str, version_id: str, min_stories: int
) -> list[dict[str, Any]]:
    """Subcaps carrying at least ``min_stories`` REAL Jira stories that are NOT attributed to any of
    that subcap's use cases in this version (the story->use-case matcher left them subcap-level),
    with the subcap's own name (from the active version) to ground the proposal. The per-subcap pass
    then re-derives + clusters those unmatched summaries. Ordered by uncovered volume so the loudest
    gaps surface first, then the id (deterministic)."""
    rows = (
        (
            await conn.execute(
                text(
                    "SELECT g.subcap_id, g.unmatched, left(g.subcap_id, 2) AS pillar, s.name "
                    "FROM (SELECT scl.subcap_id, count(*) AS unmatched "
                    "FROM control.story_catalogue_link scl WHERE scl.version_id = :ver "
                    "AND NOT EXISTS (SELECT 1 FROM control.story_use_case_link sul "
                    "WHERE sul.version_id = :ver AND sul.story_key = scl.story_key) "
                    "GROUP BY scl.subcap_id HAVING count(*) >= :min) g "
                    f"JOIN {schema}.subcap s ON s.subcap_id = g.subcap_id "
                    "ORDER BY g.unmatched DESC, g.subcap_id"
                ),
                {"ver": version_id, "min": min_stories},
            )
        )
        .mappings()
        .all()
    )
    return [dict(r) for r in rows]


async def _unmatched_stories(
    conn: AsyncConnection, version_id: str, subcap_id: str
) -> list[dict[str, Any]]:
    """The carried REAL Jira stories on ``subcap_id`` with a non-empty summary that are NOT matched
    to any of the subcap's use cases in this version — the uncovered delivery to cluster. Ordered by
    story_key so the greedy clustering is deterministic."""
    rows = (
        (
            await conn.execute(
                text(
                    "SELECT scl.story_key, coalesce(st.summary, '') AS summary "
                    "FROM control.story_catalogue_link scl "
                    "JOIN control.story st ON st.story_key = scl.story_key "
                    "WHERE scl.version_id = :ver AND scl.subcap_id = :sub "
                    "AND coalesce(st.summary, '') <> '' "
                    "AND NOT EXISTS (SELECT 1 FROM control.story_use_case_link sul "
                    "WHERE sul.version_id = :ver AND sul.story_key = scl.story_key) "
                    "ORDER BY scl.story_key LIMIT :cap"
                ),
                {"ver": version_id, "sub": subcap_id, "cap": _MAX_UNMATCHED_PER_SUBCAP},
            )
        )
        .mappings()
        .all()
    )
    return [dict(r) for r in rows]


async def _existing_use_cases(
    conn: AsyncConnection, ench_s: str, subcap_id: str
) -> list[dict[str, Any]]:
    """The subcap's EXISTING use cases (name + description) — the overlap guard's reference set, so
    a cluster that a modelled use case already covers is skipped, never re-proposed (no bloat)."""
    rows = (
        (
            await conn.execute(
                text(
                    "SELECT use_case_id, coalesce(name, '') AS name, "
                    "coalesce(description, '') AS description "
                    f"FROM {ench_s}.use_case WHERE subcap_id = :sub ORDER BY use_case_id"
                ),
                {"sub": subcap_id},
            )
        )
        .mappings()
        .all()
    )
    return [dict(r) for r in rows]


async def _flag_exists(conn: AsyncConnection, target_ref: str) -> bool:
    return (
        await conn.execute(
            text("SELECT 1 FROM control.change_flag WHERE kind = :k AND target_ref = :t"),
            {"k": _KIND, "t": target_ref},
        )
    ).first() is not None


async def _cluster_evidence(conn: AsyncConnection, ref: str, title: str) -> str:
    """A citeable evidence row for the uncovered-delivery cluster (G5/G7), keyed on target_ref."""
    body = f"uc_gap:{ref}"
    found = (
        await conn.execute(
            text(
                "SELECT evidence_id FROM control.evidence_item "
                "WHERE kind = 'catalogue' AND body_ref = :b"
            ),
            {"b": body},
        )
    ).first()
    if found is not None:
        return str(found[0])
    created = (
        await conn.execute(
            text(
                "INSERT INTO control.evidence_item (kind, title, source_tier, body_ref) "
                "VALUES ('catalogue', :t, 'T1', :b) RETURNING evidence_id"
            ),
            {"t": title, "b": body},
        )
    ).first()
    assert created is not None
    return str(created[0])


async def _infer(
    sub: dict[str, Any],
    cluster: list[tuple[str, str, list[float]]],
    top_terms: list[str],
    overlap: float,
) -> tuple[Any, float, dict[str, float]]:
    """Name + describe the candidate use case + its trust envelope (claim label, ERS) — the ONE
    place the model is asked. Live Vertex (enrich model); on any live failure it degrades to the
    deterministic proposal, so the detector is functional in any LLM_MODE and never crashes."""
    samples = [c[1] for c in cluster[:5]]
    fingerprint = {
        "subcap_id": sub["subcap_id"],
        "subcap_name": sub.get("name") or sub["subcap_id"],
        "pillar": sub.get("pillar"),
        "story_count": len(cluster),
        "top_terms": top_terms,
        "sample_summaries": samples,
        "overlap_score": overlap,
    }
    inf = await Gemini().infer_use_case_name(fingerprint)
    components, ers = compute_ers(
        tier="T1",
        published=datetime.now(UTC),
        specificity=min(1.0, len(top_terms) / 8.0),
        corroboration=min(1.0, len(cluster) / 50.0),
    )
    return inf, ers, components


async def _create_use_case_flag(
    conn: AsyncConnection,
    version_id: str,
    sub: dict[str, Any],
    cluster: list[tuple[str, str, list[float]]],
    top_terms: list[str],
    overlap: float,
    sig: str,
    ref: str,
) -> None:
    subcap_id = sub["subcap_id"]
    pillar = sub.get("pillar")
    stories = len(cluster)
    samples = [c[1] for c in cluster[:5]]
    inf, ers, components = await _infer(sub, cluster, top_terms, overlap)
    results, verdict = gates.evaluate_suggestion(
        target_exists=True,  # the subcap exists in the active version; nothing is mutated here
        evidence_count=stories,
        source_tier="T1",
        cited=True,
        contradicts=False,  # a NEW use case is purely additive — it contradicts no delivery reality
        cost_usd=inf.cost_usd,
    )
    term_txt = ", ".join(top_terms[:6]) or "recurring delivery themes"
    overlap_note = (
        f"The cluster centroid is only {overlap:.0%} similar to the subcap's closest EXISTING use "
        "case (below the merge bar), so this delivery is genuinely uncovered — a new use case, not "
        "a near-duplicate that would bloat the catalogue."
        if overlap
        else "The subcap has no existing use case that covers this delivery."
    )
    title = f"Possible new use case from delivery: {inf.name}"
    body = (
        f"{stories} real Jira stories delivered under {subcap_id} "
        f"({sub.get('name') or 'subcap'}) cluster on {term_txt}, yet none is attributed to an "
        f"existing use case. {overlap_note} Proposed (provisional) use case: {inf.name} "
        f"[{inf.archetype}]. {inf.description} {inf.rationale} Approve to add it as a new use case "
        "(re-gated server-side, versioned + audited), or reject to keep the delivery subcap-level. "
        "Nothing is auto-applied."
    )
    summary = (
        f"Use-case gap proposal: {inf.name} [{inf.archetype}] under {subcap_id} "
        f"({stories} stories, overlap {overlap:.0%})."
    )
    chain_id = (
        await conn.execute(
            text(
                "INSERT INTO control.reasoning_chain "
                "(operation, subject_ref, claim_label, summary, model, cost_usd) "
                "VALUES ('use_case_gap_discovery', :subj, CAST(:cl AS claim_label), :summary, "
                ":model, :cost) RETURNING chain_id"
            ),
            {
                "subj": ref,
                "cl": inf.claim_label,
                "summary": summary,
                "model": inf.model,
                "cost": inf.cost_usd,
            },
        )
    ).scalar_one()
    ev = await _cluster_evidence(conn, ref, f"Uncovered delivery — {subcap_id}")
    steps = [
        (
            "retrieve",
            f"{stories} real Jira stories carried onto {subcap_id} are NOT attributed to any of "
            "its existing use cases (synthetic excluded by construction).",
            ev,
        ),
        (
            "weigh",
            f"Clustered the uncovered summaries by embedding cosine; the cluster concentrates on "
            f"{term_txt}.",
            None,
        ),
        ("weigh", overlap_note, None),
        (
            "conclude",
            f"Inferred provisional use case {inf.name} [{inf.archetype}] ({inf.claim_label}) — "
            "route to a pillar lead to confirm/rename; approve re-gates + inserts it as a new use "
            "case, reject keeps the delivery subcap-level.",
            None,
        ),
    ]
    for i, (kind, txt, evid) in enumerate(steps, 1):
        await conn.execute(
            text(
                "INSERT INTO control.reasoning_step (chain_id, ordinal, kind, text, evidence_id) "
                "VALUES (:c, :o, :k, :t, :e)"
            ),
            {"c": chain_id, "o": i, "k": kind, "t": txt, "e": evid},
        )
    await conn.execute(
        text(
            "INSERT INTO control.citation (chain_id, evidence_id, verified) VALUES (:c, :e, true)"
        ),
        {"c": chain_id, "e": ev},
    )
    await conn.execute(
        text(
            "INSERT INTO control.validation_gate_run (chain_id, target_ref, gate_results, verdict) "
            "VALUES (:c, :t, CAST(:r AS jsonb), CAST(:v AS gate_verdict))"
        ),
        {"c": chain_id, "t": ref, "r": json.dumps(results), "v": verdict},
    )
    detail = {
        "title": title,
        "body": body,
        "name": inf.name,
        "description": inf.description,
        "archetype": inf.archetype,
        "subcap_id": subcap_id,
        "pillar": pillar,
        "version": version_id,
        "claim_label": inf.claim_label,
        "source_tier": "T1",
        "ers": ers,
        "ers_components": components,
        "gate_failed": gates.first_failing(results),  # None when the proposal passes G1-G8
        "verdict": verdict,
        "stories": stories,
        "top_terms": top_terms,
        "samples": samples,
        "overlap_score": round(overlap, 3),
        "model": inf.model,
        "cost": inf.cost_usd,
    }
    await conn.execute(
        text(
            "INSERT INTO control.change_flag (kind, severity, target_ref, detail, chain_id) "
            "VALUES (:k, :sev, :t, CAST(:d AS jsonb), :c)"
        ),
        {
            "k": _KIND,
            "sev": _severity(stories),
            "t": ref,
            "d": json.dumps(detail),
            "c": chain_id,
        },
    )
