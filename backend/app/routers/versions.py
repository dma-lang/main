"""Version timeline (G1) read surface — applies the F9 conventions (auth + version resolution)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text

from app import db
from app.deps import get_current_user
from app.versioning import Version, resolve_version

router = APIRouter(prefix="/api", tags=["versions"])


class VersionInfo(BaseModel):
    version_id: str
    label: str
    status: str
    schema_name: str
    created_at: str | None = None


@router.get("/versions")
async def list_versions(_user: dict[str, Any] = Depends(get_current_user)) -> list[VersionInfo]:
    engine = db.get_engine()
    if engine is None:
        return []
    sql = (
        "SELECT version_id, label, status, schema_name, created_at::text AS created_at "
        "FROM control.catalogue_version ORDER BY created_at"
    )
    async with engine.connect() as conn:
        rows = (await conn.execute(text(sql))).mappings().all()
    return [VersionInfo.model_validate(dict(r)) for r in rows]


@router.get("/versions/{version}")
async def get_version(
    version: str, _user: dict[str, Any] = Depends(get_current_user)
) -> VersionInfo:
    found: Version = await resolve_version(version)
    return VersionInfo(
        version_id=found.version_id,
        label=found.label,
        status=found.status,
        schema_name=found.schema_name,
    )
