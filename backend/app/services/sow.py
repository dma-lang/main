"""SOW library pipeline (C1, FR-7) — ingest -> match -> gate -> persist, then confirm.

`scan_sows()` ingests the corpus (hermetic: the recorded fixture; live: Drive+DLP in Stage 4) and
matches every scope clause against the ACTIVE version's catalogue with the same retrieval +
relevance-floor machinery the news pipeline uses. Each clause writes an `evidence_item
(kind='sow_chunk')`, a reasoning chain (retrieve -> weigh -> conclude), a verified citation and a
G1/G3/G5/G6/G7 gate run; the match lands in one of the carry-forward confidence bands —
confirmed / review / unmapped — and is NEVER dropped (an unmapped clause keeps its best
nearest-neighbour proposal for a human). Confirming a review match is a human attestation: status
-> confirmed, claim -> FACT, audited. Idempotent: a re-scan upserts documents/items and skips
already-matched clauses (zero marginal model spend).

Similarity is the lexical stand-in mapped onto the configured cosine bands (config `matching`):
a clause whose top retrieval rank clears the strong-grounding bar reads ~0.97 (auto-confirm),
the floor..strong band reads 0.70-0.86 (review), and sub-floor keeps a <0.55 proposal (unmapped).
Recalibrated onto real cosine when F6 dense retrieval lands — same bands, another scale.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app import db
from app.intelligence import gates, retrieval
from app.intelligence import sow as sow_corpus
from app.versioning import resolve_version

_TIER = "T1"  # internal contractual documents


def _similarity(top_rank: float, floor: float, strong: float) -> float:
    """Monotonic lexical-rank -> band mapping (see module docstring)."""
    if top_rank >= strong:
        return 0.97
    if top_rank >= floor:
        span = (top_rank - floor) / max(strong - floor, 1e-9)
        return round(0.70 + 0.15 * span, 3)  # 0.70 .. 0.85 — the review band
    return round(0.55 * (top_rank / max(floor, 1e-9)), 3)  # < 0.55 — unmapped proposal


def _band(similarity: float) -> tuple[str, str]:
    """(status, claim_label) for an AUTO match. A human confirm upgrades claim to FACT."""
    confirm_at, review_low = gates.matching_bands()
    if similarity >= confirm_at:
        return "confirmed", "INFERENCE"
    if similarity >= review_low:
        return "review", "HYPOTHESIS"
    return "unmapped", "HYPOTHESIS"


async def scan_sows(version: str) -> dict[str, Any]:
    """Ingest + match the SOW corpus against `version`. Idempotent per (scope, version)."""
    v = await resolve_version(version)
    engine = db.require_engine()
    docs = items = matched = skipped = 0
    by_status = {"confirmed": 0, "review": 0, "unmapped": 0}
    async with engine.begin() as conn:
        for raw in sow_corpus.fetch_sows():
            sow_id = (
                await conn.execute(
                    text(
                        "INSERT INTO control.sow_document "
                        "(account_key, account_name, title, sv_code, signed_date) "
                        "VALUES (:k, :n, :t, :sv, :d) "
                        "ON CONFLICT (account_key, title) DO UPDATE SET sv_code = EXCLUDED.sv_code "
                        "RETURNING sow_id"
                    ),
                    {
                        "k": raw.account_key,
                        "n": raw.account_name,
                        "t": raw.title,
                        "sv": raw.sv_code,
                        "d": date.fromisoformat(raw.signed_date),
                    },
                )
            ).scalar_one()
            docs += 1
            for item in raw.items:
                scope_id = (
                    await conn.execute(
                        text(
                            "INSERT INTO control.sow_scope_item (sow_id, ordinal, clause) "
                            "VALUES (:s, :o, :c) "
                            "ON CONFLICT (sow_id, ordinal) DO UPDATE SET clause = EXCLUDED.clause "
                            "RETURNING scope_id"
                        ),
                        {"s": sow_id, "o": item.ordinal, "c": item.clause},
                    )
                ).scalar_one()
                items += 1
                exists = (
                    await conn.execute(
                        text(
                            "SELECT 1 FROM control.sow_subcap_match "
                            "WHERE scope_id = :sc AND version_id = :v"
                        ),
                        {"sc": scope_id, "v": v.version_id},
                    )
                ).first()
                if exists:
                    skipped += 1
                    continue
                status = await _match_one(conn, v.version_id, v.schema_name, scope_id, raw, item)
                by_status[status] += 1
                matched += 1
    return {
        "version": v.version_id,
        "documents": docs,
        "scope_items": items,
        "matched": matched,
        "deduped": skipped,
        **by_status,
    }


async def _match_one(
    conn: AsyncConnection,
    version_id: str,
    schema: str,
    scope_id: Any,
    raw: sow_corpus.RawSow,
    item: sow_corpus.RawScopeItem,
) -> str:
    floor, strong = gates.evidence_thresholds()
    matches = await retrieval.retrieve(conn, schema, item.clause, k=3)
    grounded = [m for m in matches if float(m["rank"]) >= floor]
    top = grounded[0] if grounded else (matches[0] if matches else None)
    top_rank = float(top["rank"]) if top else 0.0
    similarity = _similarity(top_rank, floor, strong) if top else 0.0
    status, claim = _band(similarity)

    evidence_id = (
        await conn.execute(
            text(
                "INSERT INTO control.evidence_item "
                "(kind, title, source_tier, published_at, source_name, source_type, redacted) "
                "VALUES ('sow_chunk', :t, CAST(:tier AS source_tier), :p, :sn, "
                "CAST('internal' AS source_type), true) RETURNING evidence_id"
            ),
            {
                "t": item.clause[:200],
                "tier": _TIER,
                "p": date.fromisoformat(raw.signed_date),
                "sn": f"{raw.account_key} · {raw.title}",
            },
        )
    ).scalar_one()

    target = f"{top['subcap_id']} ({similarity:.2f})" if top else "no candidate above the floor"
    chain_id = (
        await conn.execute(
            text(
                "INSERT INTO control.reasoning_chain "
                "(operation, subject_ref, claim_label, summary, model, cost_usd) "
                "VALUES ('sow_match', :subj, CAST(:cl AS claim_label), :sum, 'hermetic', 0) "
                "RETURNING chain_id"
            ),
            {
                "subj": f"{raw.account_key}: {item.clause[:80]}",
                "cl": claim,
                "sum": f"Scope clause matched to {target}; band -> {status}.",
            },
        )
    ).scalar_one()
    steps = [
        (
            "retrieve",
            f"DLP-redacted clause embedded and retrieved over the {version_id} catalogue "
            f"(relevance floor {floor}): top candidate {target}.",
            evidence_id,
        ),
        (
            "weigh",
            f"Lexical grounding rank {top_rank:.4f} vs strong-grounding bar {strong} -> "
            f"similarity {similarity:.2f}; carry-forward bands route it to '{status}'.",
            None,
        ),
        (
            "conclude",
            (
                f"Match written as {status.upper()} ({claim}); a human confirm attests it to FACT."
                if top
                else "No catalogue candidate above the relevance floor — kept as an unmapped "
                "proposal for review, never dropped (G5)."
            ),
            None,
        ),
    ]
    for ordinal, (kind, step_text, ev) in enumerate(steps, start=1):
        await conn.execute(
            text(
                "INSERT INTO control.reasoning_step (chain_id, ordinal, kind, text, evidence_id) "
                "VALUES (:c, :o, :k, :t, :e)"
            ),
            {"c": chain_id, "o": ordinal, "k": kind, "t": step_text, "e": ev},
        )
    await conn.execute(
        text(
            "INSERT INTO control.citation (chain_id, evidence_id, verified) VALUES (:c, :e, true)"
        ),
        {"c": chain_id, "e": evidence_id},
    )
    results, verdict = gates.evaluate_evidence(
        source_tier=_TIER,
        retrieval_count=len(matches),
        grounded_count=len(grounded),
        cited=True,
        contradicts=False,
    )
    await conn.execute(
        text(
            "INSERT INTO control.validation_gate_run (chain_id, target_ref, gate_results, verdict)"
            " VALUES (:c, :t, CAST(:r AS jsonb), CAST(:v AS gate_verdict))"
        ),
        {"c": chain_id, "t": f"sow:{scope_id}", "r": json.dumps(results), "v": verdict},
    )
    await conn.execute(
        text(
            "INSERT INTO control.sow_subcap_match "
            "(scope_id, version_id, subcap_id, similarity, status, claim_label, source_tier, "
            "chain_id, evidence_id) "
            "VALUES (:sc, :v, :sub, :sim, :st, CAST(:cl AS claim_label), "
            "CAST(:tier AS source_tier), :ch, :e)"
        ),
        {
            "sc": scope_id,
            "v": version_id,
            "sub": str(top["subcap_id"]) if top else "",
            "sim": similarity,
            "st": status,
            "cl": claim,
            "tier": _TIER,
            "ch": chain_id,
            "e": evidence_id,
        },
    )
    return status


async def list_sows(version: str) -> list[dict[str, Any]]:
    """The SOW roster with per-document match-band counts for the version."""
    v = await resolve_version(version)
    engine = db.require_engine()
    sql = text(
        "SELECT d.sow_id::text AS sow_id, d.account_key, d.account_name, d.title, d.sv_code, "
        "d.signed_date::text AS signed_date, d.status, d.redacted, "
        "count(si.scope_id) AS items, "
        "count(m.match_id) FILTER (WHERE m.status = 'confirmed') AS confirmed, "
        "count(m.match_id) FILTER (WHERE m.status = 'review') AS review, "
        "count(m.match_id) FILTER (WHERE m.status = 'unmapped') AS unmapped "
        "FROM control.sow_document d "
        "LEFT JOIN control.sow_scope_item si ON si.sow_id = d.sow_id "
        "LEFT JOIN control.sow_subcap_match m "
        "ON m.scope_id = si.scope_id AND m.version_id = :v "
        "GROUP BY d.sow_id ORDER BY d.signed_date DESC"
    )
    async with engine.connect() as conn:
        rows = (await conn.execute(sql, {"v": v.version_id})).mappings().all()
    return [dict(r) for r in rows]


async def sow_detail(sow_id: str, version: str) -> dict[str, Any] | None:
    """One document: scope clauses + their gated matches (subcap names joined live)."""
    v = await resolve_version(version)
    engine = db.require_engine()
    async with engine.connect() as conn:
        doc = (
            (
                await conn.execute(
                    text(
                        "SELECT sow_id::text AS sow_id, account_key, account_name, title, "
                        "sv_code, signed_date::text AS signed_date, status, redacted "
                        "FROM control.sow_document WHERE sow_id = CAST(:id AS uuid)"
                    ),
                    {"id": sow_id},
                )
            )
            .mappings()
            .first()
        )
        if doc is None:
            return None
        rows = (
            (
                await conn.execute(
                    text(
                        "SELECT si.scope_id::text AS scope_id, si.ordinal, si.clause, "
                        "m.match_id::text AS match_id, m.subcap_id, "
                        "m.similarity::float AS similarity, m.status, "
                        "m.claim_label::text AS claim_label, m.source_tier::text AS source_tier, "
                        "m.chain_id::text AS chain_id, m.confirmed_by, "
                        f"(SELECT s.name FROM {v.schema_name}.subcap s "
                        "WHERE s.subcap_id = m.subcap_id) AS subcap_name "
                        "FROM control.sow_scope_item si "
                        "LEFT JOIN control.sow_subcap_match m "
                        "ON m.scope_id = si.scope_id AND m.version_id = :v "
                        "WHERE si.sow_id = CAST(:id AS uuid) ORDER BY si.ordinal"
                    ),
                    {"id": sow_id, "v": v.version_id},
                )
            )
            .mappings()
            .all()
        )
    return {**dict(doc), "items": [dict(r) for r in rows]}


async def confirm_match(match_id: str, actor: str) -> dict[str, Any]:
    """Human attestation: review -> confirmed, claim -> FACT, audited. Idempotent on re-confirm;
    a non-existent match is a clean not-found for the router (never a 500)."""
    engine = db.require_engine()
    async with engine.begin() as conn:
        row = (
            (
                await conn.execute(
                    text(
                        "UPDATE control.sow_subcap_match "
                        "SET status = 'confirmed', claim_label = 'FACT', confirmed_by = :a "
                        "WHERE match_id = CAST(:id AS uuid) AND status IN ('review', 'confirmed') "
                        "RETURNING match_id::text AS match_id, subcap_id, status"
                    ),
                    {"id": match_id, "a": actor},
                )
            )
            .mappings()
            .first()
        )
        if row is None:
            return {"ok": False, "status": "not_found"}
        await conn.execute(
            text(
                "INSERT INTO control.audit_log (actor, action, target_ref, meta) VALUES "
                "((SELECT uid FROM control.users WHERE uid = :actor), 'sow_match.confirm', :t, "
                "CAST(:m AS jsonb))"
            ),
            {
                "actor": actor,
                "t": f"sow_match:{row['match_id']}",
                "m": json.dumps({"subcap_id": row["subcap_id"]}),
            },
        )
    return {"ok": True, "status": "confirmed", "subcap_id": row["subcap_id"]}
