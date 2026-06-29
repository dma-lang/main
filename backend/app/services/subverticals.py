"""Unscoped-subvertical discovery (user ask) — find clients delivering OUTSIDE the nine modelled
subverticals, infer a candidate NEW subvertical for each, and queue it as a gated, human-approved
proposal in the Change-Flags / Notifications inbox. Nothing is ever auto-applied.

Grounded only (CLAUDE.md safeguard 4): the corpus's "unscoped" delivery is every REAL Jira story
whose ``story_sv_code`` is NULL or outside the nine (synthetic is excluded by construction, like
every other delivery surface). Stories are clustered **by client** (``project_key``) — each
unscoped client is a candidate subvertical, named from its own capability profile.

The "no overlap with an existing subvertical" guard (user ask) is CLIENT-LEVEL, not subcap-level:
capabilities are horizontal (every industry does process automation), so a subcap-overlap measure
would wrongly fold a distinct industry into retail banking. Instead we ask whether the CLIENT is
already majority-classified as one of the nine: ``overlap = dom_classified / (dom_classified +
unscoped)``. A client that is mostly an existing subvertical (its unscoped stories are just
unclassified work of that SV) is NOT proposed as new; one whose unscoped delivery dominates is.

Each surviving candidate is named by the single Gemini wrapper (hermetic: a deterministic,
capability-grounded provisional name, no spend; live: the pinned enrich model, governed by G8 + the
cost meter), gated G1-G8, and written as a change_flag + reasoning chain + citation + gate run — the
full trust envelope (claim label HYPOTHESIS, source tier T1, ERS, reasoning backlink). Idempotent on
``(kind, target_ref=client)``. Hermetic-deterministic so the suite is stable.
"""

from __future__ import annotations

import json
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

_KIND = "unscoped_subvertical"
# the nine modelled subverticals; anything else (or NULL) is "unscoped" delivery
_KNOWN_SV = ("RB", "CU", "CL", "CIB", "FC", "AM", "RIA", "IC", "IB")


async def detect_unscoped_subverticals(
    version: str, min_stories: int | None = None, overlap_max: float | None = None
) -> dict[str, Any]:
    """Cluster unscoped real-Jira delivery by client, infer + gate a candidate subvertical for each
    sufficiently-large, non-overlapping client, and queue it as a change flag. Thresholds default
    from config/gates.yaml (recalibrated without a deploy). Returns a summary
    ``{version, created, proposed, overlapped, filtered, candidates, already}``."""
    cfg_min, cfg_overlap = gates.unscoped_subverticals_config()
    min_stories = cfg_min if min_stories is None else min_stories
    overlap_max = cfg_overlap if overlap_max is None else overlap_max
    v = await resolve_version(version)
    engine = db.require_engine()
    async with engine.begin() as conn:
        clusters = await _client_clusters(conn)
        profiles = await _modelled_sv_subcaps(conn)  # for the distinctness cross-check
        max_j = gates.subvertical_distinctness_max()
        created = proposed = overlapped = filtered = already = 0
        for cl in clusters:
            if cl["stories"] < min_stories:
                filtered += 1  # below the volume floor (noise) — never promoted as low-confidence
                continue
            dom_sv, dom = _dominant_classified(cl["classified"])
            overlap = dom / (dom + cl["stories"]) if dom else 0.0
            if overlap >= overlap_max:
                overlapped += 1  # client is already majority an existing SV — not a NEW one
                continue
            if await _flag_exists(conn, cl["client"]):
                already += 1  # idempotent: this client was proposed in a prior run
                continue
            dist = _distinctness(cl["subcaps"], profiles, max_j)  # deep cross-check vs the nine
            await _create_subvertical_flag(conn, v.version_id, cl, dom_sv, overlap, dist)
            created += 1
            proposed += 1
    return {
        "version": v.version_id,
        "created": created,
        "proposed": proposed,
        "overlapped": overlapped,
        "filtered": filtered,
        "already": already,
        "candidates": len(clusters),
    }


def _dominant_classified(classified: dict[str, int]) -> tuple[str | None, int]:
    """The modelled subvertical this client is MOST already classified under (or none)."""
    if not classified:
        return None, 0
    sv = max(classified, key=lambda k: classified[k])
    return sv, classified[sv]


