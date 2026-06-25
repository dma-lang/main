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


def _severity(shared: int) -> str:
    """Structural suggestions are low-urgency; a stronger overlap is a touch more notable."""
    return "MED" if shared >= 4 else "LOW"


def _weight(kind: str, shared: int) -> float:
    """Deterministic confidence for the dashed edge, capped under numeric(4,3)."""
    base = 0.5 if kind == _SHARES_PLATFORM else 0.4
    return round(min(0.999, base + 0.08 * shared), 3)


def _pair_ref(a: str, b: str, kind: str) -> str:
    """Stable, order-independent change_flag target_ref for one proposed edge (idempotency key)."""
    lo, hi = sorted((a, b))
    short = "sp" if kind == _SHARES_PLATFORM else "sf"
    return f"{lo}>{hi}:{short}"


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


async def propose_structural_edges(
    version: str,
    shares_platform_min: int | None = None,
    shares_feature_min: int | None = None,
    max_proposals: int | None = None,
) -> dict[str, Any]:
    """Compute deterministic structural co-occurrence pairs, gate G1-G8, and queue each as a dashed
    ``pending_edge`` + a Change-Flags proposal (kind ``kg_edge_proposal``) with the full trust
    envelope. Never writes a kg_edge live — approval in the inbox promotes it. Idempotent on the
    pair key. Returns ``{version, created, proposed, candidates, already}``."""
    cfg_sp, cfg_sf, cfg_cap = gates.knowledge_graph_config()
    sp_min = cfg_sp if shares_platform_min is None else shares_platform_min
    sf_min = cfg_sf if shares_feature_min is None else shares_feature_min
    cap = cfg_cap if max_proposals is None else max_proposals
    v = await resolve_version(version)
    engine = db.require_engine()
    created = already = 0
    async with engine.begin() as conn:
        ench_s = await _ench_schema(conn, v.schema_name, "subcap_platform")
        pairs = await _candidate_pairs(conn, ench_s, sp_min, sf_min, cap)
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
    basis = (
        f"{shared} shared L3 platforms" if kind == _SHARES_PLATFORM else f"{shared} shared personas"
    )
    results, verdict = gates.evaluate_suggestion(
        target_exists=True,  # both subcaps exist in the active version; nothing is mutated
        evidence_count=shared,  # the co-occurring rows (>= 2 by the HAVING floor -> G2 passes)
        source_tier="T1",
        cited=True,
        contradicts=False,  # a structural link contradicts nothing — it is purely additive
        cost_usd=0.0,
    )
    title = f"Proposed knowledge-graph edge: {a} ~ {b} ({kind})"
    body = (
        f"{a} ({a_name}) and {b} ({b_name}) sit in different capabilities yet co-occur "
        f"structurally — {basis}. The flat catalogue hides this link. Proposed Layer-B edge "
        f"{kind} (dashed, AI-proposed). Approve to confirm it as a knowledge-graph relationship, "
        "or reject to keep the subcaps unlinked. Nothing is written to the graph as fact until "
        "approved."
    )
    summary = f"Structural KG edge {a} ~ {b} [{kind}] — {basis}."
    chain_id = (
        await conn.execute(
            text(
                "INSERT INTO control.reasoning_chain "
                "(operation, subject_ref, claim_label, summary, model, cost_usd) "
                "VALUES ('kg_structural', :subj, 'INFERENCE', :summary, 'hermetic-stub', 0) "
                "RETURNING chain_id"
            ),
            {"subj": ref, "summary": summary},
        )
    ).scalar_one()
    ev = await _edge_evidence(conn, a, b, kind)
    steps = [
        ("retrieve", f"Both {a} and {b} trace to real catalogue link rows ({basis}).", ev),
        (
            "weigh",
            "They live in different capabilities, so this is not an existing Layer-A sibling edge "
            "— it is a structural relationship the flat tree hides.",
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
    weight = _weight(kind, shared)
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
    await conn.execute(
        text("UPDATE control.pending_edge SET status = 'accepted' WHERE pending_id = :p"),
        {"p": pending_id},
    )
    await conn.execute(
        text(
            "INSERT INTO control.kg_edge (version_id, from_node, to_node, kind, layer, weight) "
            "VALUES (:v, :f, :t, :k, 'B_proposed', :w)"
        ),
        {
            "v": pe["version_id"],
            "f": pe["from_node"],
            "t": pe["to_node"],
            "k": pe["kind"],
            "w": pe["weight"],
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
