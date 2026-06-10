"""Evidence API (F7) — the News watch (D1) read model + the weekly scan job trigger.

GET /api/evidence serves gated evidence items with the surfaceable source sub-object
{name,type,tier,url,ers,fetched_at} (R6) and the expected-catalogue-impact class (R5); the
last/next-scan indicator reads config/schedules.yaml so the page reflects the WEEKLY cadence and
never implies real-time. The consultant loop stages a GATED suggestion only (D3 applies it).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from app.deps import get_current_user, require_admin
from app.services import benchmarks as benchmarks_svc
from app.services import evidence as evidence_svc

router = APIRouter(prefix="/api", tags=["evidence"])


class NewsSourceOut(BaseModel):
    name: str
    type: str
    tier: str
    url: str
    ers: float
    fetched_at: str


class NewsItemOut(BaseModel):
    id: str
    title: str
    date: str
    mag: str
    tier: str
    label: str
    impact: str
    impact_label: str
    impact_note: str
    reliability: float
    source: NewsSourceOut
    affects: list[list[Any]]
    chain: str | None


class NewsOut(BaseModel):
    items: list[NewsItemOut]
    impacts: list[dict[str, str]]
    scan: dict[str, Any]


class LoopOut(BaseModel):
    staged: bool
    status: str
    reason: str | None = None
    suggestion_id: str | None = None
    kind: str | None = None
    target: str | None = None


class BenchItemOut(BaseModel):
    id: str
    metric: str
    unit: str
    segment: str
    date: str
    n: int
    observations: list[float]
    p25: float
    p50: float
    p75: float
    ci_low: float | None
    ci_high: float | None
    thin: bool
    coverage_note: str | None
    methodology: str
    verdict: str
    verdict_note: str
    label: str
    tier: str
    ers: float
    reliability: float
    source: NewsSourceOut
    affects: list[list[Any]]
    chain: str | None


class BenchOut(BaseModel):
    items: list[BenchItemOut]
    segments: list[str]
    scan: dict[str, Any]


@router.get("/evidence")
async def evidence(
    kind: str = Query("news"),
    impact: str | None = Query(None),
    tier: str | None = Query(None),
    segment: str | None = Query(None),
    version: str | None = Query(None),
    _user: dict[str, Any] = Depends(get_current_user),
) -> NewsOut | BenchOut:
    if kind == "news":
        result = await evidence_svc.list_news(impact=impact, tier=tier, version=version)
        return NewsOut(
            items=[
                NewsItemOut(**{**vars(i), "source": NewsSourceOut(**vars(i.source))})
                for i in result.items
            ],
            impacts=result.impacts,
            scan=result.scan,
        )
    if kind == "benchmark":
        bench = await benchmarks_svc.list_benchmarks(segment=segment, version=version)
        return BenchOut(
            items=[
                BenchItemOut(**{**vars(i), "source": NewsSourceOut(**vars(i.source))})
                for i in bench.items
            ],
            segments=bench.segments,
            scan=bench.scan,
        )
    raise HTTPException(
        status.HTTP_400_BAD_REQUEST,
        detail=f"evidence kind '{kind}' is not ingested yet — wired kinds: news, benchmark",
    )


@router.post("/admin/evidence/scan/news/{version}")
async def scan_news(
    version: str, _admin: dict[str, Any] = Depends(require_admin)
) -> dict[str, Any]:
    """Run the weekly news ingest job inline (hermetic); Cloud Scheduler triggers it in the
    cloud per config/schedules.yaml."""
    return await evidence_svc.scan_news(version)


@router.post("/evidence/news/{news_id}/loop")
async def news_loop(news_id: str, user: dict[str, Any] = Depends(get_current_user)) -> LoopOut:
    result = await evidence_svc.propose_from_news(news_id, str(user["uid"]))
    if result.get("status") == "not_found":
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="news item not found")
    return LoopOut(**result)


@router.post("/admin/evidence/scan/benchmarks/{version}")
async def scan_benchmarks(
    version: str, _admin: dict[str, Any] = Depends(require_admin)
) -> dict[str, Any]:
    """Run the monthly benchmark ingest inline (hermetic); Cloud Scheduler triggers it in the
    cloud per config/schedules.yaml."""
    return await benchmarks_svc.scan_benchmarks(version)


@router.post("/evidence/benchmark/{benchmark_id}/loop")
async def benchmark_loop(
    benchmark_id: str, user: dict[str, Any] = Depends(get_current_user)
) -> LoopOut:
    result = await benchmarks_svc.propose_from_benchmark(benchmark_id, str(user["uid"]))
    if result.get("status") == "not_found":
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="benchmark not found")
    return LoopOut(**result)
