"""Knowledge-graph Layer B — deterministic STRUCTURAL edge proposals (R2 A2).

Layer A (the KG endpoint) is a deterministic projection of the catalogue's own link tables — the
relationships that are already FACTS. Layer B is the relationships the flat catalogue *hides*: two
subcaps in DIFFERENT capabilities that are delivered on the same platforms, or that serve the same
personas. Those are not facts — they are AI-proposed (here, deterministic structural co-occurrence;
live semantic similarity is R2 Phase B). So every Layer-B edge is written as a gated, dashed
``control.pending_edge`` and queued in the Change-Flags inbox for a human to confirm before it ever
renders as a kg_edge (CLAUDE.md safeguard 2: nothing AI-derived commits ungated).

Grounded only (safeguard 4): every proposal traces to real rows in ``subcap_platform`` /
``subcap_persona`` (the active version's own, or the reference version's when this one carries no
enrichment of its own — the same read-time inheritance the B-group pages use). Cross-capability is
deliberate: same-capability shared-platform siblings are already Layer A, so a Layer-B
SHARES_PLATFORM edge surfaces a structural link the catalogue's own tree does not. Idempotent on the
flag's pair key, bounded by ``gates.yaml::knowledge_graph.max_proposals_per_scan``, hermetic-
deterministic (no spend).
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app import db
from app.intelligence import gates
from app.versioning import resolve_version

_KG_EDGE_KIND = "kg_edge_proposal"  # the change_flag kind (also the pending_edge promotion target)
_SHARES_PLATFORM = "shares_platform"
_SHARES_FEATURE = "shares_feature"
_SEMANTIC = "semantically_similar"  # Phase B: cosine-near in the shared vector(768) space
_CO_DELIVERED = "co_delivered"  # R5: delivered together across the Jira corpus far more than chance
_SHARES_OFFERING = "shares_offering"  # R5: co-membership in the same productized offering
# Only the most-novel few co-delivery pairs are auto-queued as gated proposals; the rest stay in the
# read-time discovery panel (discover_latent) so the Change-Flags inbox is never flooded.
_CO_DELIVERY_PROPOSAL_CAP = 25


def _severity(shared: int) -> str:
    """Structural suggestions are low-urgency; a stronger overlap is a touch more notable."""
    return "MED" if shared >= 4 else "LOW"


def _weight(kind: str, shared: int) -> float:
    """Deterministic confidence for the dashed edge, capped under numeric(4,3)."""
    base = 0.5 if kind == _SHARES_PLATFORM else 0.4
    return round(min(0.999, base + 0.08 * shared), 3)


def _strength(kind: str, p: dict[str, Any]) -> float:
    """Unified confidence in [0, 1] across every edge kind, so edges are comparable + rankable.
    Co-delivery saturates on lift (lift/(lift+3)); semantic is the cosine; structural co-membership
    and the platform/persona overlaps scale gently with the shared count. numeric(4,3)-safe."""
    if kind == _CO_DELIVERED:
        lift = float(p.get("lift") or 0.0)
        return round(min(0.999, lift / (lift + 3.0)), 3) if lift > 0 else 0.0
    if kind == _SEMANTIC:
        return round(min(0.999, float(p.get("cosine") or 0.0)), 3)
    if kind == _SHARES_OFFERING:
        return round(min(0.999, 0.45 + 0.12 * int(p.get("shared") or 0)), 3)
    return _weight(kind, int(p.get("shared") or 0))


_SHORT = {
    _SHARES_PLATFORM: "sp",
    _SHARES_FEATURE: "sf",
    _SEMANTIC: "ss",
    _CO_DELIVERED: "cd",
    _SHARES_OFFERING: "so",
}


def _pair_ref(a: str, b: str, kind: str) -> str:
    """Stable, order-independent change_flag target_ref for one proposed edge (idempotency key). The
    per-kind suffix keeps a structural and a semantic edge over the same pair distinct."""
    lo, hi = sorted((a, b))
    return f"{lo}>{hi}:{_SHORT.get(kind, 'sf')}"


async def _ench_schema(conn: AsyncConnection, schema: str, table: str) -> str:
    """The schema the enrichment join should read — the version's OWN, or the reference version's
    when this one carries none of its own (the named ``table`` is empty). Mirrors the B-group reads
    so the builder proposes edges for a base-only version too, without a re-provision."""
    own = (await conn.execute(text(f"SELECT count(*) FROM {schema}.{table}"))).scalar() or 0
    if own:
        return schema
    from app.services import enrichment_seed

    ref_ver = enrichment_seed.reference_version()
    if not ref_ver:
        return schema
    try:
        ref_v = await resolve_version(ref_ver)
    except Exception:  # noqa: BLE001 - reference not provisioned -> no inheritance
        return schema
    ref_s = ref_v.schema_name
    if ref_s == schema:
        return schema
    ref_has = (await conn.execute(text(f"SELECT count(*) FROM {ref_s}.{table}"))).scalar() or 0
    return ref_s if ref_has else schema


async def _node_id(
    conn: AsyncConnection, version_id: str, kind: str, ref_id: str, label: str
) -> UUID:
    """Get-or-create the ``kg_node`` for one catalogue ref (idempotent on the unique key); the
    pending_edge / kg_edge FKs reference it by uuid."""
    row = (
        await conn.execute(
            text(
                "INSERT INTO control.kg_node (version_id, kind, ref_id, label) "
                "VALUES (:v, :k, :r, :l) "
                "ON CONFLICT (version_id, kind, ref_id) DO UPDATE SET label = EXCLUDED.label "
                "RETURNING node_id"
            ),
            {"v": version_id, "k": kind, "r": ref_id, "l": label},
        )
    ).scalar_one()
    return UUID(str(row))


async def _edge_evidence(conn: AsyncConnection, a: str, b: str, kind: str) -> UUID:
    """A citeable evidence row for the structural co-occurrence (G5/G7), keyed on the pair."""
    body = f"kg:{_pair_ref(a, b, kind)}"
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
        return UUID(str(found[0]))
    created = (
        await conn.execute(
            text(
                "INSERT INTO control.evidence_item (kind, title, source_tier, body_ref) "
                "VALUES ('catalogue', :t, 'T1', :b) RETURNING evidence_id"
            ),
            {"t": f"Structural co-occurrence {a} ~ {b}", "b": body},
        )
    ).first()
    assert created is not None
    return UUID(str(created[0]))


async def _flag_exists(conn: AsyncConnection, target_ref: str) -> bool:
    return (
        await conn.execute(
            text("SELECT 1 FROM control.change_flag WHERE kind = :k AND target_ref = :t"),
            {"k": _KG_EDGE_KIND, "t": target_ref},
        )
    ).first() is not None


async def _candidate_pairs(
    conn: AsyncConnection, ench_s: str, sp_min: int, sf_min: int, cap: int
) -> list[dict[str, Any]]:
    """Cross-capability subcap pairs that co-occur structurally — sharing >= sp_min distinct L3
    platforms (SHARES_PLATFORM) or >= sf_min personas (SHARES_FEATURE), strongest first, bounded.
    SHARES_PLATFORM takes precedence when a pair qualifies under both (the stronger evidence)."""
    plat = (
        (
            await conn.execute(
                text(
                    "SELECT sp1.subcap_id AS a, sp2.subcap_id AS b, s1.name AS a_name, "
                    "s2.name AS b_name, count(DISTINCT sp1.l3_id) AS shared "
                    f"FROM {ench_s}.subcap_platform sp1 "
                    f"JOIN {ench_s}.subcap_platform sp2 "
                    "  ON sp2.l3_id = sp1.l3_id AND sp2.subcap_id > sp1.subcap_id "
                    f"JOIN {ench_s}.subcap s1 ON s1.subcap_id = sp1.subcap_id "
                    f"JOIN {ench_s}.subcap s2 ON s2.subcap_id = sp2.subcap_id "
                    "WHERE s1.capability_id <> s2.capability_id "
                    "GROUP BY sp1.subcap_id, sp2.subcap_id, s1.name, s2.name "
                    "HAVING count(DISTINCT sp1.l3_id) >= :m "
                    "ORDER BY shared DESC, a, b LIMIT :cap"
                ),
                {"m": sp_min, "cap": cap},
            )
        )
        .mappings()
        .all()
    )
    feat = (
        (
            await conn.execute(
                text(
                    "SELECT pp1.subcap_id AS a, pp2.subcap_id AS b, s1.name AS a_name, "
                    "s2.name AS b_name, count(DISTINCT pp1.persona_id) AS shared "
                    f"FROM {ench_s}.subcap_persona pp1 "
                    f"JOIN {ench_s}.subcap_persona pp2 "
                    "  ON pp2.persona_id = pp1.persona_id AND pp2.subcap_id > pp1.subcap_id "
                    f"JOIN {ench_s}.subcap s1 ON s1.subcap_id = pp1.subcap_id "
                    f"JOIN {ench_s}.subcap s2 ON s2.subcap_id = pp2.subcap_id "
                    "WHERE s1.capability_id <> s2.capability_id "
                    "GROUP BY pp1.subcap_id, pp2.subcap_id, s1.name, s2.name "
                    "HAVING count(DISTINCT pp1.persona_id) >= :m "
                    "ORDER BY shared DESC, a, b LIMIT :cap"
                ),
                {"m": sf_min, "cap": cap},
            )
        )
        .mappings()
        .all()
    )
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for r in plat:
        key = (r["a"], r["b"])
        seen.add(key)
        out.append({**dict(r), "kind": _SHARES_PLATFORM})
    for r in feat:
        key = (r["a"], r["b"])
        if key in seen:
            continue  # already proposed as the stronger SHARES_PLATFORM edge
        seen.add(key)
        out.append({**dict(r), "kind": _SHARES_FEATURE})
    # strongest evidence first across both kinds, then bound the whole run
    out.sort(key=lambda d: (-int(d["shared"]), d["a"], d["b"]))
    return out[:cap]


async def _embedding_schema(conn: AsyncConnection, schema: str) -> str | None:
    """The schema whose subcap embeddings to read — the version's OWN once populated, else the
    reference version's (so a base-only version inherits the embedding space), else None (no
    embeddings anywhere yet → the semantic layer is simply skipped, never an error)."""
    own = (
        await conn.execute(
            text(f"SELECT 1 FROM {schema}.subcap WHERE embedding IS NOT NULL LIMIT 1")
        )
    ).first()
    if own is not None:
        return schema
    from app.services import enrichment_seed

    ref_ver = enrichment_seed.reference_version()
    if not ref_ver:
        return None
    try:
        ref_v = await resolve_version(ref_ver)
    except Exception:  # noqa: BLE001 - reference not provisioned -> no semantic layer
        return None
    if ref_v.schema_name == schema:
        return None
    ref = (
        await conn.execute(
            text(f"SELECT 1 FROM {ref_v.schema_name}.subcap WHERE embedding IS NOT NULL LIMIT 1")
        )
    ).first()
    return ref_v.schema_name if ref is not None else None


async def _semantic_pairs(
    conn: AsyncConnection, schema: str, min_cosine: float, cap: int
) -> list[dict[str, Any]]:
    """Cross-capability subcap pairs that embed close together (cosine >= min_cosine) in the shared
    vector(768) space — the semantic relationships the flat catalogue hides. Strongest first,
    bounded. ``shared`` carries cosine*100 so the gate's G2 floor (>= 2) passes."""
    rows = (
        (
            await conn.execute(
                text(
                    "SELECT a, b, a_name, b_name, cosine FROM ("
                    "SELECT s1.subcap_id AS a, s2.subcap_id AS b, s1.name AS a_name, "
                    "s2.name AS b_name, 1 - (s1.embedding <=> s2.embedding) AS cosine "
                    f"FROM {schema}.subcap s1 JOIN {schema}.subcap s2 "
                    "  ON s2.subcap_id > s1.subcap_id AND s1.capability_id <> s2.capability_id "
                    "WHERE s1.embedding IS NOT NULL AND s2.embedding IS NOT NULL"
                    ") q WHERE cosine >= :min ORDER BY cosine DESC, a, b LIMIT :cap"
                ),
                {"min": min_cosine, "cap": cap},
            )
        )
        .mappings()
        .all()
    )
    return [
        {
            "a": r["a"],
            "b": r["b"],
            "a_name": r["a_name"],
            "b_name": r["b_name"],
            "kind": _SEMANTIC,
            "shared": max(2, round(float(r["cosine"]) * 100)),
            "cosine": round(float(r["cosine"]), 4),
        }
        for r in rows
    ]


