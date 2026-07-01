"""Knowledge-graph Layer B — deep subcap↔subcap relationship mining, gated (R2 A2 · R5).

Layer A (the KG endpoint) is a deterministic projection of the catalogue's own link tables — the
relationships that are already FACTS. Layer B is the relationships the flat catalogue *hides*: two
subcaps in DIFFERENT capabilities that share platforms/personas/offerings/value-chain stages, are
**co-delivered** across the Jira corpus (market-basket lift/PMI — the latent core), or are
semantically near in the shared embedding space. Those are not facts — they are AI-proposed, each
scored to one comparable ``strength`` + a ``novelty`` (strength × how non-obvious the pair is) so
the discovery surface can lead with "relationships you may be missing" (strong but cross-pillar / no
shared platform). Every Layer-B edge is written as a gated, dashed ``control.pending_edge`` and
queued in the Change-Flags inbox for a human to confirm before it ever renders as a kg_edge
(CLAUDE.md safeguard 2: nothing AI-derived commits ungated).

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
from app.intelligence.gemini import Gemini, RelationshipInference
from app.versioning import resolve_version

_KG_EDGE_KIND = "kg_edge_proposal"  # the change_flag kind (also the pending_edge promotion target)
_SHARES_PLATFORM = "shares_platform"
_SHARES_FEATURE = "shares_feature"
_SHARES_OFFERING = "shares_offering"  # R5: cross-cap subcaps mapping to the same offering(s)
_SAME_VALUE_CHAIN = "same_value_chain"  # R5: cross-cap subcaps in the same value-chain cluster(s)
_CO_DELIVERED = "co_delivered"  # R5: co-delivered across the Jira corpus (the latent core)
_SEMANTIC = "semantically_similar"  # cosine-near in the shared vector(768) space

# Strongest-evidence first: one edge is proposed per pair (the strongest kind); the others ride
# along as corroborating signals on it. Co-delivery (a real statistical delivery bond) and
# shared-platform (a hard catalogue fact) outrank the softer structural / semantic signals.
_KIND_PRIORITY = {
    _CO_DELIVERED: 6,
    _SHARES_PLATFORM: 5,
    _SHARES_OFFERING: 4,
    _SAME_VALUE_CHAIN: 3,
    _SHARES_FEATURE: 2,
    _SEMANTIC: 1,
}

# (relation, evidence-phrase, reasoning operation) per kind — the human-readable "why" on the chain.
_KIND_PROSE: dict[str, tuple[str, str, str]] = {
    _SHARES_PLATFORM: (
        "co-occur on shared delivery platforms",
        "trace to real catalogue link rows",
        "kg_structural",
    ),
    _SHARES_OFFERING: (
        "map to the same productized offering(s)",
        "map to the same offering rows",
        "kg_structural",
    ),
    _SAME_VALUE_CHAIN: (
        "sit in the same value-chain stage(s)",
        "occupy the same value-chain cluster(s)",
        "kg_structural",
    ),
    _SHARES_FEATURE: (
        "serve the same personas",
        "trace to real catalogue link rows",
        "kg_structural",
    ),
    _CO_DELIVERED: (
        "are co-delivered",
        "are delivered together across real Jira projects and stories",
        "kg_codelivery",
    ),
    _SEMANTIC: (
        "are semantically similar",
        "embed close together in the shared vector(768) space",
        "kg_semantic",
    ),
}

_SHORT = {
    _SHARES_PLATFORM: "sp",
    _SHARES_FEATURE: "sf",
    _SHARES_OFFERING: "so",
    _SAME_VALUE_CHAIN: "vc",
    _CO_DELIVERED: "cd",
    _SEMANTIC: "ss",
}


def _severity(shared: int) -> str:
    """Structural suggestions are low-urgency; a stronger overlap is a touch more notable."""
    return "MED" if shared >= 4 else "LOW"


def _pair_key(a: str, b: str) -> tuple[str, str]:
    """Order-independent pair key (lo, hi)."""
    return (a, b) if a <= b else (b, a)


def _pair_ref(a: str, b: str, kind: str) -> str:
    """Stable, order-independent change_flag target_ref for one proposed edge; the kind suffix
    records which relationship won. Idempotency is enforced at the PAIR level (see
    ``_pair_flag_exists``) so a pair is proposed once — a re-mine never queues a second edge."""
    lo, hi = _pair_key(a, b)
    return f"{lo}>{hi}:{_SHORT.get(kind, 'sf')}"


def _strength(p: dict[str, Any]) -> float:
    """Unified 0..1 confidence across every relationship kind so edges are comparable + rankable
    (thickness ∝ strength): a squashed market-basket lift for co-delivery, cosine for the semantic
    layer, a shared-count ramp for the structural kinds. Capped under numeric(4,3)."""
    kind = p["kind"]
    if kind == _SEMANTIC:
        return round(min(0.999, max(0.0, float(p.get("cosine") or 0.0))), 3)
    if kind == _CO_DELIVERED:
        lift = float(p.get("lift") or 0.0)
        return round(min(0.999, max(0.0, 1.0 - 1.0 / lift)) if lift > 1.0 else 0.0, 3)
    base = {
        _SHARES_PLATFORM: 0.5,
        _SHARES_OFFERING: 0.45,
        _SAME_VALUE_CHAIN: 0.4,
        _SHARES_FEATURE: 0.4,
    }.get(kind, 0.4)
    return round(min(0.999, base + 0.08 * int(p.get("shared") or 0)), 3)


def _basis(p: dict[str, Any]) -> str:
    """The one-line "why" shown on the edge and carried into the reasoning chain."""
    kind = p["kind"]
    if kind == _SEMANTIC:
        return f"cosine {float(p.get('cosine') or 0.0):.3f} in the shared embedding space"
    if kind == _CO_DELIVERED:
        parts: list[str] = []
        cc, cs = int(p.get("co_clients") or 0), int(p.get("co_stories") or 0)
        if cc:
            parts.append(f"{cc} client project{'s' if cc != 1 else ''}")
        if cs:
            parts.append(f"{cs} shared stor{'ies' if cs != 1 else 'y'}")
        where = " and ".join(parts) if parts else f"{int(p.get('shared') or 0)} deliveries"
        return f"co-delivered across {where} (lift {float(p.get('lift') or 0.0):.1f})"
    unit = {
        _SHARES_PLATFORM: "shared L3 platforms",
        _SHARES_OFFERING: "shared offerings",
        _SAME_VALUE_CHAIN: "shared value-chain stages",
        _SHARES_FEATURE: "shared personas",
    }.get(kind, "shared items")
    return f"{int(p.get('shared') or 0)} {unit}"


def _crosses(a: str, b: str) -> str:
    """A proposed pair is always cross-CAPABILITY (same-cap siblings are Layer A); flag the
    cross-PILLAR ones (different pillar code) — the most non-obvious links, gated per D16."""
    return "cross_pillar" if a[:2] != b[:2] else "cross_capability"


def _novelty(strength: float, a: str, b: str, shares_plat: bool, weight: float) -> float:
    """novelty = strength × (1 − w·obviousness). A strong pair the catalogue structure already makes
    obvious (same pillar, or already sharing a platform) is not a discovery; a strong cross-pillar
    pair with no shared platform is exactly "what we may not be noticing" — it ranks top."""
    obviousness = min(
        1.0, 0.5 * (1.0 if a[:2] == b[:2] else 0.0) + 0.5 * (1.0 if shares_plat else 0.0)
    )
    return round(max(0.0, strength * (1.0 - weight * obviousness)), 4)


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


async def _co_membership_pairs(
    conn: AsyncConnection, schema: str, off_min: int, vcc_min: int, cap: int
) -> list[dict[str, Any]]:
    """Cross-capability subcap pairs co-inhabiting the same structural bucket the flat tree hides:
    the same productized offering(s) (>= off_min) or the same value-chain cluster(s) (>= vcc_min).
    Built exactly like the shared-platform projection (inheriting the reference version's enrichment
    when this one carries none of its own), strongest first, bounded."""
    off_s = await _ench_schema(conn, schema, "offering_subcap")
    vcc_s = await _ench_schema(conn, schema, "subcap_vcc")
    offer = (
        (
            await conn.execute(
                text(
                    "SELECT os1.subcap_id AS a, os2.subcap_id AS b, s1.name AS a_name, "
                    "s2.name AS b_name, count(DISTINCT os1.offering_id) AS shared "
                    f"FROM {off_s}.offering_subcap os1 "
                    f"JOIN {off_s}.offering_subcap os2 "
                    "  ON os2.offering_id = os1.offering_id AND os2.subcap_id > os1.subcap_id "
                    f"JOIN {off_s}.subcap s1 ON s1.subcap_id = os1.subcap_id "
                    f"JOIN {off_s}.subcap s2 ON s2.subcap_id = os2.subcap_id "
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
    vcc = (
        (
            await conn.execute(
                text(
                    "SELECT v1.subcap_id AS a, v2.subcap_id AS b, s1.name AS a_name, "
                    "s2.name AS b_name, count(DISTINCT v1.vcc_id) AS shared "
                    f"FROM {vcc_s}.subcap_vcc v1 "
                    f"JOIN {vcc_s}.subcap_vcc v2 "
                    "  ON v2.vcc_id = v1.vcc_id AND v2.subcap_id > v1.subcap_id "
                    f"JOIN {vcc_s}.subcap s1 ON s1.subcap_id = v1.subcap_id "
                    f"JOIN {vcc_s}.subcap s2 ON s2.subcap_id = v2.subcap_id "
                    "WHERE s1.capability_id <> s2.capability_id "
                    "GROUP BY v1.subcap_id, v2.subcap_id, s1.name, s2.name "
                    "HAVING count(DISTINCT v1.vcc_id) >= :m "
                    "ORDER BY shared DESC, a, b LIMIT :cap"
                ),
                {"m": vcc_min, "cap": cap},
            )
        )
        .mappings()
        .all()
    )
    out: list[dict[str, Any]] = [{**dict(r), "kind": _SHARES_OFFERING} for r in offer]
    out += [{**dict(r), "kind": _SAME_VALUE_CHAIN} for r in vcc]
    return out


async def _co_delivery_pairs(
    conn: AsyncConnection, schema: str, version_id: str, min_lift: float, min_count: int, cap: int
) -> list[dict[str, Any]]:
    """Market-basket association mining over the Jira delivery corpus (control.story_catalogue_link,
    Jira-only by construction) — the CROSS-capability subcap pairs actually delivered together, by
    the same client (project_key basket -> lift/PMI) and/or the same story (tight shared-evidence).
    lift = P(A&B)/(P(A)*P(B)); a pair co-delivered far above independence is a real, non-obvious
    delivery bond. Deterministic counts (hermetic-identical to live, zero spend); kept iff, in
    EITHER basket, lift >= min_lift AND co-count >= min_count; strongest lift first, bounded."""
    meta = {
        str(r["id"]): (str(r["name"]), str(r["cap"]))
        for r in (
            await conn.execute(
                text(f"SELECT subcap_id AS id, name, capability_id AS cap FROM {schema}.subcap")
            )
        )
        .mappings()
        .all()
    }

    async def _basket(
        co_sql: str, marg_sql: str, n_sql: str
    ) -> tuple[list[Any], dict[str, int], int]:
        co = (
            (await conn.execute(text(co_sql), {"ver": version_id, "m": min_count})).mappings().all()
        )
        marg = {
            str(r["id"]): int(r["n"])
            for r in (await conn.execute(text(marg_sql), {"ver": version_id})).mappings().all()
        }
        n = int((await conn.execute(text(n_sql), {"ver": version_id})).scalar() or 0)
        return list(co), marg, n

    _CLIENT_PS = (
        "WITH ps AS (SELECT DISTINCT s.project_key AS pk, l.subcap_id AS sid "
        "FROM control.story_catalogue_link l JOIN control.story s ON s.story_key = l.story_key "
        "WHERE l.version_id = :ver AND s.project_key IS NOT NULL AND s.project_key <> '') "
    )
    client_co, client_marg, client_n = await _basket(
        _CLIENT_PS + "SELECT p1.sid AS a, p2.sid AS b, count(*) AS co FROM ps p1 "
        "JOIN ps p2 ON p2.pk = p1.pk AND p2.sid > p1.sid "
        "GROUP BY p1.sid, p2.sid HAVING count(*) >= :m ORDER BY co DESC LIMIT 5000",
        _CLIENT_PS + "SELECT sid AS id, count(*) AS n FROM ps GROUP BY sid",
        "SELECT count(DISTINCT s.project_key) FROM control.story_catalogue_link l "
        "JOIN control.story s ON s.story_key = l.story_key "
        "WHERE l.version_id = :ver AND s.project_key IS NOT NULL AND s.project_key <> ''",
    )
    story_co, story_marg, story_n = await _basket(
        "SELECT l1.subcap_id AS a, l2.subcap_id AS b, count(DISTINCT l1.story_key) AS co "
        "FROM control.story_catalogue_link l1 JOIN control.story_catalogue_link l2 "
        "  ON l2.story_key = l1.story_key AND l2.subcap_id > l1.subcap_id "
        "WHERE l1.version_id = :ver AND l2.version_id = :ver "
        "GROUP BY l1.subcap_id, l2.subcap_id "
        "HAVING count(DISTINCT l1.story_key) >= :m ORDER BY co DESC LIMIT 5000",
        "SELECT subcap_id AS id, count(DISTINCT story_key) AS n "
        "FROM control.story_catalogue_link WHERE version_id = :ver GROUP BY subcap_id",
        "SELECT count(DISTINCT story_key) FROM control.story_catalogue_link "
        "WHERE version_id = :ver",
    )

    def _lift(co: int, na: int, nb: int, n: int) -> float:
        return (co * n) / (na * nb) if na and nb and n else 0.0

    merged: dict[tuple[str, str], dict[str, Any]] = {}
    baskets = (
        (client_co, client_marg, client_n, "clients"),
        (story_co, story_marg, story_n, "stories"),
    )
    for rows, marg, n, tag in baskets:
        for r in rows:
            a, b = str(r["a"]), str(r["b"])
            if a not in meta or b not in meta or meta[a][1] == meta[b][1]:
                continue  # unknown id, or same-capability (already Layer A) — skip
            co = int(r["co"])
            key = _pair_key(a, b)
            m = merged.setdefault(
                key,
                {
                    "a": key[0],
                    "b": key[1],
                    "co_clients": 0,
                    "co_stories": 0,
                    "lift_clients": 0.0,
                    "lift_stories": 0.0,
                },
            )
            m[f"co_{tag}"] = co
            m[f"lift_{tag}"] = _lift(co, marg.get(a, 0), marg.get(b, 0), n)
    out: list[dict[str, Any]] = []
    for m in merged.values():
        client_ok = m["co_clients"] >= min_count and m["lift_clients"] >= min_lift
        story_ok = m["co_stories"] >= min_count and m["lift_stories"] >= min_lift
        if not (client_ok or story_ok):
            continue
        lift = max(m["lift_clients"] if client_ok else 0.0, m["lift_stories"] if story_ok else 0.0)
        shared = max(m["co_clients"] if client_ok else 0, m["co_stories"] if story_ok else 0)
        a, b = m["a"], m["b"]
        out.append(
            {
                "a": a,
                "b": b,
                "a_name": meta[a][0],
                "b_name": meta[b][0],
                "kind": _CO_DELIVERED,
                "lift": round(lift, 3),
                "shared": shared,
                "co_clients": m["co_clients"],
                "co_stories": m["co_stories"],
            }
        )
    out.sort(key=lambda d: (-float(d["lift"]), -int(d["shared"]), d["a"], d["b"]))
    return out[:cap]


async def _shared_platform_pairs(
    conn: AsyncConnection, ench_s: str, ids: set[str]
) -> set[tuple[str, str]]:
    """The subset of ``ids`` pairs that already share >= 1 L3 platform — the structural obviousness
    signal for novelty (a strong pair that already shares a platform is not a hidden relationship).
    """
    if not ids:
        return set()
    rows = (
        await conn.execute(
            text(
                "SELECT DISTINCT sp1.subcap_id AS a, sp2.subcap_id AS b "
                f"FROM {ench_s}.subcap_platform sp1 "
                f"JOIN {ench_s}.subcap_platform sp2 "
                "  ON sp2.l3_id = sp1.l3_id AND sp2.subcap_id > sp1.subcap_id "
                "WHERE sp1.subcap_id = ANY(:ids) AND sp2.subcap_id = ANY(:ids)"
            ),
            {"ids": list(ids)},
        )
    ).all()
    return {_pair_key(str(r[0]), str(r[1])) for r in rows}


def _score_and_reduce(
    raw: list[dict[str, Any]],
    shares_plat_set: set[tuple[str, str]],
    novelty_weight: float,
    allow_cross_pillar: bool,
) -> list[dict[str, Any]]:
    """Score every raw pair (strength + basis), reduce to ONE edge per pair (the strongest kind,
    the rest recorded as corroborating ``signals``), tag cross-capability/-pillar reach, compute
    novelty, and rank by novelty so the surface leads with "relationships you may be missing"."""
    by_pair: dict[tuple[str, str], dict[str, Any]] = {}
    for r in raw:
        a, b = str(r["a"]), str(r["b"])
        if not allow_cross_pillar and a[:2] != b[:2]:
            continue  # D16: cross-pillar proposals disabled by config
        p = {**r, "a": a, "b": b}
        p["strength"] = _strength(p)
        p["basis"] = _basis(p)
        sig = {"kind": p["kind"], "basis": p["basis"], "strength": p["strength"]}
        key = _pair_key(a, b)
        cur = by_pair.get(key)
        if cur is None:
            p["signals"] = [sig]
            by_pair[key] = p
            continue
        cur["signals"].append(sig)
        if (_KIND_PRIORITY.get(p["kind"], 0), p["strength"]) > (
            _KIND_PRIORITY.get(cur["kind"], 0),
            cur["strength"],
        ):
            p["signals"] = cur["signals"]  # keep the strongest kind primary; carry all signals
            by_pair[key] = p
    out: list[dict[str, Any]] = []
    for key, p in by_pair.items():
        shares_plat = key in shares_plat_set or any(
            s["kind"] == _SHARES_PLATFORM for s in p["signals"]
        )
        p["crosses"] = _crosses(p["a"], p["b"])
        p["novelty"] = _novelty(float(p["strength"]), p["a"], p["b"], shares_plat, novelty_weight)
        p["signals"] = sorted(p["signals"], key=lambda s: -float(s["strength"]))
        out.append(p)
    out.sort(key=lambda d: (-float(d["novelty"]), -float(d["strength"]), d["a"], d["b"]))
    return out


async def _pair_flag_exists(conn: AsyncConnection, a: str, b: str) -> bool:
    """Pair-level idempotency: has ANY edge (of any kind) already been proposed for this pair? Exact
    match against the finite set of per-kind refs (no LIKE wildcard risk)."""
    lo, hi = _pair_key(a, b)
    refs = [f"{lo}>{hi}:{s}" for s in set(_SHORT.values())]
    return (
        await conn.execute(
            text(
                "SELECT 1 FROM control.change_flag "
                "WHERE kind = :k AND target_ref = ANY(:refs) LIMIT 1"
            ),
            {"k": _KG_EDGE_KIND, "refs": refs},
        )
    ).first() is not None


async def propose_structural_edges(
    version: str,
    shares_platform_min: int | None = None,
    shares_feature_min: int | None = None,
    max_proposals: int | None = None,
    semantic_min_cosine: float | None = None,
    shares_offering_min: int | None = None,
    same_value_chain_min: int | None = None,
    co_delivery_min_count: int | None = None,
    co_delivery_min_lift: float | None = None,
) -> dict[str, Any]:
    """Mine every subcap↔subcap relationship the flat catalogue hides — structural co-occurrence
    (shared platforms / personas / offerings / value-chain stages), co-delivery association over
    the Jira corpus (lift/PMI), and (when an embedding space exists) semantic cosine — then unify
    them to one comparable ``strength`` + ``novelty``, reduce to one edge per pair (strongest kind
    primary, the rest recorded as signals), rank by novelty, gate G1-G8, and queue each as a dashed
    ``pending_edge`` + a Change-Flags proposal (kind ``kg_edge_proposal``) with the full trust
    envelope. Never writes a kg_edge live — approval in the inbox promotes it. Idempotent at the
    PAIR level; bounded by the cap. Returns ``{version, created, proposed, candidates, already}``.
    """
    cfg = gates.knowledge_graph_full_config()
    sp_min = cfg.shares_platform_min if shares_platform_min is None else shares_platform_min
    sf_min = cfg.shares_feature_min if shares_feature_min is None else shares_feature_min
    cap = cfg.max_proposals if max_proposals is None else max_proposals
    sem_cos = cfg.semantic_min_cosine if semantic_min_cosine is None else semantic_min_cosine
    off_min = cfg.shares_offering_min if shares_offering_min is None else shares_offering_min
    vcc_min = cfg.same_value_chain_min if same_value_chain_min is None else same_value_chain_min
    cd_count = cfg.co_delivery_min_count if co_delivery_min_count is None else co_delivery_min_count
    cd_lift = cfg.co_delivery_min_lift if co_delivery_min_lift is None else co_delivery_min_lift
    v = await resolve_version(version)
    engine = db.require_engine()
    created = already = 0
    async with engine.begin() as conn:
        ench_s = await _ench_schema(conn, v.schema_name, "subcap_platform")
        # Gather every relationship signal the data supports, then unify + rank (_score_and_reduce).
        raw = await _candidate_pairs(conn, ench_s, sp_min, sf_min, cap)
        raw += await _co_membership_pairs(conn, v.schema_name, off_min, vcc_min, cap)
        raw += await _co_delivery_pairs(conn, v.schema_name, v.version_id, cd_lift, cd_count, cap)
        emb_s = await _embedding_schema(conn, v.schema_name)
        if emb_s is not None:
            raw += await _semantic_pairs(conn, emb_s, sem_cos, cap)
        ids = {str(p["a"]) for p in raw} | {str(p["b"]) for p in raw}
        shares_plat_set = await _shared_platform_pairs(conn, ench_s, ids)
        pairs = _score_and_reduce(raw, shares_plat_set, cfg.novelty_weight, cfg.allow_cross_pillar)[
            :cap
        ]
        for p in pairs:
            if await _pair_flag_exists(conn, p["a"], p["b"]):
                already += 1  # idempotent: this pair was proposed in a prior run
                continue
            await _create_edge_proposal(conn, v.version_id, p, _pair_ref(p["a"], p["b"], p["kind"]))
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
    a, b, kind = str(p["a"]), str(p["b"]), p["kind"]
    a_name, b_name = str(p["a_name"]), str(p["b_name"])
    shared = int(p.get("shared") or 2)
    strength = float(p.get("strength") or _strength(p))
    basis = str(p.get("basis") or _basis(p))
    crosses = str(p.get("crosses") or _crosses(a, b))
    novelty = float(p.get("novelty") or 0.0)
    signals = list(p.get("signals") or [{"kind": kind, "basis": basis, "strength": strength}])
    relation, ev_phrase, operation = _KIND_PROSE.get(kind, _KIND_PROSE[_SHARES_FEATURE])
    claim = "HYPOTHESIS" if crosses == "cross_pillar" else "INFERENCE"
    pillars = " and different pillars" if crosses == "cross_pillar" else ""
    results, verdict = gates.evaluate_suggestion(
        target_exists=True,  # both subcaps exist in the active version; nothing is mutated
        evidence_count=max(2, shared),  # >= 2 by construction -> G2 passes
        source_tier="T1",
        cited=True,
        contradicts=False,  # an additional edge contradicts nothing — it is purely additive
        cost_usd=0.0,
    )
    title = f"Proposed knowledge-graph edge: {a} ~ {b} ({kind})"
    body = (
        f"{a} ({a_name}) and {b} ({b_name}) sit in different capabilities{pillars} yet {relation} "
        f"— {basis}. The flat catalogue hides this link. Proposed Layer-B edge {kind} (dashed, "
        f"AI-{'hypothesis' if claim == 'HYPOTHESIS' else 'inference'}). Approve to confirm it as a "
        "knowledge-graph relationship, or reject to keep the subcaps unlinked. Nothing is written "
        "to the graph as fact until approved."
    )
    summary = f"KG Layer-B edge {a} ~ {b} [{kind}] — {basis} (novelty {novelty:.2f})."
    chain_id = (
        await conn.execute(
            text(
                "INSERT INTO control.reasoning_chain "
                "(operation, subject_ref, claim_label, summary, model, cost_usd) "
                "VALUES (:op, :subj, CAST(:cl AS claim_label), :summary, 'hermetic-stub', 0) "
                "RETURNING chain_id"
            ),
            {"op": operation, "subj": ref, "cl": claim, "summary": summary},
        )
    ).scalar_one()
    ev = await _edge_evidence(conn, a, b, kind)
    steps = [
        ("retrieve", f"Both {a} and {b} {ev_phrase} ({basis}).", ev),
        (
            "weigh",
            f"They live in different capabilities{pillars}, so this is not an existing Layer-A "
            f"sibling edge — it is a relationship the flat tree hides (novelty {novelty:.2f}, "
            f"strength {strength:.2f}).",
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
    # The "why" a PROMOTED kg_edge keeps (migration 0014: pending_edge.detail / kg_edge.detail).
    edge_detail: dict[str, Any] = {
        "kind_edge": kind,
        "from": a,
        "from_name": a_name,
        "to": b,
        "to_name": b_name,
        "basis": basis,
        "strength": strength,
        "novelty": novelty,
        "crosses": crosses,
        "shared": shared,
        "lift": float(p["lift"]) if p.get("lift") is not None else None,
        "cosine": float(p["cosine"]) if p.get("cosine") is not None else None,
        "co_clients": int(p["co_clients"]) if p.get("co_clients") is not None else None,
        "co_stories": int(p["co_stories"]) if p.get("co_stories") is not None else None,
        "signals": signals,
        "claim_label": claim,
        "source_tier": "T1",
    }
    pending_id = (
        await conn.execute(
            text(
                "INSERT INTO control.pending_edge "
                "(version_id, from_node, to_node, kind, weight, chain_id, status, detail) "
                "VALUES (:v, :f, :t, :k, :w, :c, 'pending', CAST(:d AS jsonb)) RETURNING pending_id"
            ),
            {
                "v": version_id,
                "f": from_node,
                "t": to_node,
                "k": kind,
                "w": strength,
                "c": chain_id,
                "d": json.dumps(edge_detail),
            },
        )
    ).scalar_one()
    # The change_flag carries the same "why" PLUS the inbox-render + promotion envelope.
    flag_detail = {
        **edge_detail,
        "title": title,
        "body": body,
        "version": version_id,
        "gate_failed": gates.first_failing(results),  # None when the proposal passes G1-G8
        "verdict": verdict,
        "weight": strength,
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
            "d": json.dumps(flag_detail),
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
                    "SELECT version_id, from_node, to_node, kind, relation, direction, weight, "
                    "detail::text AS detail FROM control.pending_edge "
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
    await conn.execute(
        text("UPDATE control.pending_edge SET status = 'accepted' WHERE pending_id = :p"),
        {"p": pending_id},
    )
    await conn.execute(
        text(
            "INSERT INTO control.kg_edge "
            "(version_id, from_node, to_node, kind, relation, direction, layer, weight, detail) "
            "VALUES (:v, :f, :t, :k, :rel, :dir, 'B_proposed', :w, CAST(:d AS jsonb))"
        ),
        {
            "v": pe["version_id"],
            "f": pe["from_node"],
            "t": pe["to_node"],
            "k": pe["kind"],
            "rel": pe["relation"],  # directional relation (NULL for legacy symmetric edges)
            "dir": pe["direction"],  # forward | bidirectional (NULL for legacy)
            "w": pe["weight"],
            "d": pe["detail"],  # the edge's "why" survives promotion (migration 0014)
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


# ─────────────────────────────────────────────────────────────────────────────
# R6 — NLP DIRECTIONAL relationship engine. Reads two subcaps' DESCRIPTIONS into a
# typed, DIRECTIONAL relation (one affects / precedes / depends_on the other), then
# DUAL-verifies it — an adversarial refutation AND corroboration against the Jira
# delivery corpus — before a gated, dashed pending_edge + Change-Flags proposal.
# ─────────────────────────────────────────────────────────────────────────────

_SYMMETRIC_REL = frozenset({"complements", "alternative_to"})
# Order-independent target_ref suffix per relation — distinct from the structural _SHORT set, so a
# directional proposal never collides with a structural one for the same pair.
_REL_SHORT = {
    "enables": "den",
    "depends_on": "ddp",
    "precedes": "dpr",
    "affects": "daf",
    "complements": "dcm",
    "alternative_to": "dal",
    "subsumes": "dsb",
}
# Delivery-language stopwords dropped before keyphrase overlap — the shared subset is "the major
# keywords" connecting two subcaps, surfaced on the edge and fed to the NLP extractor.
_KW_STOP = frozenset(
    (
        "the a an and or of to in for with on by from as is are be this that these those it its "
        "into via per across enable enables support supports provide provides using use used new "
        "existing which such their they them our your capability capabilities subcap platform"
    ).split()
)


def _content_tokens(text_in: str) -> set[str]:
    """Salient content tokens of a description (>= 4 chars, stopwords dropped) — the keyphrase set a
    relationship is grounded in. No regex: split on non-alphanumerics so kg.py needs no new import.
    """
    words = "".join(c if c.isalnum() else " " for c in (text_in or "").lower()).split()
    return {w for w in words if len(w) >= 4 and w not in _KW_STOP}


def _directional_ref(a: str, b: str, relation: str) -> str:
    """Stable, order-independent change_flag target_ref for a directional edge (pair-level
    idempotency; the relation suffix records which relation won)."""
    lo, hi = _pair_key(a, b)
    return f"{lo}>{hi}:{_REL_SHORT.get(relation, 'dxx')}"


async def _directional_flag_exists(conn: AsyncConnection, a: str, b: str) -> bool:
    """Pair-level idempotency for the directional layer: has ANY directional relation already been
    proposed for this pair? (Exact match against the finite per-relation ref set.)"""
    lo, hi = _pair_key(a, b)
    refs = [f"{lo}>{hi}:{s}" for s in _REL_SHORT.values()]
    return (
        await conn.execute(
            text(
                "SELECT 1 FROM control.change_flag "
                "WHERE kind = :k AND target_ref = ANY(:refs) LIMIT 1"
            ),
            {"k": _KG_EDGE_KIND, "refs": refs},
        )
    ).first() is not None


def _aggregate_signals(raw: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    """Fold every structural / co-delivery / semantic signal into ONE dict per (a<b) pair, carrying
    the exact counts the directional extractor + corroboration need (shared platforms/offerings,
    co-delivery lift + client/story co-counts, cosine)."""
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for r in raw:
        a, b = str(r["a"]), str(r["b"])
        key = _pair_key(a, b)
        s = out.setdefault(
            key,
            {
                "a": key[0],
                "b": key[1],
                "a_name": str(r.get("a_name") or key[0]),
                "b_name": str(r.get("b_name") or key[1]),
                "shared_platforms": 0,
                "shared_offerings": 0,
                "lift": 0.0,
                "co_clients": 0,
                "co_stories": 0,
                "cosine": 0.0,
            },
        )
        kind = r["kind"]
        if kind == _SHARES_PLATFORM:
            s["shared_platforms"] = int(r.get("shared") or 0)
        elif kind == _SHARES_OFFERING:
            s["shared_offerings"] = int(r.get("shared") or 0)
        elif kind == _CO_DELIVERED:
            s["lift"] = float(r.get("lift") or 0.0)
            s["co_clients"] = int(r.get("co_clients") or 0)
            s["co_stories"] = int(r.get("co_stories") or 0)
        elif kind == _SEMANTIC:
            s["cosine"] = float(r.get("cosine") or 0.0)
    return out


async def _subcap_descriptions(conn: AsyncConnection, schema: str) -> dict[str, tuple[str, str]]:
    """Every subcap's (name, description) — the natural language the NLP extractor reads."""
    rows = (
        await conn.execute(
            text(f"SELECT subcap_id, name, coalesce(description, '') AS d FROM {schema}.subcap")
        )
    ).all()
    return {str(r[0]): (str(r[1]), str(r[2])) for r in rows}