async def _modelled_sv_subcaps(conn: AsyncConnection) -> dict[str, set[str]]:
    """Each MODELLED subvertical's delivered-subcap footprint (real Jira) — the reference profiles a
    candidate is cross-checked against for genuine distinctness."""
    rows = (
        await conn.execute(
            text(
                "SELECT s.story_sv_code AS sv, "
                "array_remove(array_agg(DISTINCT s.sub_cap_id), NULL) AS subcaps "
                "FROM control.story s WHERE NOT s.is_synthetic "
                "AND s.story_sv_code = ANY(:known) GROUP BY s.story_sv_code"
            ),
            {"known": list(_KNOWN_SV)},
        )
    ).mappings()
    return {str(r["sv"]): {str(x) for x in (r["subcaps"] or [])} for r in rows}


def _distinctness(
    candidate: set[str], profiles: dict[str, set[str]], max_jaccard: float
) -> dict[str, Any]:
    """DEEP cross-check (not just the semantic name): how close the candidate's delivered-subcap
    footprint is to each modelled subvertical (Jaccard over delivered subcaps). Returns the closest
    modelled SV + similarity + whether the candidate is genuinely DISTINCT (below the merge bar). A
    high overlap means the 'new' subvertical is really an existing one's untagged delivery — it
    should fold there, not be proposed as new."""
    best_sv: str | None = None
    best_j = 0.0
    for sv, prof in profiles.items():
        if not prof or not candidate:
            continue
        union = len(candidate | prof)
        j = len(candidate & prof) / union if union else 0.0
        if j > best_j:
            best_sv, best_j = sv, j
    return {
        "closest_sv": best_sv,
        "similarity": round(best_j, 3),
        "distinct": best_j < max_jaccard,
    }


async def _client_clusters(conn: AsyncConnection) -> list[dict[str, Any]]:
    """One cluster per client (project_key) with unscoped real delivery: volume, pillars, latest
    activity, top capabilities, distinct delivered subcaps, sample summaries, and the client's
    existing classification footprint across the nine modelled subverticals."""
    unscoped = (
        "NOT s.is_synthetic AND s.project_key IS NOT NULL "
        "AND (s.story_sv_code IS NULL OR NOT (s.story_sv_code = ANY(:known)))"
    )
    rows = (
        (
            await conn.execute(
                text(
                    "SELECT s.project_key AS client, count(*) AS stories, "
                    "count(DISTINCT s.sub_cap_id) AS subcap_n, "
                    "array_remove(array_agg(DISTINCT s.sub_cap_id), NULL) AS subcaps, "
                    "array_remove(array_agg(DISTINCT s.pillar_id), NULL) AS pillars, "
                    "max(s.created_at) AS latest "
                    f"FROM control.story s WHERE {unscoped} "
                    "GROUP BY s.project_key ORDER BY count(*) DESC"
                ),
                {"known": list(_KNOWN_SV)},
            )
        )
        .mappings()
        .all()
    )
    clients = [r["client"] for r in rows]
    if not clients:
        return []
    # top capabilities per client (unscoped stories only)
    caps: dict[str, list[dict[str, Any]]] = {c: [] for c in clients}
    for r in (
        await conn.execute(
            text(
                "SELECT s.project_key AS client, s.cap_name, count(*) AS n "
                f"FROM control.story s WHERE {unscoped} AND s.cap_name IS NOT NULL "
                "AND s.project_key = ANY(:clients) "
                "GROUP BY s.project_key, s.cap_name ORDER BY count(*) DESC"
            ),
            {"known": list(_KNOWN_SV), "clients": clients},
        )
    ).mappings():
        caps[r["client"]].append({"name": r["cap_name"], "n": int(r["n"])})
    # the client's existing classification footprint (real stories already under a modelled SV)
    classified: dict[str, dict[str, int]] = {c: {} for c in clients}
    for r in (
        await conn.execute(
            text(
                "SELECT s.project_key AS client, s.story_sv_code AS sv, count(*) AS n "
                "FROM control.story s WHERE NOT s.is_synthetic AND s.project_key = ANY(:clients) "
                "AND s.story_sv_code = ANY(:known) GROUP BY s.project_key, s.story_sv_code"
            ),
            {"known": list(_KNOWN_SV), "clients": clients},
        )
    ).mappings():
        classified[r["client"]][str(r["sv"])] = int(r["n"])
    # a few sample summaries per client (grounding the proposal — what this delivery actually is)
    samples: dict[str, list[str]] = {c: [] for c in clients}
    for r in (
        await conn.execute(
            text(
                "SELECT client, summary FROM (SELECT s.project_key AS client, s.summary, "
                "row_number() OVER (PARTITION BY s.project_key ORDER BY s.created_at DESC) AS rn "
                f"FROM control.story s WHERE {unscoped} AND s.summary IS NOT NULL "
                "AND s.project_key = ANY(:clients)) q WHERE q.rn <= 5"
            ),
            {"known": list(_KNOWN_SV), "clients": clients},
        )
    ).mappings():
        samples[r["client"]].append(str(r["summary"]))
    return [
        {
            "client": r["client"],
            "stories": int(r["stories"]),
            "subcap_n": int(r["subcap_n"]),
            "subcaps": {str(x) for x in (r["subcaps"] or [])},
            "pillars": sorted(str(p) for p in (r["pillars"] or [])),
            "latest": r["latest"],
            "top_capabilities": caps[r["client"]],
            "classified": classified[r["client"]],
            "samples": samples[r["client"]],
        }
        for r in rows
    ]


