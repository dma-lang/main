"""Catalogue-grounded chat (H1) — the grounded-only RAG path.

retrieve (F6) -> G5 grounding gate -> grounded answer (one Gemini wrapper) -> persist the reasoning
chain (steps + citations + gate run) so every answer is auditable via GET /api/reasoning/{id}. When
nothing is retrieved the answer is refused (G5): no answer ever comes from model memory.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app import db
from app.intelligence import gates
from app.intelligence.gemini import Gemini
from app.intelligence.retrieval import retrieve
from app.versioning import resolve_version

_SCHEMA_RE = re.compile(r"^cat_[a-z0-9_]+$")

_REFUSAL = (
    "I can only answer from the retrieved catalogue evidence, and nothing in the {v} catalogue "
    "matches that. Try a capability, platform, persona, or delivery topic."
)


@dataclass
class Citation:
    subcap_id: str
    name: str


@dataclass
class ChatResult:
    grounded: bool
    answer: str
    citations: list[Citation] = field(default_factory=list)
    claim_label: str | None = None
    source_tier: str | None = None
    source: str | None = None
    ers: int = 0
    chain_id: str | None = None


async def answer(version: str, question: str) -> ChatResult:
    v = await resolve_version(version)
    schema = v.schema_name
    if not _SCHEMA_RE.match(schema):
        raise ValueError("invalid version schema")
    engine = db.get_engine()
    if engine is None:
        raise RuntimeError("database not initialised")

    async with engine.begin() as conn:
        hits = await retrieve(conn, schema, question, k=5)
        if not hits:
            return ChatResult(grounded=False, answer=_REFUSAL.format(v=v.version_id))
        ga = await Gemini().ground(question, hits)
        ev_ids = [await _evidence_for(conn, h) for h in hits]
        results, verdict = gates.evaluate_chat(len(hits), len(ev_ids))
        chain_id = await _persist(conn, question, ga, hits, ev_ids, results, verdict)

    return ChatResult(
        grounded=True,
        answer=ga.text,
        citations=[Citation(subcap_id=h["subcap_id"], name=h["name"]) for h in hits],
        claim_label=ga.claim_label,
        source_tier="T1",
        source=f"{v.version_id} catalog",
        ers=min(95, 55 + 8 * len(hits)),  # tier(T1) + corroboration from citation count
        chain_id=str(chain_id),
    )


async def _evidence_for(conn: AsyncConnection, hit: dict[str, Any]) -> UUID:
    """Get-or-create the catalogue evidence_item for a subcap (citation target; idempotent)."""
    sid = hit["subcap_id"]
    found = (
        await conn.execute(
            text(
                "SELECT evidence_id FROM control.evidence_item "
                "WHERE kind = 'catalogue' AND body_ref = :b"
            ),
            {"b": sid},
        )
    ).first()
    if found is not None:
        return cast(UUID, found[0])
    created = (
        await conn.execute(
            text(
                "INSERT INTO control.evidence_item (kind, title, source_tier, body_ref) "
                "VALUES ('catalogue', :t, 'T1', :b) RETURNING evidence_id"
            ),
            {"t": hit["name"], "b": sid},
        )
    ).first()
    assert created is not None
    return cast(UUID, created[0])


async def _persist(
    conn: AsyncConnection,
    question: str,
    ga: Any,
    hits: list[dict[str, Any]],
    ev_ids: list[UUID],
    results: dict[str, Any],
    verdict: str,
) -> UUID:
    chain_id: UUID = (
        await conn.execute(
            text(
                "INSERT INTO control.reasoning_chain "
                "(operation, subject_ref, claim_label, summary, model, cost_usd) "
                "VALUES ('chat', :subj, CAST(:claim AS claim_label), :summary, :model, :cost) "
                "RETURNING chain_id"
            ),
            {
                "subj": question[:200],
                "claim": ga.claim_label,
                "summary": ga.text,
                "model": ga.model,
                "cost": ga.cost_usd,
            },
        )
    ).scalar_one()

    steps: list[tuple[int, str, str, UUID | None]] = [
        (
            1,
            "retrieve",
            f"Retrieved {len(hits)} capabilities from the active catalogue by hybrid lexical "
            f"search for '{question[:80]}'.",
            ev_ids[0],
        )
    ]
    ordinal = 2
    for h, ev in zip(hits, ev_ids, strict=True):
        desc = (h.get("description") or "")[:140]
        steps.append((ordinal, "weigh", f"{h['name']} ({h['subcap_id']}) — {desc}", ev))
        ordinal += 1
    steps.append((ordinal, "conclude", ga.text, None))

    for ordn, kind, txt, step_ev in steps:
        await conn.execute(
            text(
                "INSERT INTO control.reasoning_step (chain_id, ordinal, kind, text, evidence_id) "
                "VALUES (:c, :o, :k, :t, :e)"
            ),
            {"c": chain_id, "o": ordn, "k": kind, "t": txt, "e": step_ev},
        )
    for ev in ev_ids:
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
            "VALUES (:c, 'chat', CAST(:r AS jsonb), CAST(:v AS gate_verdict))"
        ),
        {"c": chain_id, "r": json.dumps(results), "v": verdict},
    )
    return chain_id