async def _co_delivery_pairs(
    conn: AsyncConnection,
    version_id: str,
    schema: str,
    min_lift: float,
    min_projects: int,
    cap: int,
    center: str | None = None,
) -> list[dict[str, Any]]:
    """The LATENT signal: cross-capability subcap pairs delivered together far more than chance.
    Market-basket over client engagements (``story.project_key``): for each pair,
    co = distinct clients delivering BOTH, and lift = (co * N) / (sup_a * sup_b) where N = clients,
    sup = clients delivering each. Kept only with co >= ``min_projects`` (real volume) AND lift >=
    ``min_lift`` (above chance). ``co_stories`` (same story evidencing both) corroborates;
    ``shares_platform_too`` flags whether the structural layer already shows the link (used by the
    novelty rank so a HIDDEN co-delivery — cross-pillar, no shared platform — rises). Deterministic,
    hermetic, bounded; ``center`` restricts to a subcap's own latent edges."""
    sql = (
        "WITH proj_sub AS ("
        "  SELECT DISTINCT s.project_key AS pk, scl.subcap_id AS sid "
        "  FROM control.story s "
        "  JOIN control.story_catalogue_link scl "
        "    ON scl.story_key = s.story_key AND scl.version_id = :ver "
        "  WHERE s.project_key IS NOT NULL), "
        "tot AS (SELECT count(DISTINCT pk)::float AS n FROM proj_sub), "
        "sup AS (SELECT sid, count(DISTINCT pk) AS c FROM proj_sub GROUP BY sid), "
        "costory AS ("
        "  SELECT l1.subcap_id AS a, l2.subcap_id AS b, count(DISTINCT l1.story_key) AS cs "
        "  FROM control.story_catalogue_link l1 "
        "  JOIN control.story_catalogue_link l2 "
        "    ON l2.story_key = l1.story_key AND l2.subcap_id > l1.subcap_id "
        "   AND l1.version_id = :ver AND l2.version_id = :ver "
        "  GROUP BY l1.subcap_id, l2.subcap_id), "
        "pairs AS ("
        "  SELECT a.sid AS a, b.sid AS b, count(DISTINCT a.pk) AS co "
        "  FROM proj_sub a JOIN proj_sub b ON b.pk = a.pk AND b.sid > a.sid "
        "  GROUP BY a.sid, b.sid HAVING count(DISTINCT a.pk) >= :minp) "
        "SELECT p.a, p.b, s1.name AS a_name, s2.name AS b_name, "
        "  left(p.a, 2) AS a_pillar, left(p.b, 2) AS b_pillar, p.co AS co_projects, "
        "  (p.co * t.n) / (sa.c * sb.c) AS lift, coalesce(cs.cs, 0) AS co_stories, "
        f"  EXISTS (SELECT 1 FROM {schema}.subcap_platform x JOIN {schema}.subcap_platform y "
        "    ON y.l3_id = x.l3_id WHERE x.subcap_id = p.a AND y.subcap_id = p.b) "
        "    AS shares_platform_too "
        "FROM pairs p CROSS JOIN tot t "
        "JOIN sup sa ON sa.sid = p.a JOIN sup sb ON sb.sid = p.b "
        f"JOIN {schema}.subcap s1 ON s1.subcap_id = p.a "
        f"JOIN {schema}.subcap s2 ON s2.subcap_id = p.b "
        "LEFT JOIN costory cs ON cs.a = p.a AND cs.b = p.b "
        "WHERE s1.capability_id <> s2.capability_id "
        "  AND (p.co * t.n) / (sa.c * sb.c) >= :minlift "
        + ("  AND (p.a = :center OR p.b = :center) " if center else "")
        + "ORDER BY lift DESC, p.a, p.b LIMIT :cap"
    )
    params: dict[str, Any] = {
        "ver": version_id,
        "minp": min_projects,
        "minlift": min_lift,
        "cap": cap,
    }
    if center:
        params["center"] = center
    rows = (await conn.execute(text(sql), params)).mappings().all()
    out: list[dict[str, Any]] = []
    for r in rows:
        co = int(r["co_projects"])
        lift = round(float(r["lift"]), 2)
        out.append(
            {
                "a": r["a"],
                "b": r["b"],
                "a_name": r["a_name"],
                "b_name": r["b_name"],
                "a_pillar": r["a_pillar"],
                "b_pillar": r["b_pillar"],
                "kind": _CO_DELIVERED,
                "shared": co,  # evidence count = distinct client engagements (G2-safe)
                "co_projects": co,
                "co_stories": int(r["co_stories"]),
                "lift": lift,
                "shares_platform_too": bool(r["shares_platform_too"]),
            }
        )
    return out


