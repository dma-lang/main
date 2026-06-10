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
from app.services import provision, sources, stories

router = APIRouter(prefix="/api/admin", tags=["admin"])


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
