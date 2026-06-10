"""Trends API (F7) — the Trends monitor (D2) read model + the weekly detection job trigger.

GET /api/trends serves staged/promoted/etc. trend cards, each with the four-signal breakdown
(velocity/diversity/novelty/persistence), affected subcaps with the emergent flag, the trust
envelope (claim · tier · ERS · reasoning backlink), the window and per-status KPI counts. The
evidence drilldown lists the gated cluster behind a trend; feedback promotes/dismisses (feeding the
config-recalibration loop); the consultant loop stages a GATED suggestion (D3 applies it). Cadence
comes from config/schedules.yaml (weekly, after the news scan) — the page never implies real-time.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from app.deps import get_current_user, require_admin
from app.services import trends as trends_svc

router = APIRouter(prefix="/api", tags=["trends"])


class TrendSignalsOut(BaseModel):
    velocity: float
    diversity: float
    novelty: float
    persistence: float


class TrendSubcapOut(BaseModel):
    subcap_id: str
    name: str
    emergent: bool


class TrendItemOut(BaseModel):
    id: str
    label: str
    status: str
    window: str
    window_start: str
    window_end: str
    evidence_count: int
    score: float
    signals: TrendSignalsOut
    affects: list[TrendSubcapOut]
    emergent: bool
    label_claim: str
    tier: str
    ers: float
    chain: str | None


class TrendsOut(BaseModel):
    items: list[TrendItemOut]
    counts: dict[str, int]
    scan: dict[str, Any]


class TrendLoopOut(BaseModel):
    staged: bool
    status: str
    reason: str | None = None
    suggestion_id: str | None = None
    kind: str | None = None
    target: str | None = None


class FeedbackIn(BaseModel):
    verdict: str  # promote | dismiss


@router.get("/trends")
async def list_trends(
    status: str | None = Query(None),
    version: str | None = Query(None),
    _user: dict[str, Any] = Depends(get_current_user),
) -> TrendsOut:
    result = await trends_svc.list_trends(status=status, version=version)
    return TrendsOut(
        items=[
            TrendItemOut(
                **{
                    **vars(i),
                    "signals": TrendSignalsOut(**vars(i.signals)),
                    "affects": [TrendSubcapOut(**vars(a)) for a in i.affects],
                }
            )
            for i in result.items
        ],
        counts=result.counts,
        scan=result.scan,
    )


@router.get("/trends/{trend_id}/evidence")
async def trend_evidence(
    trend_id: str, _user: dict[str, Any] = Depends(get_current_user)
) -> dict[str, Any]:
    result = await trends_svc.trend_evidence(trend_id)
    if not result.get("found"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="trend not found")
    return result


@router.post("/admin/trends/scan/{version}")
async def scan_trends(
    version: str, _admin: dict[str, Any] = Depends(require_admin)
) -> dict[str, Any]:
    """Run the weekly trend-detection job inline (hermetic); Cloud Scheduler triggers it in the
    cloud per config/schedules.yaml (Monday 06:30, after the news scan)."""
    return await trends_svc.detect_trends(version)


@router.post("/trends/{trend_id}/feedback")
async def trend_feedback(
    trend_id: str, body: FeedbackIn, user: dict[str, Any] = Depends(get_current_user)
) -> dict[str, Any]:
    result = await trends_svc.feedback(trend_id, body.verdict, str(user["uid"]))
    if result.get("status") == "invalid":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=result.get("reason"))
    return result


@router.post("/trends/{trend_id}/loop")
async def trend_loop(
    trend_id: str, user: dict[str, Any] = Depends(get_current_user)
) -> TrendLoopOut:
    result = await trends_svc.propose_from_trend(trend_id, str(user["uid"]))
    if result.get("status") == "not_found":
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="trend not found")
    return TrendLoopOut(**result)