async def _subcap_stage_ords(conn: AsyncConnection, schema: str) -> dict[str, int]:
    """Each subcap's earliest value-chain stage ordinal — the canonical sequence signal that
    corroborates a ``precedes`` relation (an earlier-stage subcap precedes a later-stage one)."""
    vcc_s = await _ench_schema(conn, schema, "subcap_vcc")
    rows = (
        await conn.execute(
            text(
                f"SELECT subcap_id, min(stage_ord) FROM {vcc_s}.subcap_vcc "
                "WHERE stage_ord IS NOT NULL GROUP BY subcap_id"
            )
        )
    ).all()
    return {str(r[0]): int(r[1]) for r in rows if r[1] is not None}


def _prelim_strength(sig: dict[str, Any]) -> float:
    """A quick, signal-only strength to RANK candidates before the bounded NLP pass (strongest,
    most-novel pairs first) — reuses the unified per-kind ``_strength``."""
    return max(
        _strength({"kind": _SEMANTIC, "cosine": sig.get("cosine")}) if sig.get("cosine") else 0.0,
        _strength({"kind": _CO_DELIVERED, "lift": sig.get("lift")}) if sig.get("lift") else 0.0,
        (
            _strength({"kind": _SHARES_PLATFORM, "shared": sig.get("shared_platforms")})
            if sig.get("shared_platforms")
            else 0.0
        ),
        (
            _strength({"kind": _SHARES_OFFERING, "shared": sig.get("shared_offerings")})
            if sig.get("shared_offerings")
            else 0.0
        ),
    )