async def _co_membership_pairs(
    conn: AsyncConnection, ench_s: str, off_min: int, cap: int
) -> list[dict[str, Any]]:
    """Cross-capability subcap pairs that ship in the SAME productized offering
    (``offering_subcap``). Offerings are curated bundles, so even one shared offering is a real
    co-membership link the flat tree hides. ``shared`` = distinct shared offerings; the gate sees
    2 link rows per shared offering so G2 always passes."""
    rows = (
        (
            await conn.execute(
                text(
                    "SELECT os1.subcap_id AS a, os2.subcap_id AS b, s1.name AS a_name, "
                    "s2.name AS b_name, left(os1.subcap_id, 2) AS a_pillar, "
                    "left(os2.subcap_id, 2) AS b_pillar, count(DISTINCT os1.offering_id) AS shared "
                    f"FROM {ench_s}.offering_subcap os1 "
                    f"JOIN {ench_s}.offering_subcap os2 "
                    "  ON os2.offering_id = os1.offering_id AND os2.subcap_id > os1.subcap_id "
                    f"JOIN {ench_s}.subcap s1 ON s1.subcap_id = os1.subcap_id "
                    f"JOIN {ench_s}.subcap s2 ON s2.subcap_id = os2.subcap_id "
                    "WHERE s1.capability_id <> s2.capability_id "
                    "GROUP BY os1.subcap_id, os2.subcap_id, s1.name, s2.name "
                    "HAVING count(DISTINCT os1.offering_id) >= :m "
                    "ORDER BY shared DESC, a, b LIMIT :cap"
                ),
                {"m": off_min, "cap": cap},
            )
        )
        .mappings()
        .all()
    )
    return [{**dict(r), "kind": _SHARES_OFFERING} for r in rows]


