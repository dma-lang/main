"""Catalogue read surfaces (version-scoped, F9 conventions) over the cat_<version> data plane.

Lights up Capability workbench (tree + detail) and Mission control (pillar summary) on real data.
"""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
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
    # Live counts (truthful now, auto-correct as F5 carry-forward / enrichment seed these tables).
    n_use_cases: int = 0
    n_stories: int = 0
    n_platforms: int = 0


class PillarSummary(BaseModel):
    pillar_id: str
    name: str
    subcap_count: int
    completeness: float
    decay: int


class CatalogueSummary(BaseModel):
    version_id: str
    total_subcaps: int
    pillars: list[PillarSummary]


class StoryRow(BaseModel):
    story_key: str
    project_key: str | None = None
    summary: str | None = None
    confidence_level: str | None = None
    composite_score: float | None = None
    ac_score: float | None = None
    sd_score: float | None = None
    story_score: float | None = None
    story_sv_code: str | None = None
    tier: str | None = None


class StoryPage(BaseModel):
    total: int
    page: int
    size: int
    items: list[StoryRow]


class Persona(BaseModel):
    persona_id: str
    canonical_name: str
    role_description: str | None = None


class Platform(BaseModel):
    l3_id: str
    name: str
    vendor: str | None = None
    category: str | None = None


class UseCase(BaseModel):
    use_case_id: str
    archetype: str | None = None
    name: str
    description: str | None = None


class Maturity(BaseModel):
    level: str
    descriptor: str | None = None
    features: str | None = None


class OfferingRef(BaseModel):
    offering_id: str
    name: str
    category: str | None = None


class SubcapEnrichment(BaseModel):
    personas: list[Persona]
    platforms: list[Platform]
    use_cases: list[UseCase]
    maturity: list[Maturity]
    offerings: list[OfferingRef]


class PlatformRow(BaseModel):
    l3_id: str
    name: str
    vendor: str | None = None
    category: str | None = None
    subcap_count: int
    p1: int
    p2: int
    p3: int
    p4: int
    stories: int


class PlatformSubcap(BaseModel):
    id: str
    pillar: str
    name: str


class PlatformDetail(BaseModel):
    l3_id: str
    name: str
    vendor: str | None = None
    category: str | None = None
    subcaps: list[PlatformSubcap]


class VendorRow(BaseModel):
    vendor: str
    plats: int
    subcap_count: int
    p1: int
    p2: int
    p3: int
    p4: int


class UseCaseRow(BaseModel):
    use_case_id: str
    archetype: str | None = None
    description: str | None = None
    subcap_id: str
    subcap_name: str
    pillar: str
    category: str


class ArchetypeFacet(BaseModel):
    archetype: str
    count: int


class UseCasePage(BaseModel):
    total: int
    page: int
    size: int
    items: list[UseCaseRow]
    archetypes: list[ArchetypeFacet]


class LifecycleSubcap(BaseModel):
    id: str
    name: str
    pillar: str
    stories: int
    offering_id: str | None = None
    offering_name: str | None = None


class LifecycleSummary(BaseModel):
    subcaps_delivered: int
    offerings: int
    covered_pct: int
    gaps: int
    top: list[LifecycleSubcap]


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
    v = await resolve_version(version)
    s = _schema(v)
    sql = text(
        "SELECT s.subcap_id AS id, s.name, cat.pillar_id AS pillar, cat.name AS category, "
        "cap.name AS cluster, s.description, s.solution_type, s.tier, s.lifecycle_state, "
        "s.completeness, "
        f"(SELECT count(*) FROM {s}.use_case uc WHERE uc.subcap_id = s.subcap_id) AS n_use_cases, "
        f"(SELECT count(*) FROM {s}.subcap_platform sp WHERE sp.subcap_id = s.subcap_id) "
        "AS n_platforms, "
        "(SELECT count(*) FROM control.story_catalogue_link scl "
        "WHERE scl.subcap_id = s.subcap_id AND scl.version_id = :ver) AS n_stories "
        + _JOINS.format(s=s)
        + " WHERE s.subcap_id = :sid"
    )
    async with _engine().connect() as conn:
        row = (await conn.execute(sql, {"sid": subcap_id, "ver": v.version_id})).mappings().first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"subcap '{subcap_id}' not found")
    return SubcapDetail.model_validate(dict(row))