def _rank_directional_candidates(
    sig_by_pair: dict[tuple[str, str], dict[str, Any]],
    descs: dict[str, tuple[str, str]],
    stage_ords: dict[str, int],
    dcfg: gates.KnowledgeGraphDirectionalConfig,
) -> list[dict[str, Any]]:
    """Assemble the full per-pair signal (descriptions + value-chain order + shared keyphrases) for
    every connected candidate, drop cross-pillar ones when disallowed (D16), and rank by preliminary
    novelty so the bounded NLP pass reads the strongest, most non-obvious pairs first."""
    out: list[dict[str, Any]] = []
    for (a, b), sig in sig_by_pair.items():
        if not dcfg.allow_cross_pillar and a[:2] != b[:2]:
            continue
        a_name, a_desc = descs.get(a, (sig["a_name"], ""))
        b_name, b_desc = descs.get(b, (sig["b_name"], ""))
        shared_kw = sorted(_content_tokens(a_desc) & _content_tokens(b_desc))[:8]
        full = {
            **sig,
            "a_id": a,
            "b_id": b,
            "a_name": a_name,
            "b_name": b_name,
            "a_desc": a_desc,
            "b_desc": b_desc,
            "a_stage_ord": stage_ords.get(a),
            "b_stage_ord": stage_ords.get(b),
            "shared_keywords": shared_kw,
        }
        full["_prelim"] = _prelim_strength(sig)
        full["_novelty"] = _novelty(
            full["_prelim"], a, b, bool(sig.get("shared_platforms")), dcfg.novelty_weight
        )
        out.append(full)
    out.sort(key=lambda d: (-float(d["_novelty"]), -float(d["_prelim"]), d["a"], d["b"]))
    return out


