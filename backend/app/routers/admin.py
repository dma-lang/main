"""Admin operations (F4). Provisioning trigger; the full schema-mapping studio layers on later."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from app.deps import require_admin
from app.services import provision

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.post("/provision/{version}")
async def provision_version(
    version: str, _admin: dict[str, Any] = Depends(require_admin)
) -> dict[str, Any]:
    """Generate + seed cat_<version> and register it (admin only)."""
    return await provision.bring_version_online(version, label=f"Catalogue {version}.0")