async def _flag_exists(conn: AsyncConnection, client: str) -> bool:
    return (
        await conn.execute(
            text("SELECT 1 FROM control.change_flag WHERE kind = :k AND target_ref = :t"),
            {"k": _KIND, "t": client},
        )
    ).first() is not None


async def _cluster_evidence(conn: AsyncConnection, client: str, title: str) -> str:
    """A citeable evidence row for the unscoped-delivery cluster (G5/G7), keyed on the client."""
    body = f"unscoped:{client}"
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
    cl: dict[str, Any], overlap_sv: str | None, overlap: float
) -> tuple[Any, float, dict[str, float]]:
    """Name the candidate + its trust envelope (claim label, ERS) from the cluster — the ONE place
    the model is asked. Live Vertex (R2 Phase B); until then, and on any live failure, degrade to
    the deterministic name so the detector is functional in any LLM_MODE and never crashes."""
    fingerprint = {
        "clients": [cl["client"]],
        "story_count": cl["stories"],
        "pillars": cl["pillars"],
        "top_capabilities": cl["top_capabilities"],
        "sample_summaries": cl["samples"],
        "overlap_sv": overlap_sv,
        "overlap": overlap,
    }
    try:
        inf = await Gemini().infer_subvertical_name(fingerprint)
    except NotImplementedError:
        inf = Gemini._hermetic_infer_subvertical(fingerprint)
    dom_share = (cl["top_capabilities"][0]["n"] / cl["stories"]) if cl["top_capabilities"] else 0.0
    components, ers = compute_ers(
        tier="T1",
        published=cl["latest"] or datetime.now(UTC),
        specificity=min(1.0, dom_share),
        corroboration=min(1.0, cl["stories"] / 100.0),
    )
    return inf, ers, components


async def candidates_for(
    version: str, min_stories: int | None = None, overlap_max: float | None = None
) -> list[dict[str, Any]]:
    """READ-ONLY: the unscoped-subvertical candidates as they'd be proposed — clustered, overlap-
    guarded, named (deterministic; no spend) — WITHOUT writing any gated flag. Lets the mission-
    control orange panel render the detection out of the box; the gated proposals (Notifications,
    approve/reject) are still created by the explicit/scheduled scan."""
    cfg_min, cfg_overlap = gates.unscoped_subverticals_config()
    min_stories = cfg_min if min_stories is None else min_stories
    overlap_max = cfg_overlap if overlap_max is None else overlap_max
    await resolve_version(version)
    engine = db.require_engine()
    out: list[dict[str, Any]] = []
    async with engine.connect() as conn:
        profiles = await _modelled_sv_subcaps(conn)
        max_j = gates.subvertical_distinctness_max()
        for cl in await _client_clusters(conn):
            if cl["stories"] < min_stories:
                continue
            dom_sv, dom = _dominant_classified(cl["classified"])
            overlap = dom / (dom + cl["stories"]) if dom else 0.0
            if overlap >= overlap_max:
                continue
            dist = _distinctness(cl["subcaps"], profiles, max_j)
            inf, ers, _ = await _infer(cl, dom_sv, overlap)
            out.append(
                {
                    "client": cl["client"],
                    "code": inf.code,
                    "name": inf.name,
                    "stories": cl["stories"],
                    "pillars": cl["pillars"],
                    "top_capabilities": cl["top_capabilities"][:6],
                    "samples": cl["samples"],
                    "overlap_sv": dom_sv,
                    "overlap": round(overlap, 3),
                    "distinct": dist["distinct"],
                    "distinct_closest_sv": dist["closest_sv"],
                    "distinct_similarity": dist["similarity"],
                    "claim_label": inf.claim_label,
                    "source_tier": "T1",
                    "ers": ers,
                }
            )
    return out


