"""Admin operations (F4) + the source registry (Settings · admin sources).

Provisioning trigger and the app's persisted ingestion points: GET /sources composes the
control.ingest_source registry with config/schedules.yaml and the last ingest_run per source —
which origin is active (database fixture vs online), cadence, last poll and staleness, nothing
hidden. PATCH /sources/{key} persists the enable switch the scan jobs enforce.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.deps import require_admin
from app.services import admins, provision, sources, stories

router = APIRouter(prefix="/api/admin", tags=["admin"])


class AdminGrantIn(BaseModel):
    email: str
    note: str = ""


class SourceOut(BaseModel):
    key: str
    name: str
    type: str
    tier: str
    enabled: bool
    mode: str
    origin_active: str
    origin_recorded: str
    origin_live: str
    cadence: str
    cron: str | None
    next_run: str | None
    last_run: str | None
    last_status: str | None
    last_stats: dict[str, Any]
    status: str
    notes: str


class SourcePatch(BaseModel):
    enabled: bool


@router.post("/provision/{version}")
async def provision_version(
    version: str, _admin: dict[str, Any] = Depends(require_admin)
) -> dict[str, Any]:
    """Generate + seed cat_<version> and register it (admin only)."""
    return await provision.bring_version_online(version, label=f"Catalogue {version}.0")


@router.post("/carry-forward/{version}")
async def carry_forward(
    version: str, _admin: dict[str, Any] = Depends(require_admin)
) -> dict[str, Any]:
    """Ingest the canonical story corpus and carry it onto cat_<version> (F5, admin only)."""
    return await stories.carry_forward(version)


@router.get("/sources")
async def list_sources(_admin: dict[str, Any] = Depends(require_admin)) -> list[SourceOut]:
    """The persisted source registry: every ingestion point with its ACTIVE origin (database
    fixture vs online, per LLM_MODE), cadence, last poll and staleness — warned, never hidden."""
    return [SourceOut(**vars(s)) for s in await sources.list_sources()]


@router.patch("/sources/{key}")
async def patch_source(
    key: str, body: SourcePatch, admin: dict[str, Any] = Depends(require_admin)
) -> dict[str, Any]:
    """Persist the per-source enable switch (audited). Scan jobs enforce it before any fetch."""
    result = await sources.set_enabled(key, body.enabled, str(admin["uid"]))
    if result.get("status") == "not_found":
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"unknown source '{key}'")
    return result


@router.get("/admins")
async def list_admins(_admin: dict[str, Any] = Depends(require_admin)) -> list[dict[str, Any]]:
    """The administrator config space: every admin with its source (bootstrap env vs runtime
    grant). Bootstrap admins are shown but not removable from the UI."""
    return await admins.list_admins()


@router.post("/admins")
async def grant_admin(
    body: AdminGrantIn, admin: dict[str, Any] = Depends(require_admin)
) -> dict[str, Any]:
    """Grant an administrator at runtime (persisted + audited). Domain-restricted."""
    result = await admins.grant_admin(body.email, str(admin["uid"]), body.note)
    if result.get("status") in ("invalid", "rejected"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=result.get("reason"))
    return result


@router.delete("/admins/{email}")
async def revoke_admin(
    email: str, admin: dict[str, Any] = Depends(require_admin)
) -> dict[str, Any]:
    """Revoke a granted administrator (persisted + audited). Bootstrap admins cannot be removed."""
    result = await admins.revoke_admin(email, str(admin["uid"]))
    if result.get("status") == "not_found":
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"'{email}' is not a granted admin")
    if result.get("status") == "rejected":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=result.get("reason"))
    return result