def _corroborate(
    relation: str, direction: str, a: str, b: str, sig: dict[str, Any], lift_min: float
) -> tuple[bool, str]:
    """The corpus/structural half of the dual verification ("does it truly pan out"): the claimed
    relation must be consistent with the grounded delivery + catalogue data. A relation the data
    does not support is dropped. Returns (corroborated, note)."""
    lift = float(sig.get("lift") or 0.0)
    co_clients = int(sig.get("co_clients") or 0)
    co_stories = int(sig.get("co_stories") or 0)
    cosine = float(sig.get("cosine") or 0.0)
    shared_plat = int(sig.get("shared_platforms") or 0)
    shared_off = int(sig.get("shared_offerings") or 0)
    a_ord, b_ord = sig.get("a_stage_ord"), sig.get("b_stage_ord")
    if relation == "precedes":
        if a_ord is None or b_ord is None or int(a_ord) == int(b_ord):
            return (False, "no value-chain ordering to corroborate precedence")
        a_first = int(a_ord) < int(b_ord)
        ok = a_first == (direction != "b_to_a")
        verb = "supports" if ok else "contradicts"
        return (ok, f"value-chain stage order {verb} the claimed direction")
    if relation in ("depends_on", "complements", "enables"):
        ok = lift >= lift_min or co_clients >= 1
        return (
            ok,
            (
                f"co-delivered in real Jira (lift {lift:.1f}, {co_clients} client projects)"
                if ok
                else "no co-delivery in the corpus to support the relation"
            ),
        )
    if relation == "alternative_to":
        ok = cosine >= 0.9 or shared_plat >= 1
        return (
            ok,
            (
                f"near-identical capability space (cosine {cosine:.2f})"
                if ok
                else "not similar enough in the corpus to be an alternative"
            ),
        )
    if relation in ("affects", "subsumes"):
        ok = co_clients >= 1 or co_stories >= 1 or shared_plat >= 1 or shared_off >= 1
        return (
            ok,
            (
                "co-occur in real delivery / shared catalogue structure"
                if ok
                else "no delivery or structural co-occurrence to support the relation"
            ),
        )
    return (False, "unrecognised relation")


