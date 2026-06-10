"""SOW library routes (C1, FR-7) — the gated SOW -> subcap evidence surface.

GET /api/sow lists the corpus with per-document match-band counts; GET /api/sow/{id} is the
master-detail read (clauses + gated matches + chain backlinks); POST /api/admin/sow/scan/{version}
runs the ingest+match pipeline (admin, idempotent); POST /api/sow/matches/{id}/confirm is the
human attestation (review -> confirmed, claim -> FACT, audited).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.deps import get_current_user, require_admin
from app.services import sow as sow_service

router = APIRouter(prefix="/api", tags=["sow"])


@router.get("/sow")
async def list_sows(
    version: str = Query("v7"), _user: dict[str, Any] = Depends(get_current_user)
) -> list[dict[str, Any]]:
    return await sow_service.list_sows(version)


@router.get("/sow/{sow_id}")
async def sow_detail(
    sow_id: UUID,
    version: str = Query("v7"),
    _user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    found = await sow_service.sow_detail(str(sow_id), version)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="SOW not found")
    return found


@router.post("/admin/sow/scan/{version}")
async def scan(version: str, user: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
    return await sow_service.scan_sows(version)


@router.post("/sow/matches/{match_id}/confirm")
async def confirm(
    match_id: UUID, user: dict[str, Any] = Depends(get_current_user)
) -> dict[str, Any]:
    out = await sow_service.confirm_match(str(match_id), str(user["uid"]))
    if not out["ok"]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="match not found or not reviewable")
    return out
