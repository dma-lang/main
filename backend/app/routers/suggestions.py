"""AI suggestions (D3) — the gated-mutation queue.

GET lists the queue with the trust envelope + gate verdict. apply RE-GATES server-side then mutates
cat_<v> + appends an immutable audit_log row in one transaction; reject requires a reason. propose
(admin) generates grounded suggestions from the delivery corpus.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from app.deps import get_current_user, require_admin
from app.services import suggestions as svc

router = APIRouter(prefix="/api", tags=["suggestions"])


class SuggestionOut(BaseModel):
    suggestion_id: str
    target_subcap: str | None
    subcap_name: str | None
    pillar: str | None
    kind: str
    title: str
    rationale: str
    status: str
    verdict: str | None
    breaking: bool
    claim_label: str | None
    source_tier: str | None
    ers: int
    chain_id: str | None
    cost: str
    created_at: str | None


class RejectBody(BaseModel):
    reason: str = ""


class ApplyOut(BaseModel):
    applied: bool
    status: str
    gate_failed: str | None = None
    before: str | None = None
    after: str | None = None


@router.get("/suggestions")
async def list_suggestions(
    status_filter: str = Query("pending", alias="status"),
    _user: dict[str, Any] = Depends(get_current_user),
) -> list[SuggestionOut]:
    rows = await svc.list_suggestions(status_filter)
    return [SuggestionOut(**vars(r)) for r in rows]


@router.post("/admin/suggestions/propose/{version}")
async def propose(version: str, _admin: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
    return await svc.propose(version)


@router.post("/suggestions/{suggestion_id}/apply")
async def apply(suggestion_id: str, user: dict[str, Any] = Depends(get_current_user)) -> ApplyOut:
    result = await svc.apply(suggestion_id, str(user["uid"]))
    if result.status == "not_found":
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="suggestion not found")
    return ApplyOut(**vars(result))


@router.post("/suggestions/{suggestion_id}/reject")
async def reject(
    suggestion_id: str, body: RejectBody, user: dict[str, Any] = Depends(get_current_user)
) -> ApplyOut:
    if not body.reason.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="a rejection reason is required")
    result = await svc.reject(suggestion_id, body.reason, str(user["uid"]))
    if result.status == "not_found":
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="suggestion not found")
    return ApplyOut(**vars(result))