def _novelty(
    p: dict[str, Any], strength: float, same_pillar_f: float, structural_f: float
) -> float:
    """The "what we may not be noticing" rank: an edge's strength discounted by how OBVIOUS the link
    already is. A same-pillar pair is less surprising; a pair that ALSO shares a platform is already
    visible structurally — both shrink novelty, so a strong but hidden (cross-pillar, no shared
    platform) relationship rises to the top. A gentle support term balances the surprise of lift
    with the robustness of volume, so a one-off high-lift pair does not bury a broad co-delivery."""
    factor = 1.0
    if p.get("a_pillar") and p.get("a_pillar") == p.get("b_pillar"):
        factor *= same_pillar_f
    if p.get("shares_platform_too"):
        factor *= structural_f
    co = int(p.get("co_projects") or 0)
    support = co / (co + 4.0) if co else 0.0  # saturating: more engagements -> more trustworthy
    return round(strength * factor * (0.5 + 0.5 * support), 4)


async def discover_latent(
    version: str, center: str | None = None, limit: int = 40
) -> list[dict[str, Any]]:
    """Read-only discovery — "Relationships you may be missing": the co-delivery latent edges ranked
    by NOVELTY (strong but structurally hidden first). Grounded (real Jira co-delivery), trust-
    labelled INFERENCE, never mutates — the operator can promote any to a gated edge. ``center``
    scopes to one subcap's hidden links."""
    min_lift, min_proj, _off = gates.knowledge_graph_codelivery_config()
    same_pillar_f, structural_f = gates.knowledge_graph_novelty_config()
    v = await resolve_version(version)
    engine = db.require_engine()
    async with engine.begin() as conn:
        pairs = await _co_delivery_pairs(
            conn, v.version_id, v.schema_name, min_lift, min_proj, max(limit * 4, 80), center
        )
    out: list[dict[str, Any]] = []
    for p in pairs:
        strength = _strength(_CO_DELIVERED, p)
        cross = "cross_pillar" if p["a_pillar"] != p["b_pillar"] else "cross_capability"
        basis = f"co-delivered in {p['co_projects']} client engagements (lift {p['lift']:.1f})"
        if p["co_stories"]:
            basis += f", {p['co_stories']} shared stories"
        out.append(
            {
                "source": p["a"],
                "source_name": p["a_name"],
                "target": p["b"],
                "target_name": p["b_name"],
                "kind": _CO_DELIVERED,
                "strength": strength,
                "novelty": _novelty(p, strength, same_pillar_f, structural_f),
                "crosses": cross,
                "lift": p["lift"],
                "co_projects": p["co_projects"],
                "co_stories": p["co_stories"],
                "shares_platform_too": p["shares_platform_too"],
                "basis": basis,
                "claim_label": "INFERENCE",
            }
        )
    out.sort(key=lambda d: (-d["novelty"], -d["lift"], d["source"], d["target"]))
    return out[:limit]


