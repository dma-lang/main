"""Catalogue read surfaces (version-scoped, F9 conventions) over the cat_<version> data plane.

Lights up Capability workbench (tree + detail) and Mission control (pillar summary) on real data.
"""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app import db
from app.deps import get_current_user
from app.versioning import Version, resolve_version

router = APIRouter(prefix="/api/catalogue", tags=["catalogue"])

_SCHEMA_RE = re.compile(r"^cat_[a-z0-9_]+$")


def _engine() -> AsyncEngine:
    engine = db.get_engine()
    if engine is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="database unavailable")
    return engine


def _schema(v: Version) -> str:
    # schema_name comes from control.catalogue_version (our data); validated for defence in depth
    # since it is interpolated as a SQL identifier.
    if not _SCHEMA_RE.match(v.schema_name):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="invalid version schema")
    return v.schema_name


class SubcapNode(BaseModel):
    id: str
    name: str
    pillar: str
    cat_id: str
    cat_name: str
    cluster: str
    life: str
    is_new: bool


class SubcapDetail(BaseModel):
    id: str
    name: str
    pillar: str
    category: str
    cluster: str
    description: str | None = None
    solution_type: str | None = None
    tier: str | None = None
    lifecycle_state: str
    completeness: float | None = None


class PillarSummary(BaseModel):
    pillar_id: str
    name: str
    subcap_count: int
    completeness: float


class CatalogueSummary(BaseModel):
    version_id: str
    total_subcaps: int
    pillars: list[PillarSummary]


_JOINS = (
    "FROM {s}.subcap s "
    "JOIN {s}.capability cap ON cap.capability_id = s.capability_id "
    "JOIN {s}.category cat ON cat.category_id = cap.category_id"
)


@router.get("/{version}/subcaps")
async def list_subcaps(
    version: str, _user: dict[str, Any] = Depends(get_current_user)
) -> list[SubcapNode]:
    s = _schema(await resolve_version(version))
    sql = text(
        "SELECT s.subcap_id AS id, s.name, cat.pillar_id AS pillar, cat.category_id AS cat_id, "
        "cat.name AS cat_name, cap.name AS cluster, s.lifecycle_state AS life, false AS is_new "
        + _JOINS.format(s=s)
        + " ORDER BY s.subcap_id"
    )
    async with _engine().connect() as conn:
        rows = (await conn.execute(sql)).mappings().all()
    return [SubcapNode.model_validate(dict(r)) for r in rows]


@router.get("/{version}/subcaps/{subcap_id}")
async def get_subcap(
    version: str, subcap_id: str, _user: dict[str, Any] = Depends(get_current_user)
) -> SubcapDetail:
    s = _schema(await resolve_version(version))
    sql = text(
        "SELECT s.subcap_id AS id, s.name, cat.pillar_id AS pillar, cat.name AS category, "
        "cap.name AS cluster, s.description, s.solution_type, s.tier, s.lifecycle_state, "
        "s.completeness " + _JOINS.format(s=s) + " WHERE s.subcap_id = :sid"
    )
    async with _engine().connect() as conn:
        row = (await conn.execute(sql, {"sid": subcap_id})).mappings().first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"subcap '{subcap_id}' not found")
    return SubcapDetail.model_validate(dict(row))


@router.get("/{version}/summary")
async def summary(
    version: str, _user: dict[str, Any] = Depends(get_current_user)
) -> CatalogueSummary:
    v = await resolve_version(version)
    s = _schema(v)
    sql = text(
        "SELECT p.pillar_id, p.name, count(s.subcap_id) AS subcap_count, "
        "coalesce(avg(s.completeness), 0)::float AS completeness "
        f"FROM {s}.pillar p "
        f"LEFT JOIN {s}.category cat ON cat.pillar_id = p.pillar_id "
        f"LEFT JOIN {s}.capability cap ON cap.category_id = cat.category_id "
        f"LEFT JOIN {s}.subcap s ON s.capability_id = cap.capability_id "
        "GROUP BY p.pillar_id, p.name ORDER BY p.pillar_id"
    )
    async with _engine().connect() as conn:
        rows = (await conn.execute(sql)).mappings().all()
        total = (await conn.execute(text(f"SELECT count(*) FROM {s}.subcap"))).scalar()
    pillars = [PillarSummary.model_validate(dict(r)) for r in rows]
    return CatalogueSummary(version_id=v.version_id, total_subcaps=int(total or 0), pillars=pillars)