async def _create_subvertical_flag(
    conn: AsyncConnection,
    version_id: str,
    cl: dict[str, Any],
    overlap_sv: str | None,
    overlap: float,
    dist: dict[str, Any],
) -> None:
    client = cl["client"]
    stories = cl["stories"]
    top_caps = cl["top_capabilities"]
    inf, ers, components = await _infer(cl, overlap_sv, overlap)
    results, verdict = gates.evaluate_suggestion(
        target_exists=True,  # the active version exists; nothing is mutated, only proposed
        evidence_count=stories,
        source_tier="T1",
        cited=True,
        contradicts=False,  # the caller only writes proposals whose client overlap is below the bar
        cost_usd=inf.cost_usd,
    )
    dom_pillar = cl["pillars"][0] if cl["pillars"] else None
    overlap_note = (
        f"Closest modelled subvertical is {overlap_sv} — but only {overlap:.0%} of this client's "
        f"classified-or-unscoped delivery is {overlap_sv}, so the unscoped {stories} are a "
        "distinct segment, not unclassified work of an existing subvertical."
        if overlap_sv
        else "This client delivers nothing under any of the nine modelled subverticals."
    )
    closest = dist["closest_sv"] or "none"
    distinct_note = (
        f"Capability cross-check (deeper than the name): the client's delivered-subcap footprint "
        f"is {dist['similarity']:.0%} similar (Jaccard) to its closest modelled subvertical "
        f"({closest}) — "
        + (
            "below the merge bar, so it is genuinely DISTINCT and a real candidate."
            if dist["distinct"]
            else f"at/above the merge bar, so it is likely {closest}'s untagged delivery, "
            "not new — review to fold it there rather than model a near-duplicate."
        )
    )
    title = f"Possible new subvertical from unscoped delivery: {inf.name}"
    body = (
        f"Client {client} has {stories} real Jira stories outside the nine modelled subverticals "
        f"(synthetic excluded), spanning pillars {', '.join(cl['pillars'])}. {overlap_note} "
        f"{distinct_note} Proposed (provisional) subvertical: {inf.name} [{inf.code}]. "
        f"{inf.rationale} Approve to model it as a new candidate subvertical, or reject to keep "
        "the delivery unscoped / fold it into an existing one. Nothing is auto-applied."
    )
    summary = (
        f"Unscoped-subvertical proposal: {inf.name} [{inf.code}] from client {client} "
        f"({stories} stories, closest {overlap_sv or 'none'} {overlap:.0%})."
    )
    chain_id = (
        await conn.execute(
            text(
                "INSERT INTO control.reasoning_chain "
                "(operation, subject_ref, claim_label, summary, model, cost_usd) "
                "VALUES ('subvertical_discovery', :subj, CAST(:cl AS claim_label), :summary, "
                ":model, :cost) RETURNING chain_id"
            ),
            {
                "subj": f"{inf.code}:{client}",
                "cl": inf.claim_label,
                "summary": summary,
                "model": inf.model,
                "cost": inf.cost_usd,
            },
        )
    ).scalar_one()
    ev = await _cluster_evidence(conn, client, f"Unscoped delivery — {client}")
    cap_txt = "; ".join(f"{c['name']} ({c['n']})" for c in top_caps[:4]) or "n/a"
    steps = [
        (
            "retrieve",
            f"{stories} unscoped real Jira stories from client {client} "
            "(synthetic excluded by construction).",
            ev,
        ),
        (
            "weigh",
            f"Clustered by client; top capabilities: {cap_txt}. "
            f"Pillars {', '.join(cl['pillars'])}.",
            None,
        ),
        ("weigh", overlap_note, None),
        ("weigh", distinct_note, None),
        (
            "conclude",
            f"Inferred provisional subvertical {inf.name} [{inf.code}] ({inf.claim_label}); "
            + (
                "genuinely distinct — route to a pillar lead to confirm/rename."
                if dist["distinct"]
                else f"NOT distinct from {closest} — review to fold there, not model as new."
            ),
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
        {"c": chain_id, "t": client, "r": json.dumps(results), "v": verdict},
    )
    detail = {
        "title": title,
        "body": body,
        "name": inf.name,
        "code": inf.code,
        "pillar": dom_pillar,
        "pillars": cl["pillars"],
        "version": version_id,
        "claim_label": inf.claim_label,
        "source_tier": "T1",
        "ers": ers,
        "ers_components": components,
        "gate_failed": gates.first_failing(results),  # None when the proposal passes G1-G8
        "verdict": verdict,
        "stories": stories,
        "clients": [client],
        "top_capabilities": top_caps[:6],
        "samples": cl["samples"],
        "overlap_sv": overlap_sv,
        "overlap": round(overlap, 3),
        "distinct": dist["distinct"],
        "distinct_closest_sv": dist["closest_sv"],
        "distinct_similarity": dist["similarity"],
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
            "t": client,
            "d": json.dumps(detail),
            "c": chain_id,
        },
    )