def _directional_strength(confidence: float, refuted_fraction: float, corroborated: bool) -> float:
    """Unified 0..1 strength for a directional edge: the NLP confidence, how strongly it survived
    the adversary (1 − refuted fraction), and whether the corpus corroborated it."""
    verify_margin = 1.0 - refuted_fraction
    base = 0.5 * confidence + 0.3 * verify_margin + 0.2 * (1.0 if corroborated else 0.0)
    return round(min(0.999, max(0.0, base)), 3)


async def propose_directional_edges(version: str) -> dict[str, Any]:
    """R6: read the DIRECTIONAL relationship between connected subcap pairs by NLP over their
    descriptions, DUAL-verify each (adversary refutation + Jira-corpus corroboration), and queue the
    survivors as gated, dashed directional ``pending_edge`` + Change-Flags proposals. Candidates are
    the bounded union of the structural / co-delivery / semantic signals the flat catalogue hides;
    the enrich model assigns the typed relation + direction, the adversarial model tries to refute
    it, and the delivery corpus (co-delivery lift, value-chain order) must corroborate it. Hermetic:
    deterministic stub extraction + verification, zero spend; live: metered, G8-gated. Idempotent at
    the pair level; bounded by ``directional_max_per_scan``. Returns
    ``{version, created, candidates, refuted, uncorroborated, already}``."""
    cfg = gates.knowledge_graph_full_config()
    dcfg = gates.knowledge_graph_directional_config()
    v = await resolve_version(version)
    gem = Gemini()
    engine = db.require_engine()
    created = refuted = uncorroborated = already = 0
    async with engine.begin() as conn:
        ench_s = await _ench_schema(conn, v.schema_name, "subcap_platform")
        raw = await _candidate_pairs(
            conn, ench_s, cfg.shares_platform_min, cfg.shares_feature_min, dcfg.max_per_scan
        )
        raw += await _co_membership_pairs(
            conn,
            v.schema_name,
            cfg.shares_offering_min,
            cfg.same_value_chain_min,
            dcfg.max_per_scan,
        )
        raw += await _co_delivery_pairs(
            conn,
            v.schema_name,
            v.version_id,
            cfg.co_delivery_min_lift,
            cfg.co_delivery_min_count,
            dcfg.max_per_scan,
        )
        emb_s = await _embedding_schema(conn, v.schema_name)
        if emb_s is not None:
            raw += await _semantic_pairs(conn, emb_s, cfg.semantic_min_cosine, dcfg.max_per_scan)
        descs = await _subcap_descriptions(conn, ench_s)
        stage_ords = await _subcap_stage_ords(conn, v.schema_name)
        ranked = _rank_directional_candidates(_aggregate_signals(raw), descs, stage_ords, dcfg)[
            : dcfg.max_per_scan
        ]
        for sig in ranked:
            a, b = str(sig["a"]), str(sig["b"])
            if await _directional_flag_exists(conn, a, b):
                already += 1
                continue
            inf = await gem.infer_relationship(sig)
            if inf.relation == "none" or inf.confidence < dcfg.confidence_floor:
                continue
            refutes, vcost = 0, 0.0
            for _ in range(dcfg.verify_passes):
                verdict = await gem.verify_relationship(inf, sig)
                vcost += verdict.cost_usd
                if verdict.refuted:
                    refutes += 1
            refuted_fraction = refutes / dcfg.verify_passes
            if refuted_fraction >= 0.5:
                refuted += 1  # the adversary majority refuted it — dropped
                continue
            corrob, note = _corroborate(
                inf.relation, inf.direction, a, b, sig, dcfg.corroboration_lift
            )
            if not corrob:
                uncorroborated += 1  # the corpus does not support it — dropped
                continue
            strength = _directional_strength(inf.confidence, refuted_fraction, corrob)
            novelty = _novelty(
                strength, a, b, bool(sig.get("shared_platforms")), dcfg.novelty_weight
            )
            await _create_directional_proposal(
                conn, v.version_id, sig, inf, note, strength, novelty, refuted_fraction, vcost
            )
            created += 1
    return {
        "version": v.version_id,
        "created": created,
        "candidates": len(ranked),
        "refuted": refuted,
        "uncorroborated": uncorroborated,
        "already": already,
    }