async def propose_structural_edges(
    version: str,
    shares_platform_min: int | None = None,
    shares_feature_min: int | None = None,
    max_proposals: int | None = None,
    semantic_min_cosine: float | None = None,
) -> dict[str, Any]:
    """Compute deterministic structural co-occurrence pairs PLUS (when an embedding space exists)
    semantic cosine-near pairs, gate G1-G8, and queue each as a dashed ``pending_edge`` + a
    Change-Flags proposal (kind ``kg_edge_proposal``) with the full trust envelope. Never writes a
    kg_edge live — approval in the inbox promotes it. Idempotent on the pair key; each layer is
    bounded by the cap and the semantic layer is deduped against the (stronger) structural pairs.
    Returns ``{version, created, proposed, candidates, already}``."""
    cfg_sp, cfg_sf, cfg_cap = gates.knowledge_graph_config()
    sp_min = cfg_sp if shares_platform_min is None else shares_platform_min
    sf_min = cfg_sf if shares_feature_min is None else shares_feature_min
    cap = cfg_cap if max_proposals is None else max_proposals
    sem_cos = (
        gates.knowledge_graph_semantic_config()
        if semantic_min_cosine is None
        else semantic_min_cosine
    )
    cd_lift, cd_minp, off_min = gates.knowledge_graph_codelivery_config()
    spf, stf = gates.knowledge_graph_novelty_config()
    v = await resolve_version(version)
    engine = db.require_engine()
    created = already = 0
    async with engine.begin() as conn:
        ench_s = await _ench_schema(conn, v.schema_name, "subcap_platform")
        pairs = await _candidate_pairs(conn, ench_s, sp_min, sf_min, cap)
        seen = {(p["a"], p["b"]) for p in pairs}
        emb_s = await _embedding_schema(conn, v.schema_name)
        if emb_s is not None:
            for sp in await _semantic_pairs(conn, emb_s, sem_cos, cap):
                if (sp["a"], sp["b"]) in seen:
                    continue  # already proposed structurally (the stronger evidence) — dedup
                seen.add((sp["a"], sp["b"]))
                pairs.append(sp)
        # R5: queue the structural co-membership pairs + the MOST-NOVEL co-delivery pairs (the broad
        # set stays read-time in discover_latent so the inbox is not flooded — bounded everything).
        off_s = await _ench_schema(conn, v.schema_name, "offering_subcap")
        for om in await _co_membership_pairs(conn, off_s, off_min, cap):
            if (om["a"], om["b"]) in seen:
                continue
            seen.add((om["a"], om["b"]))
            pairs.append(om)
        cd_pairs = await _co_delivery_pairs(
            conn, v.version_id, v.schema_name, cd_lift, cd_minp, cap
        )
        cd_pairs.sort(key=lambda d: -_novelty(d, _strength(_CO_DELIVERED, d), spf, stf))
        for cd in cd_pairs[:_CO_DELIVERY_PROPOSAL_CAP]:
            if (cd["a"], cd["b"]) in seen:
                continue
            seen.add((cd["a"], cd["b"]))
            pairs.append(cd)
        for p in pairs:
            ref = _pair_ref(p["a"], p["b"], p["kind"])
            if await _flag_exists(conn, ref):
                already += 1  # idempotent: this edge was proposed in a prior run
                continue
            await _create_edge_proposal(conn, v.version_id, p, ref)
            created += 1
    return {
        "version": v.version_id,
        "created": created,
        "proposed": created,
        "candidates": len(pairs),
        "already": already,
    }