@router.get("/{version}/subcaps/{subcap_id}/stories")
async def subcap_stories(
    version: str,
    subcap_id: str,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    _user: dict[str, Any] = Depends(get_current_user),
) -> StoryPage:
    """Confirmed delivery stories carried onto this subcap (F5), highest composite first."""
    v = await resolve_version(version)
    where = (
        "FROM control.story_catalogue_link scl "
        "JOIN control.story st ON st.story_key = scl.story_key "
        "WHERE scl.version_id = :ver AND scl.subcap_id = :sid"
    )
    rows_sql = text(
        "SELECT st.story_key, st.project_key, st.summary, st.confidence_level::text, "
        "st.composite_score::float AS composite_score, st.ac_score::float AS ac_score, "
        "st.sd_score::float AS sd_score, st.story_score::float AS story_score, "
        "st.story_sv_code, st.tier " + where + " ORDER BY st.composite_score DESC NULLS LAST, "
        "st.story_key LIMIT :size OFFSET :off"
    )
    params = {"ver": v.version_id, "sid": subcap_id}
    async with _engine().connect() as conn:
        total = (await conn.execute(text("SELECT count(*) " + where), params)).scalar() or 0
        rows = (
            (await conn.execute(rows_sql, {**params, "size": size, "off": (page - 1) * size}))
            .mappings()
            .all()
        )
    items = [StoryRow.model_validate(dict(r)) for r in rows]
    return StoryPage(total=int(total), page=page, size=size, items=items)


@router.get("/{version}/subcaps/{subcap_id}/enrichment")
async def subcap_enrichment(
    version: str, subcap_id: str, _user: dict[str, Any] = Depends(get_current_user)
) -> SubcapEnrichment:
    """Personas, L3 platforms, use cases and M1-M5 maturity for a subcap (Overview/Use/Maturity)."""
    s = _schema(await resolve_version(version))
    q_personas = text(
        f"SELECT p.persona_id, p.canonical_name, p.role_description FROM {s}.subcap_persona sp "
        f"JOIN {s}.persona p ON p.persona_id = sp.persona_id WHERE sp.subcap_id = :sid "
        "ORDER BY p.canonical_name"
    )
    q_platforms = text(
        f"SELECT l.l3_id, l.name, v.name AS vendor, l.category FROM {s}.subcap_platform sp "
        f"JOIN {s}.l3_platform l ON l.l3_id = sp.l3_id "
        f"LEFT JOIN {s}.vendor v ON v.vendor_id = l.vendor_id WHERE sp.subcap_id = :sid "
        "ORDER BY l.name"
    )
    q_uc = text(
        f"SELECT use_case_id, archetype, name, description FROM {s}.use_case "
        "WHERE subcap_id = :sid ORDER BY use_case_id"
    )
    q_mat = text(
        f"SELECT level, descriptor, features FROM {s}.maturity_descriptor "
        "WHERE subcap_id = :sid ORDER BY level"
    )
    q_off = text(
        f"SELECT o.offering_id, o.name, o.category FROM {s}.offering_subcap os "
        f"JOIN {s}.offering o ON o.offering_id = os.offering_id WHERE os.subcap_id = :sid "
        "ORDER BY o.name"
    )
    p = {"sid": subcap_id}
    async with _engine().connect() as conn:
        personas = (await conn.execute(q_personas, p)).mappings().all()
        platforms = (await conn.execute(q_platforms, p)).mappings().all()
        use_cases = (await conn.execute(q_uc, p)).mappings().all()
        maturity = (await conn.execute(q_mat, p)).mappings().all()
        offerings = (await conn.execute(q_off, p)).mappings().all()
    return SubcapEnrichment(
        personas=[Persona.model_validate(dict(r)) for r in personas],
        platforms=[Platform.model_validate(dict(r)) for r in platforms],
        use_cases=[UseCase.model_validate(dict(r)) for r in use_cases],
        maturity=[Maturity.model_validate(dict(r)) for r in maturity],
        offerings=[OfferingRef.model_validate(dict(r)) for r in offerings],
    )


