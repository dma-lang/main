"""Story library (C2) — the canonical 14,406-row Jira corpus (control.story), filterable.

Read-only over ``control.story``; the per-version carry link lives in ``story_subcap_carry`` and is
surfaced on the subcap deep-dive Delivery tab. Synthetic stories are excluded by default.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import text

from app import db
from app.deps import get_current_user

router = APIRouter(prefix="/api", tags=["stories"])


class StoryLibraryRow(BaseModel):
    story_key: str
    summary: str | None = None
    subcap_id: str
    subcap_name: str | None = None
    pillar: str | None = None
    sv: str | None = None
    composite_score: float | None = None
    confidence_level: str | None = None
    ac_score: float | None = None
    sd_score: float | None = None
    story_score: float | None = None
    is_synthetic: bool = False
    source_system: str | None = None


class StoryLibraryPage(BaseModel):
    total: int
    page: int
    size: int
    items: list[StoryLibraryRow]
    high: int
    medium: int
    low: int
    jira_total: int  # the real corpus (analysis-grade)
    synthetic_total: int  # workbook-embedded synthetic/derived rows (labelled, excluded by default)
    buckets: list[int]  # composite distribution, 6 buckets of 0.6


_WHERE = (
    # synthetic mode: exclude (default, Jira-only analysis) | include | only
    " WHERE (CASE :syn WHEN 'include' THEN true WHEN 'only' THEN is_synthetic "
    "ELSE NOT is_synthetic END) "
    "AND (:pillar = '' OR pillar_id = :pillar) "
    "AND (:conf = '' OR confidence_level::text = :conf) "
    "AND (:sv = '' OR story_sv_code = :sv) "
    "AND coalesce(composite_score, 0) >= :minc "
    "AND (:q = '' OR summary ILIKE :qlike OR story_key ILIKE :qlike OR sub_cap_name ILIKE :qlike)"
)


@router.get("/stories")
async def list_stories(
    pillar: str = Query(""),
    conf: str = Query(""),
    sv: str = Query(""),
    min_composite: float = Query(0.0, ge=0),
    q: str = Query(""),
    synthetic: str = Query("exclude"),
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=50),
    _user: dict[str, Any] = Depends(get_current_user),
) -> StoryLibraryPage:
    engine = db.get_engine()
    if engine is None:
        return StoryLibraryPage(
            total=0,
            page=page,
            size=size,
            items=[],
            high=0,
            medium=0,
            low=0,
            jira_total=0,
            synthetic_total=0,
            buckets=[0] * 6,
        )
    if synthetic not in ("exclude", "include", "only"):
        synthetic = "exclude"
    params = {
        "syn": synthetic,
        "pillar": pillar,
        "conf": conf,
        "sv": sv,
        "minc": min_composite,
        "q": q,
        "qlike": f"%{q}%",
    }
    items_sql = text(
        "SELECT story_key, summary, sub_cap_id AS subcap_id, sub_cap_name AS subcap_name, "
        "pillar_id AS pillar, story_sv_code AS sv, composite_score::float AS composite_score, "
        "confidence_level::text AS confidence_level, ac_score::float AS ac_score, "
        "sd_score::float AS sd_score, story_score::float AS story_score, "
        "is_synthetic, source_system "
        "FROM control.story" + _WHERE + " ORDER BY composite_score DESC NULLS LAST, story_key "
        "LIMIT :size OFFSET :off"
    )
    agg_sql = text(
        "SELECT count(*) AS total, "
        "count(*) FILTER (WHERE confidence_level = 'HIGH') AS high, "
        "count(*) FILTER (WHERE confidence_level = 'MEDIUM') AS medium, "
        "count(*) FILTER (WHERE confidence_level = 'LOW') AS low, "
        "count(*) FILTER (WHERE bkt = 0) AS b0, count(*) FILTER (WHERE bkt = 1) AS b1, "
        "count(*) FILTER (WHERE bkt = 2) AS b2, count(*) FILTER (WHERE bkt = 3) AS b3, "
        "count(*) FILTER (WHERE bkt = 4) AS b4, count(*) FILTER (WHERE bkt = 5) AS b5 "
        "FROM (SELECT confidence_level, "
        "least(5, greatest(0, floor(coalesce(composite_score, 0) / 0.6)))::int AS bkt "
        "FROM control.story" + _WHERE + ") t"
    )
    split_sql = text(
        "SELECT count(*) FILTER (WHERE NOT is_synthetic) AS jira, "
        "count(*) FILTER (WHERE is_synthetic) AS synthetic FROM control.story"
    )
    async with engine.connect() as conn:
        split = (await conn.execute(split_sql)).mappings().first()
        agg = (await conn.execute(agg_sql, params)).mappings().first()
        rows = (
            (await conn.execute(items_sql, {**params, "size": size, "off": (page - 1) * size}))
            .mappings()
            .all()
        )
    a = dict(agg) if agg else {}
    sp = dict(split) if split else {}
    return StoryLibraryPage(
        jira_total=int(sp.get("jira", 0)),
        synthetic_total=int(sp.get("synthetic", 0)),
        total=int(a.get("total", 0)),
        page=page,
        size=size,
        items=[StoryLibraryRow.model_validate(dict(r)) for r in rows],
        high=int(a.get("high", 0)),
        medium=int(a.get("medium", 0)),
        low=int(a.get("low", 0)),
        buckets=[int(a.get(f"b{i}", 0)) for i in range(6)],
    )