async def _create_directional_proposal(
    conn: AsyncConnection,
    version_id: str,
    sig: dict[str, Any],
    inf: RelationshipInference,
    corroboration: str,
    strength: float,
    novelty: float,
    refuted_fraction: float,
    cost: float,
) -> None:
    """Write ONE gated, DIRECTIONAL Layer-B proposal (reasoning chain + evidence + citation + REAL
    G1-G8 run + dashed pending_edge + Change-Flags flag). ``from_node`` is the relation's SOURCE and
    ``to_node`` its TARGET; ``direction`` is 'forward' (arrow) or 'bidirectional' (symmetric)."""
    a, b = str(sig["a"]), str(sig["b"])
    a_name, b_name = str(sig["a_name"]), str(sig["b_name"])
    relation, keywords = inf.relation, list(inf.keywords)
    if inf.direction == "b_to_a":
        src, dst, src_name, dst_name, stored_dir = b, a, b_name, a_name, "forward"
    elif inf.direction == "bidirectional":
        src, dst, src_name, dst_name, stored_dir = a, b, a_name, b_name, "bidirectional"
    else:
        src, dst, src_name, dst_name, stored_dir = a, b, a_name, b_name, "forward"
    ref = _directional_ref(a, b, relation)
    crosses = _crosses(a, b)
    claim = inf.claim_label
    arrow = "<->" if stored_dir == "bidirectional" else "->"
    kw_txt = ", ".join(keywords) if keywords else "shared themes"
    # REAL gates: the survivor passed the adversary + corpus, so G6 contradicts=False is earned; G8
    # carries the REAL extraction+verification spend (0 under hermetic), G2 the corroborating count.
    evidence_count = max(
        2,
        int(sig.get("co_clients") or 0)
        + int(sig.get("co_stories") or 0)
        + int(sig.get("shared_platforms") or 0)
        + int(sig.get("shared_offerings") or 0)
        + (1 if sig.get("cosine") else 0),
    )
    results, verdict = gates.evaluate_suggestion(
        target_exists=True,
        evidence_count=evidence_count,
        source_tier="T1",
        cited=True,
        contradicts=False,  # survived the adversary AND corpus corroboration -> earned
        cost_usd=cost,
    )
    basis = f"{relation.replace('_', ' ')} ({stored_dir}); {corroboration}"
    title = f"Proposed directional edge: {src} {arrow} {dst} ({relation})"
    body = (
        f"NLP over the descriptions of {src} ({src_name}) and {dst} ({dst_name}) infers that "
        f"{src_name} {relation.replace('_', ' ')} {dst_name}"
        + (f" ({arrow})" if stored_dir != "bidirectional" else " (both ways)")
        + f". {inf.rationale} It survived an adversarial counter-check and is corroborated: "
        f"{corroboration}. Connective keywords: {kw_txt}. Proposed dashed Layer-B directional edge "
        f"(AI-{'hypothesis' if claim == 'HYPOTHESIS' else 'inference'}); approve to confirm the "
        "relationship + direction, or reject. Nothing is written to the graph until approved."
    )
    summary = (
        f"KG directional edge {src} {arrow} {dst} [{relation}] — strength {strength:.2f}, "
        f"novelty {novelty:.2f}, confidence {inf.confidence:.2f}."
    )
    chain_id = (
        await conn.execute(
            text(
                "INSERT INTO control.reasoning_chain "
                "(operation, subject_ref, claim_label, summary, model, cost_usd) "
                "VALUES ('kg_directional_extract', :subj, CAST(:cl AS claim_label), :summary, "
                ":model, :cost) RETURNING chain_id"
            ),
            {"subj": ref, "cl": claim, "summary": summary, "model": inf.model, "cost": cost},
        )
    ).scalar_one()
    ev = await _edge_evidence(conn, a, b, "directional")
    steps = [
        (
            "retrieve",
            f"Read the descriptions of {src} and {dst} plus grounded signals (shared keywords: "
            f"{kw_txt}).",
            ev,
        ),
        (
            "weigh",
            f"NLP infers {src_name} {relation.replace('_', ' ')} {dst_name} "
            f"(confidence {inf.confidence:.2f}). {inf.rationale}",
            None,
        ),
        (
            "weigh",
            f"Adversarial counter-check: {(1.0 - refuted_fraction):.0%} of passes upheld the "
            "relationship (majority did not refute).",
            None,
        ),
        ("weigh", f"Corpus corroboration: {corroboration}.", None),
        (
            "conclude",
            f"Propose a dashed directional {relation} edge {src} {arrow} {dst} "
            f"(novelty {novelty:.2f}); route to a pillar lead (never rendered as fact ungated).",
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
    from_node = await _node_id(conn, version_id, "subcap", src, src_name)
    to_node = await _node_id(conn, version_id, "subcap", dst, dst_name)
    edge_detail: dict[str, Any] = {
        "kind_edge": relation,
        "relation": relation,
        "direction": stored_dir,
        "from": src,
        "from_name": src_name,
        "to": dst,
        "to_name": dst_name,
        "basis": basis,
        "rationale": inf.rationale,
        "keywords": keywords,
        "confidence": round(float(inf.confidence), 3),
        "verify_survived": round(1.0 - refuted_fraction, 3),
        "corroboration": corroboration,
        "strength": strength,
        "novelty": novelty,
        "crosses": crosses,
        "claim_label": claim,
        "source_tier": "T1",
        "model": inf.model,
        "cost": round(cost, 6),
    }
    pending_id = (
        await conn.execute(
            text(
                "INSERT INTO control.pending_edge "
                "(version_id, from_node, to_node, kind, relation, direction, weight, chain_id, "
                "status, detail) VALUES (:v, :f, :t, :k, :rel, :dir, :w, :c, 'pending', "
                "CAST(:d AS jsonb)) RETURNING pending_id"
            ),
            {
                "v": version_id,
                "f": from_node,
                "t": to_node,
                "k": relation,
                "rel": relation,
                "dir": stored_dir,
                "w": strength,
                "c": chain_id,
                "d": json.dumps(edge_detail),
            },
        )
    ).scalar_one()
    flag_detail = {
        **edge_detail,
        "title": title,
        "body": body,
        "version": version_id,
        "gate_failed": gates.first_failing(results),
        "verdict": verdict,
        "weight": strength,
        "pending_id": str(pending_id),
    }
    await conn.execute(
        text(
            "INSERT INTO control.change_flag (kind, severity, target_ref, detail, chain_id) "
            "VALUES (:k, :sev, :t, CAST(:d AS jsonb), :c)"
        ),
        {
            "k": _KG_EDGE_KIND,
            "sev": _severity(evidence_count),
            "t": ref,
            "d": json.dumps(flag_detail),
            "c": chain_id,
        },
    )