@router.get("/{version}/summary")
async def summary(
    version: str, _user: dict[str, Any] = Depends(get_current_user)
) -> CatalogueSummary:
    v = await resolve_version(version)
    s = _schema(v)
    sql = text(
        "SELECT p.pillar_id, p.name, count(s.subcap_id) AS subcap_count, "
        "coalesce(avg(s.completeness), 0)::float AS completeness, "
        "count(s.subcap_id) FILTER "
        "(WHERE s.lifecycle_state IN ('declining', 'fading', 'dead')) AS decay "
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


_PLATFORMS_SQL = (
    "SELECT l.l3_id, l.name, v.name AS vendor, l.category, "
    "count(DISTINCT sp.subcap_id) AS subcap_count, "
    "count(DISTINCT sp.subcap_id) FILTER (WHERE left(sp.subcap_id, 2) = 'P1') AS p1, "
    "count(DISTINCT sp.subcap_id) FILTER (WHERE left(sp.subcap_id, 2) = 'P2') AS p2, "
    "count(DISTINCT sp.subcap_id) FILTER (WHERE left(sp.subcap_id, 2) = 'P3') AS p3, "
    "count(DISTINCT sp.subcap_id) FILTER (WHERE left(sp.subcap_id, 2) = 'P4') AS p4, "
    "coalesce(sum(stc.n), 0)::int AS stories "
    "FROM {s}.l3_platform l "
    "LEFT JOIN {s}.vendor v ON v.vendor_id = l.vendor_id "
    "LEFT JOIN {s}.subcap_platform sp ON sp.l3_id = l.l3_id "
    "LEFT JOIN (SELECT subcap_id, count(*) n FROM control.story_catalogue_link "
    "WHERE version_id = :ver GROUP BY subcap_id) stc ON stc.subcap_id = sp.subcap_id "
    "GROUP BY l.l3_id, l.name, v.name, l.category "
    "ORDER BY subcap_count DESC, l.l3_id"
)


@router.get("/{version}/platforms")
async def list_platforms(
    version: str, _user: dict[str, Any] = Depends(get_current_user)
) -> list[PlatformRow]:
    """L3 platforms with per-pillar subcap coverage + total stories (Platform catalog)."""
    v = await resolve_version(version)
    sql = text(_PLATFORMS_SQL.format(s=_schema(v)))
    async with _engine().connect() as conn:
        rows = (await conn.execute(sql, {"ver": v.version_id})).mappings().all()
    return [PlatformRow.model_validate(dict(r)) for r in rows]


@router.get("/{version}/platforms/{l3_id}")
async def platform_detail(
    version: str, l3_id: str, _user: dict[str, Any] = Depends(get_current_user)
) -> PlatformDetail:
    s = _schema(await resolve_version(version))
    meta_sql = text(
        f"SELECT l.l3_id, l.name, v.name AS vendor, l.category FROM {s}.l3_platform l "
        f"LEFT JOIN {s}.vendor v ON v.vendor_id = l.vendor_id WHERE l.l3_id = :lid"
    )
    subs_sql = text(
        f"SELECT sp.subcap_id AS id, left(sp.subcap_id, 2) AS pillar, s.name "
        f"FROM {s}.subcap_platform sp JOIN {s}.subcap s ON s.subcap_id = sp.subcap_id "
        "WHERE sp.l3_id = :lid ORDER BY sp.subcap_id"
    )
    async with _engine().connect() as conn:
        meta = (await conn.execute(meta_sql, {"lid": l3_id})).mappings().first()
        if meta is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"platform '{l3_id}' not found")
        subs = (await conn.execute(subs_sql, {"lid": l3_id})).mappings().all()
    return PlatformDetail(
        **dict(meta), subcaps=[PlatformSubcap.model_validate(dict(r)) for r in subs]
    )


@router.get("/{version}/vendors")
async def list_vendors(
    version: str, _user: dict[str, Any] = Depends(get_current_user)
) -> list[VendorRow]:
    """Per-vendor deduped subcap coverage by pillar (the Platform catalog heatmap)."""
    s = _schema(await resolve_version(version))
    sql = text(
        "SELECT coalesce(v.name, 'Unattributed') AS vendor, count(DISTINCT l.l3_id) AS plats, "
        "count(DISTINCT sp.subcap_id) AS subcap_count, "
        "count(DISTINCT sp.subcap_id) FILTER (WHERE left(sp.subcap_id, 2) = 'P1') AS p1, "
        "count(DISTINCT sp.subcap_id) FILTER (WHERE left(sp.subcap_id, 2) = 'P2') AS p2, "
        "count(DISTINCT sp.subcap_id) FILTER (WHERE left(sp.subcap_id, 2) = 'P3') AS p3, "
        "count(DISTINCT sp.subcap_id) FILTER (WHERE left(sp.subcap_id, 2) = 'P4') AS p4 "
        f"FROM {s}.l3_platform l LEFT JOIN {s}.vendor v ON v.vendor_id = l.vendor_id "
        f"LEFT JOIN {s}.subcap_platform sp ON sp.l3_id = l.l3_id "
        "GROUP BY coalesce(v.name, 'Unattributed') ORDER BY subcap_count DESC, vendor"
    )
    async with _engine().connect() as conn:
        rows = (await conn.execute(sql)).mappings().all()
    return [VendorRow.model_validate(dict(r)) for r in rows]


