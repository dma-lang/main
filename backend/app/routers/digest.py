"""Quarterly digest API (E1) + signed exports (F12).

GET /api/digest serves the synthesis read model (exec summary + cross-pillar theme + pillar
priorities with adversarial lines + the trust envelope + quarterly cadence + the latest export's
verification state). Admin regenerates per quarter; export signs the canonical JSON into the
append-only manifest; verify recomputes from CURRENT stored state — tamper-evident.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from app.deps import get_current_user, require_admin
from app.services import digest as digest_svc

router = APIRouter(prefix="/api", tags=["digest"])


class PriorityOut(BaseModel):
    pillar: str
    pillar_name: str
    title: str
    body: str
    adversary_verdict: str


class DigestOut(BaseModel):
    quarter: str
    generated: bool
    summary: str
    theme: str
    claim_label: str
    chain: str | None
    created_at: str | None
    priorities: list[PriorityOut]
    quarters: list[str]
    cadence: dict[str, Any]
    export: dict[str, Any] | None


class GenerateIn(BaseModel):
    quarter: str | None = None


class ExportIn(BaseModel):
    quarter: str | None = None


@router.get("/digest")
async def get_digest(
    quarter: str | None = Query(None),
    _user: dict[str, Any] = Depends(get_current_user),
) -> DigestOut:
    d = await digest_svc.read(quarter)
    return DigestOut(
        **{
            **vars(d),
            "priorities": [PriorityOut(**vars(p)) for p in d.priorities],
        }
    )


@router.post("/admin/digest/generate")
async def generate_digest(
    body: GenerateIn, admin: dict[str, Any] = Depends(require_admin)
) -> dict[str, Any]:
    """Run the quarterly synthesis inline (hermetic); Cloud Scheduler triggers it in the cloud
    per config/schedules.yaml. Idempotent per quarter (regeneration replaces)."""
    return await digest_svc.generate(body.quarter, str(admin["uid"]))


@router.post("/exports/digest")
async def export_digest(
    body: ExportIn, user: dict[str, Any] = Depends(get_current_user)
) -> dict[str, Any]:
    try:
        return await digest_svc.export(body.quarter, str(user["uid"]))
    except RuntimeError as exc:
        if "HMAC_KEY" in str(exc):
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
        raise


@router.get("/exports/{export_id}/verify")
async def verify_export(
    export_id: UUID, _user: dict[str, Any] = Depends(get_current_user)
) -> dict[str, Any]:
    result = await digest_svc.verify(str(export_id))
    if not result.get("found"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="export not found")
    return result
