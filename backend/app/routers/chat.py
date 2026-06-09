"""AI chat (H1) + reasoning-chain viewer (H2).

POST /api/chat returns a catalogue-grounded, citation-backed answer (or a refusal when nothing is
retrieved — G5). GET /api/reasoning/{chain_id} is the universal audit window: the ordered steps,
the evidence rows, and the gate checks the system ran before showing the answer.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import text

from app import db
from app.deps import get_current_user
from app.services import chat as chat_service

router = APIRouter(prefix="/api", tags=["intelligence"])


class ChatRequest(BaseModel):
    question: str
    version: str = "v7"


class ChatCitation(BaseModel):
    subcap_id: str
    name: str


class ChatResponse(BaseModel):
    grounded: bool
    answer: str
    citations: list[ChatCitation]
    claim_label: str | None = None
    source_tier: str | None = None
    source: str | None = None
    ers: int = 0
    chain_id: str | None = None


@router.post("/chat")
async def chat(
    payload: ChatRequest, _user: dict[str, Any] = Depends(get_current_user)
) -> ChatResponse:
    q = payload.question.strip()
    if not q:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="empty question")
    r = await chat_service.answer(payload.version, q)
    return ChatResponse(
        grounded=r.grounded,
        answer=r.answer,
        citations=[ChatCitation(subcap_id=c.subcap_id, name=c.name) for c in r.citations],
        claim_label=r.claim_label,
        source_tier=r.source_tier,
        source=r.source,
        ers=r.ers,
        chain_id=r.chain_id,
    )


class EvidenceRow(BaseModel):
    claim_label: str
    tier: str
    text: str


class ReasoningStep(BaseModel):
    kind: str
    text: str
    evidence: list[EvidenceRow] = []


class GateCheck(BaseModel):
    name: str
    state: str
    detail: str


class ReasoningChain(BaseModel):
    chain_id: str
    title: str
    claim_label: str | None = None
    verdict: str | None = None
    cost: str
    model: str | None = None
    created_at: str | None = None
    steps: list[ReasoningStep]
    checks: list[GateCheck]


@router.get("/reasoning/{chain_id}")
async def reasoning(
    chain_id: str, _user: dict[str, Any] = Depends(get_current_user)
) -> ReasoningChain:
    engine = db.get_engine()
    if engine is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="database unavailable")
    async with engine.connect() as conn:
        ch = (
            (
                await conn.execute(
                    text(
                        "SELECT subject_ref, claim_label::text AS claim_label, summary, model, "
                        "cost_usd::float AS cost_usd, created_at::text AS created_at "
                        "FROM control.reasoning_chain WHERE chain_id = :id"
                    ),
                    {"id": chain_id},
                )
            )
            .mappings()
            .first()
        )
        if ch is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="reasoning chain unavailable")
        step_rows = (
            (
                await conn.execute(
                    text(
                        "SELECT rs.kind, rs.text, e.title AS ev_title, "
                        "e.source_tier::text AS ev_tier "
                        "FROM control.reasoning_step rs "
                        "LEFT JOIN control.evidence_item e ON e.evidence_id = rs.evidence_id "
                        "WHERE rs.chain_id = :id ORDER BY rs.ordinal"
                    ),
                    {"id": chain_id},
                )
            )
            .mappings()
            .all()
        )
        gate = (
            (
                await conn.execute(
                    text(
                        "SELECT gate_results, verdict::text AS verdict "
                        "FROM control.validation_gate_run WHERE chain_id = :id "
                        "ORDER BY created_at DESC LIMIT 1"
                    ),
                    {"id": chain_id},
                )
            )
            .mappings()
            .first()
        )

    steps: list[ReasoningStep] = []
    for r in step_rows:
        ev: list[EvidenceRow] = []
        if r["ev_title"]:
            ev = [EvidenceRow(claim_label="FACT", tier=r["ev_tier"] or "T1", text=r["ev_title"])]
        steps.append(ReasoningStep(kind=r["kind"], text=r["text"], evidence=ev))

    checks: list[GateCheck] = []
    if gate is not None:
        for name, res in (gate["gate_results"] or {}).items():
            passed = res.get("verdict") == "pass"
            checks.append(
                GateCheck(
                    name=name,
                    state="Passed" if passed else "Needs review",
                    detail=res.get("detail", ""),
                )
            )

    summary = ch["summary"] or ""
    return ReasoningChain(
        chain_id=chain_id,
        title=ch["subject_ref"] or summary[:80],
        claim_label=ch["claim_label"],
        verdict=gate["verdict"] if gate is not None else None,
        cost=f"${ch['cost_usd'] or 0:.3f}",
        model=ch["model"],
        created_at=ch["created_at"],
        steps=steps,
        checks=checks,
    )