@router.get("/{version}/use-cases")
async def list_use_cases(
    version: str,
    pillar: str = Query(""),
    category: str = Query(""),
    archetype: str = Query(""),
    q: str = Query(""),
    page: int = Query(1, ge=1),
    size: int = Query(12, ge=1, le=60),
    _user: dict[str, Any] = Depends(get_current_user),
) -> UseCasePage:
    """Actual use cases, filterable by pillar / area / type / text (Use case explorer)."""
    s = _schema(await resolve_version(version))
    joins = (
        f"FROM {s}.use_case uc "
        f"JOIN {s}.subcap sc ON sc.subcap_id = uc.subcap_id "
        f"JOIN {s}.capability cap ON cap.capability_id = sc.capability_id "
        f"JOIN {s}.category cat ON cat.category_id = cap.category_id"
    )
    where = (
        " WHERE (:pillar = '' OR left(uc.subcap_id, 2) = :pillar) "
        "AND (:category = '' OR cat.category_id = :category) "
        "AND (:archetype = '' OR uc.archetype = :archetype) "
        "AND (:q = '' OR uc.description ILIKE :qlike OR sc.name ILIKE :qlike)"
    )
    facet_where = (
        " WHERE (:pillar = '' OR left(uc.subcap_id, 2) = :pillar) "
        "AND (:category = '' OR cat.category_id = :category) AND uc.archetype IS NOT NULL"
    )
    params = {
        "pillar": pillar,
        "category": category,
        "archetype": archetype,
        "q": q,
        "qlike": f"%{q}%",
    }
    items_sql = text(
        "SELECT uc.use_case_id, uc.archetype, uc.description, uc.subcap_id, "
        "sc.name AS subcap_name, left(uc.subcap_id, 2) AS pillar, cat.name AS category "
        + joins
        + where
        + " ORDER BY uc.use_case_id LIMIT :size OFFSET :off"
    )
    count_sql = text("SELECT count(*) " + joins + where)
    facet_sql = text(
        "SELECT uc.archetype, count(*) AS count "
        + joins
        + facet_where
        + " GROUP BY uc.archetype ORDER BY count DESC, uc.archetype"
    )
    async with _engine().connect() as conn:
        total = (await conn.execute(count_sql, params)).scalar() or 0
        off = (page - 1) * size
        rows = (
            (await conn.execute(items_sql, {**params, "size": size, "off": off})).mappings().all()
        )
        facets = (await conn.execute(facet_sql, params)).mappings().all()
    return UseCasePage(
        total=int(total),
        page=page,
        size=size,
        items=[UseCaseRow.model_validate(dict(r)) for r in rows],
        archetypes=[ArchetypeFacet.model_validate(dict(r)) for r in facets],
    )


@router.get("/{version}/lifecycle")
async def lifecycle(
    version: str, _user: dict[str, Any] = Depends(get_current_user)
) -> LifecycleSummary:
    """Most-delivered subcaps mapped to productized offerings + coverage KPIs (Lifecycle)."""
    v = await resolve_version(version)
    s = _schema(v)
    off_join = (
        "(SELECT os.subcap_id, min(o.offering_id) AS offering_id, min(o.name) AS offering_name "
        f"FROM {s}.offering_subcap os JOIN {s}.offering o ON o.offering_id = os.offering_id "
        "GROUP BY os.subcap_id) off"
    )
    delivered_cte = (
        "(SELECT subcap_id, count(*) AS stories FROM control.story_catalogue_link "
        "WHERE version_id = :ver GROUP BY subcap_id) sc"
    )
    top_sql = text(
        "SELECT sc.subcap_id AS id, s.name, left(sc.subcap_id, 2) AS pillar, "
        "sc.stories::int AS stories, off.offering_id, off.offering_name "
        f"FROM {delivered_cte} JOIN {s}.subcap s ON s.subcap_id = sc.subcap_id "
        f"LEFT JOIN {off_join} ON off.subcap_id = sc.subcap_id "
        "ORDER BY sc.stories DESC, sc.subcap_id LIMIT 8"
    )
    kpi_sql = text(
        "SELECT count(*) AS delivered, "
        "count(*) FILTER (WHERE off.offering_id IS NOT NULL) AS covered "
        f"FROM {delivered_cte} LEFT JOIN {off_join} ON off.subcap_id = sc.subcap_id"
    )
    async with _engine().connect() as conn:
        offerings = (await conn.execute(text(f"SELECT count(*) FROM {s}.offering"))).scalar() or 0
        kpi = (await conn.execute(kpi_sql, {"ver": v.version_id})).mappings().first()
        rows = (await conn.execute(top_sql, {"ver": v.version_id})).mappings().all()
    delivered = int(kpi["delivered"]) if kpi else 0
    covered = int(kpi["covered"]) if kpi else 0
    return LifecycleSummary(
        subcaps_delivered=delivered,
        offerings=int(offerings),
        covered_pct=round(100 * covered / delivered) if delivered else 0,
        gaps=delivered - covered,
        top=[LifecycleSubcap.model_validate(dict(r)) for r in rows],
    )