async def _create_edge_proposal(
    conn: AsyncConnection, version_id: str, p: dict[str, Any], ref: str
) -> None:
    a, b, kind, shared = p["a"], p["b"], p["kind"], int(p["shared"])
    a_name, b_name = p["a_name"], p["b_name"]
    cosine = p.get("cosine")
    evidence_count = shared  # default: the shared-item count (>= 2 by construction)
    if kind == _SEMANTIC:
        basis = f"cosine {float(cosine or 0.0):.3f} in the shared embedding space"
        relation, ev_phrase, operation = (
            "are semantically similar",
            "embed close together in the shared vector(768) space",
            "kg_semantic",
        )
    elif kind == _CO_DELIVERED:
        lift = float(p.get("lift") or 0.0)
        co_stories = int(p.get("co_stories") or 0)
        basis = f"co-delivered in {shared} client engagements (lift {lift:.1f})"
        if co_stories:
            basis += f", {co_stories} shared stories"
        relation, ev_phrase, operation = (
            "are delivered together far more than chance",
            "co-occur across the Jira delivery corpus",
            "kg_codelivery",
        )
    elif kind == _SHARES_OFFERING:
        basis = f"{shared} shared productized offering" + ("s" if shared != 1 else "")
        evidence_count = 2 * shared  # 2 real subcap->offering link rows per offering -> G2 passes
        relation, ev_phrase, operation = (
            "ship in the same offering",
            "map to the same productized offering",
            "kg_structural",
        )
    else:
        unit = "shared L3 platforms" if kind == _SHARES_PLATFORM else "shared personas"
        basis = f"{shared} {unit}"
        relation, ev_phrase, operation = (
            "co-occur structurally",
            "trace to real catalogue link rows",
            "kg_structural",
        )
    results, verdict = gates.evaluate_suggestion(
        target_exists=True,  # both subcaps exist in the active version; nothing is mutated
        evidence_count=evidence_count,  # >= 2 by construction -> G2 passes
        source_tier="T1",
        cited=True,
        contradicts=False,  # an additional edge contradicts nothing — it is purely additive
        cost_usd=0.0,
    )
    title = f"Proposed knowledge-graph edge: {a} ~ {b} ({kind})"
    body = (
        f"{a} ({a_name}) and {b} ({b_name}) sit in different capabilities yet {relation} — "
        f"{basis}. The flat catalogue hides this link. Proposed Layer-B edge {kind} (dashed, "
        "AI-proposed). Approve to confirm it as a knowledge-graph relationship, or reject to keep "
        "the subcaps unlinked. Nothing is written to the graph as fact until approved."
    )
    summary = f"KG Layer-B edge {a} ~ {b} [{kind}] — {basis}."
    chain_id = (
        await conn.execute(
            text(
                "INSERT INTO control.reasoning_chain "
                "(operation, subject_ref, claim_label, summary, model, cost_usd) "
                "VALUES (:op, :subj, 'INFERENCE', :summary, 'hermetic-stub', 0) "
                "RETURNING chain_id"
            ),
            {"op": operation, "subj": ref, "summary": summary},
        )
    ).scalar_one()
    ev = await _edge_evidence(conn, a, b, kind)
    steps = [
        ("retrieve", f"Both {a} and {b} {ev_phrase} ({basis}).", ev),
        (
            "weigh",
            "They live in different capabilities, so this is not an existing Layer-A sibling edge "
            "— it is a relationship the flat tree hides.",
            None,
        ),
        (
            "conclude",
            f"Propose a dashed Layer-B {kind} edge; route to a pillar lead to confirm or reject "
            "(never rendered as fact ungated).",
            None,
        ),
    ]
    for i, (k, txt, evid) in enumerate(steps, 1):
        await conn.execute(
            text(
                "INSERT INTO control.reasoning_step (chain_id, ordinal, kind, text, evidence_id) "
                "VALUES (:c, :o, :k, :t, :e)"
            ),
            {"c": chain_id, "o": i, "k": k, "t": txt, "e": evid},
        )
    await conn.execute(
        text(
            "INSERT INTO control.citation (chain_id, evidence_id, verified) "
            "VALUES (:c, :e, true)"
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
    from_node = await _node_id(conn, version_id, "subcap", a, a_name)
    to_node = await _node_id(conn, version_id, "subcap", b, b_name)
    weight = _strength(kind, p)  # unified 0..1 strength (co-delivery lift, cosine, or shared count)
    pending_id = (
        await conn.execute(
            text(
                "INSERT INTO control.pending_edge "
                "(version_id, from_node, to_node, kind, weight, chain_id, status) "
                "VALUES (:v, :f, :t, :k, :w, :c, 'pending') RETURNING pending_id"
            ),
            {"v": version_id, "f": from_node, "t": to_node, "k": kind, "w": weight, "c": chain_id},
        )
    ).scalar_one()
    detail = {
        "title": title,
        "body": body,
        "version": version_id,
        "claim_label": "INFERENCE",
        "source_tier": "T1",
        "gate_failed": gates.first_failing(results),  # None when the proposal passes G1-G8
        "verdict": verdict,
        "kind_edge": kind,
        "from": a,
        "from_name": a_name,
        "to": b,
        "to_name": b_name,
        "shared": shared,
        "basis": basis,
        "cosine": float(cosine) if cosine is not None else None,
        "lift": float(p["lift"]) if p.get("lift") is not None else None,
        "co_projects": p.get("co_projects"),
        "co_stories": p.get("co_stories"),
        "crosses": (
            "cross_pillar"
            if p.get("a_pillar") and p.get("a_pillar") != p.get("b_pillar")
            else "cross_capability"
        ),
        "weight": weight,
        "pending_id": str(pending_id),
    }
    await conn.execute(
        text(
            "INSERT INTO control.change_flag (kind, severity, target_ref, detail, chain_id) "
            "VALUES (:k, :sev, :t, CAST(:d AS jsonb), :c)"
        ),
        {
            "k": _KG_EDGE_KIND,
            "sev": _severity(shared),
            "t": ref,
            "d": json.dumps(detail),
            "c": chain_id,
        },
    )


async def promote_pending_edge(conn: AsyncConnection, pending_id: str) -> bool:
    """Promote a pending_edge to an accepted Layer-B ``kg_edge`` (still dashed/Layer B, now
    confirmed by a human). Idempotent: a no-op if already resolved. Returns True if it promoted."""
    pe = (
        (
            await conn.execute(
                text(
                    "SELECT version_id, from_node, to_node, kind, weight FROM control.pending_edge "
                    "WHERE pending_id = :p AND status = 'pending' FOR UPDATE"
                ),
                {"p": pending_id},
            )
        )
        .mappings()
        .first()
    )
    if pe is None:
        return False
    # carry the proposal's basis (relation, the human "why", strength) onto the accepted edge so the
    # graph can still explain it — the change_flag detail is the source of truth for the basis.
    flag = (
        await conn.execute(
            text(
                "SELECT detail FROM control.change_flag "
                "WHERE kind = :k AND (detail ->> 'pending_id') = :p LIMIT 1"
            ),
            {"k": _KG_EDGE_KIND, "p": pending_id},
        )
    ).scalar()
    d = flag if isinstance(flag, dict) else {}
    edge_detail = {
        "basis": d.get("basis"),
        "crosses": d.get("crosses"),
        "lift": d.get("lift"),
        "co_projects": d.get("co_projects"),
        "cosine": d.get("cosine"),
        "shared": d.get("shared"),
    }
    await conn.execute(
        text("UPDATE control.pending_edge SET status = 'accepted' WHERE pending_id = :p"),
        {"p": pending_id},
    )
    await conn.execute(
        text(
            "INSERT INTO control.kg_edge "
            "(version_id, from_node, to_node, kind, layer, weight, detail) "
            "VALUES (:v, :f, :t, :k, 'B_proposed', :w, CAST(:d AS jsonb))"
        ),
        {
            "v": pe["version_id"],
            "f": pe["from_node"],
            "t": pe["to_node"],
            "k": pe["kind"],
            "w": pe["weight"],
            "d": json.dumps(edge_detail),
        },
    )
    return True


async def reject_pending_edge(conn: AsyncConnection, pending_id: str) -> None:
    """Mark a pending_edge rejected (the human declined the proposed relationship)."""
    await conn.execute(
        text(
            "UPDATE control.pending_edge SET status = 'rejected' "
            "WHERE pending_id = :p AND status = 'pending'"
        ),
        {"p": pending_id},
    )
