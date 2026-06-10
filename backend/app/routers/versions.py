"""Version timeline (G1) + diff (G2) read surfaces — F9 conventions (auth + version resolution)."""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import text

from app import db
from app.deps import get_current_user
from app.versioning import Version, resolve_version

router = APIRouter(prefix="/api", tags=["versions"])

_SCHEMA_RE = re.compile(r"^cat_[a-z0-9_]+$")


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
        # newest (highest numeric version) first — the governed "most recent" order, so every
        # consumer defaults the same way the header/active-version resolution does
        "SELECT version_id, label, status, schema_name, created_at::text AS created_at "
        "FROM control.catalogue_version "
        "ORDER BY coalesce(nullif(regexp_replace(version_id, '[^0-9]', '', 'g'), '')::int, 0) "
        "DESC, created_at DESC"
    )
    async with engine.connect() as conn:
        rows = (await conn.execute(text(sql))).mappings().all()
    return [VersionInfo.model_validate(dict(r)) for r in rows]


class DiffRow(BaseModel):
    id: str
    name: str
    pillar: str


class DiffModified(BaseModel):
    id: str
    name: str
    pillar: str
    changes: list[str]  # which fields differ: name | lifecycle_state | description | tier


class DiffResp(BaseModel):
    a: str
    b: str
    added: list[DiffRow]  # in b, not in a
    removed: list[DiffRow]  # in a, not in b
    modified: list[DiffModified]
    unchanged: int


@router.get("/diff/{a}/{b}")
async def diff_versions(
    a: str, b: str, _user: dict[str, Any] = Depends(get_current_user)
) -> DiffResp:
    """Catalogue diff (G2): added / removed / modified subcaps between two PROVISIONED versions —
    a full outer join on subcap_id with per-field comparison. An unprovisioned version is a clear
    404 from resolve_version (the page tells the operator to provision it); a self-compare returns
    an empty diff. Renames across versions come from control.version_crosswalk once a real legacy
    workbook is ingested — id-identity is the honest baseline until then."""
    va = await resolve_version(a)
    vb = await resolve_version(b)
    for v in (va, vb):
        if not _SCHEMA_RE.match(v.schema_name):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="invalid version schema")
    engine = db.require_engine()
    sql = text(
        f"SELECT coalesce(sa.subcap_id, sb.subcap_id) AS id, "
        f"coalesce(sb.name, sa.name) AS name, "
        f"left(coalesce(sa.subcap_id, sb.subcap_id), 2) AS pillar, "
        f"(sa.subcap_id IS NULL) AS added, (sb.subcap_id IS NULL) AS removed, "
        f"(sa.name IS DISTINCT FROM sb.name) AS d_name, "
        f"(sa.lifecycle_state IS DISTINCT FROM sb.lifecycle_state) AS d_life, "
        f"(sa.description IS DISTINCT FROM sb.description) AS d_desc, "
        f"(sa.tier IS DISTINCT FROM sb.tier) AS d_tier "
        f"FROM {va.schema_name}.subcap sa "
        f"FULL OUTER JOIN {vb.schema_name}.subcap sb ON sb.subcap_id = sa.subcap_id"
    )
    async with engine.connect() as conn:
        rows = (await conn.execute(sql)).mappings().all()
    added: list[DiffRow] = []
    removed: list[DiffRow] = []
    modified: list[DiffModified] = []
    unchanged = 0
    for r in rows:
        base = {"id": r["id"], "name": r["name"], "pillar": r["pillar"]}
        if r["added"]:
            added.append(DiffRow(**base))
        elif r["removed"]:
            removed.append(DiffRow(**base))
        else:
            changes = [
                f
                for f, hit in (
                    ("name", r["d_name"]),
                    ("lifecycle_state", r["d_life"]),
                    ("description", r["d_desc"]),
                    ("tier", r["d_tier"]),
                )
                if hit
            ]
            if changes:
                modified.append(DiffModified(**base, changes=changes))
            else:
                unchanged += 1
    return DiffResp(
        a=va.version_id,
        b=vb.version_id,
        added=added,
        removed=removed,
        modified=modified,
        unchanged=unchanged,
    )


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
