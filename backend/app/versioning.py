"""Catalogue version resolution (F9).

Version-scoped routes resolve a `{version}` path param to a real, provisioned version (404 if not),
so every read is version-correct (§19). The data plane lives in the resolved schema_name (cat_<v>).
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException, status
from sqlalchemy import text

from app import db


@dataclass(frozen=True)
class Version:
    version_id: str
    schema_name: str
    status: str
    label: str


async def _fetch(clause: str, params: dict[str, object]) -> Version | None:
    engine = db.get_engine()
    if engine is None:
        return None
    sql = (
        "SELECT version_id, schema_name, status, label "
        "FROM control.catalogue_version " + clause + " LIMIT 1"
    )
    async with engine.connect() as conn:
        row = (await conn.execute(text(sql), params)).mappings().first()
    if row is None:
        return None
    return Version(
        version_id=str(row["version_id"]),
        schema_name=str(row["schema_name"]),
        status=str(row["status"]),
        label=str(row["label"]),
    )


async def get_active_version() -> Version | None:
    """The active / most-recent provisioned version, or None (no DB / nothing provisioned).
    Most-recent = highest NUMERIC version id (re-provisioning legacy v5 after v7 must never
    steal the default), created_at only as the tie-break."""
    return await _fetch(
        "WHERE status IN ('active', 'provisioned') "
        "ORDER BY coalesce(nullif(regexp_replace(version_id, '[^0-9]', '', 'g'), '')::int, 0) "
        "DESC, created_at DESC",
        {},
    )


async def resolve_version(version: str) -> Version:
    """Validate a {version} path param against control.catalogue_version (404 if unknown).
    A version that is uploaded-but-not-provisioned has no cat_<v> schema yet — reading it would
    be a raw SQL error, so it fails closed with the actionable next step instead."""
    found = await _fetch("WHERE version_id = :vid", {"vid": version})
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"version '{version}' not found")
    if found.status == "uploaded":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=f"version '{version}' is uploaded but not provisioned yet — run Apply & "
            "provision (onboarding or the Versions page) to bring it online",
        )
    return found
