"""Validation gates log (G4) + QA & audit (G5) — read-only transparency over the trust layer.

/api/gates aggregates the per-gate pass/fail distribution from validation_gate_run; /api/qa/metrics
reports the real gate pass-rate + reasoning-chain count + spend (admin-gated, $0 hermetic) with
honest nulls where the F6 eval / F11 meter are not wired; /api/audit-log is the append-only record
of every gated mutation.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import text

from app import db
from app.deps import get_current_user, require_admin
from app.services import change_flags as flags_svc
from app.services import embeddings as embeddings_svc
from app.services import kg as kg_svc
from app.services import subverticals as subverticals_svc
from app.services import use_case_gaps as use_case_gaps_svc

router = APIRouter(prefix="/api", tags=["governance"])


class GateStat(BaseModel):
    id: str
    name: str
    pass_pct: int
    warn_pct: int
    fail_pct: int
    score: float
    runs: int


class GatesLog(BaseModel):
    gates: list[GateStat]
    total_runs: int
    pass_runs: int
    fail_runs: int


def _gate_name(key: str) -> tuple[str, str]:
    gid, _, rest = key.partition("_")
    return gid, rest.replace("_", " ").title()


@router.get("/gates")
async def gates(_user: dict[str, Any] = Depends(get_current_user)) -> GatesLog:
    engine = db.get_engine()
    if engine is None:
        return GatesLog(gates=[], total_runs=0, pass_runs=0, fail_runs=0)
    async with engine.connect() as conn:
        rows = (
            (
                await conn.execute(
                    text(
                        "SELECT gate_results, verdict::text AS verdict "
                        "FROM control.validation_gate_run"
                    )
                )
            )
            .mappings()
            .all()
        )
    agg: dict[str, list[int]] = {}
    pass_runs = fail_runs = 0
    for r in rows:
        if r["verdict"] == "pass":
            pass_runs += 1
        else:
            fail_runs += 1
        for key, res in (r["gate_results"] or {}).items():
            a = agg.setdefault(key, [0, 0])
            if res.get("verdict") == "pass":
                a[0] += 1
            else:
                a[1] += 1
    stats: list[GateStat] = []
    for key in sorted(agg):
        p, f = agg[key]
        total = p + f
        gid, name = _gate_name(key)
        pass_pct = round(100 * p / total) if total else 0
        stats.append(
            GateStat(
                id=gid,
                name=name,
                pass_pct=pass_pct,
                warn_pct=0,
                fail_pct=100 - pass_pct,
                score=round(p / total, 2) if total else 0.0,
                runs=total,
            )
        )
    return GatesLog(
        gates=stats, total_runs=pass_runs + fail_runs, pass_runs=pass_runs, fail_runs=fail_runs
    )


class QaMetrics(BaseModel):
    gate_pass_rate: float | None
    total_runs: int
    reasoning_chains: int
    applied: int
    hallucination_rate: float | None = None  # F6 eval harness (not yet wired)
    retrieval_mrr: float | None = None  # F6 eval harness (not yet wired)
    spend_usd: float | None = None  # admin-only (R7); $0 in hermetic
    envelope_usd: int = 8000


@router.get("/qa/metrics")
async def qa_metrics(user: dict[str, Any] = Depends(get_current_user)) -> QaMetrics:
    engine = db.get_engine()
    if engine is None:
        return QaMetrics(gate_pass_rate=None, total_runs=0, reasoning_chains=0, applied=0)
    async with engine.connect() as conn:
        # The pass-rate measures AI-output trustworthiness (chat answers + suggestion/flag commits).
        # Change-flag *detection* runs (operation='contradiction') are the gates CATCHING an
        # anomaly, not an output failing — counting them would invert the metric, so they're
        # excluded here (the Gates log G4 still shows their full distribution).
        outputs = (
            "FROM control.validation_gate_run vr "
            "LEFT JOIN control.reasoning_chain rc ON rc.chain_id = vr.chain_id "
            "WHERE coalesce(rc.operation, '') <> 'contradiction'"
        )
        total = (await conn.execute(text(f"SELECT count(*) {outputs}"))).scalar() or 0
        passed = (
            await conn.execute(text(f"SELECT count(*) {outputs} AND vr.verdict = 'pass'"))
        ).scalar() or 0
        chains = (await conn.execute(text("SELECT count(*) FROM control.reasoning_chain"))).scalar()
        applied = (
            await conn.execute(
                text("SELECT count(*) FROM control.suggestion WHERE status = 'applied'")
            )
        ).scalar() or 0
    return QaMetrics(
        gate_pass_rate=round(100 * int(passed) / int(total), 1) if total else None,
        total_runs=int(total),
        reasoning_chains=int(chains or 0),
        applied=int(applied),
        spend_usd=0.0 if user.get("is_admin") else None,
    )


class AuditRow(BaseModel):
    audit_id: int
    actor: str | None
    action: str
    target_ref: str | None
    at: str | None
    meta: dict[str, Any]


@router.get("/audit-log")
async def audit_log(
    limit: int = Query(50, ge=1, le=200), _user: dict[str, Any] = Depends(get_current_user)
) -> list[AuditRow]:
    engine = db.get_engine()
    if engine is None:
        return []
    async with engine.connect() as conn:
        rows = (
            (
                await conn.execute(
                    text(
                        "SELECT audit_id, actor, action, target_ref, at::text AS at, meta "
                        "FROM control.audit_log ORDER BY at DESC, audit_id DESC LIMIT :n"
                    ),
                    {"n": limit},
                )
            )
            .mappings()
            .all()
        )
    return [AuditRow.model_validate(dict(r)) for r in rows]


class ChangeFlagOut(BaseModel):
    id: str
    sev: str
    kind: str
    age: str
    chain: str | None
    title: str
    body: str
    target: str | None
    name: str | None
    pillar: str | None
    gate_failed: str | None
    before: str | None
    after: str | None
    stories: int
    status: str


class ChangeFlagsOut(BaseModel):
    flags: list[ChangeFlagOut]
    counts: dict[str, int]


class FlagActionOut(BaseModel):
    resolved: bool
    status: str
    gate_failed: str | None = None
    before: str | None = None
    after: str | None = None


class FlagRejectBody(BaseModel):
    reason: str = ""


@router.get("/change-flags")
async def change_flags(
    status_filter: str = Query("open", alias="status"),
    severity: str | None = Query(None, description="BLOCKING | HIGH | MED | LOW (unset = all)"),
    _user: dict[str, Any] = Depends(get_current_user),
) -> ChangeFlagsOut:
    result = await flags_svc.list_flags(status_filter, severity)
    return ChangeFlagsOut(
        flags=[ChangeFlagOut(**vars(f)) for f in result.flags], counts=result.counts
    )


@router.post("/admin/change-flags/scan/{version}")
async def scan_flags(
    version: str, _admin: dict[str, Any] = Depends(require_admin)
) -> dict[str, Any]:
    """Run ALL flag analyses: lifecycle-vs-delivery contradictions (G6), the decay analysis
    (subcaps missing vs the previous version), and unscoped-subvertical discovery (clients
    delivering outside the nine subverticals) — each gated and explained, nothing auto-acted."""
    contradiction = await flags_svc.scan(version)
    decay = await flags_svc.scan_decay(version)
    unscoped = await subverticals_svc.detect_unscoped_subverticals(version)
    return {
        "version": version,
        "created": int(contradiction["created"]) + int(decay["created"]) + int(unscoped["created"]),
        "candidates": int(contradiction["candidates"])
        + int(decay["candidates"])
        + int(unscoped["candidates"]),
        "contradiction": contradiction,
        "decay": decay,
        "unscoped_subverticals": unscoped,
    }


@router.post("/admin/change-flags/scan-subverticals/{version}")
async def scan_subverticals(
    version: str, _admin: dict[str, Any] = Depends(require_admin)
) -> dict[str, Any]:
    """Unscoped-subvertical discovery on its own: cluster real-Jira delivery from clients outside
    the nine modelled subverticals, infer + gate a candidate new subvertical for each (volume-
    stratified, overlap-guarded), and queue it in the Change-Flags / Notifications inbox."""
    return await subverticals_svc.detect_unscoped_subverticals(version)


@router.post("/admin/kg/propose/{version}")
async def propose_kg_edges(
    version: str, _admin: dict[str, Any] = Depends(require_admin)
) -> dict[str, Any]:
    """Knowledge-graph Layer-B structural discovery: propose dashed ``pending_edge``s between
    cross-capability subcaps that co-occur structurally (shared L3 platforms / personas), each
    gated G1-G8 and queued in the Change-Flags inbox for human approval — never written live."""
    return await kg_svc.propose_structural_edges(version)


@router.post("/admin/kg/directional/{version}")
async def propose_kg_directional(
    version: str, _admin: dict[str, Any] = Depends(require_admin)
) -> dict[str, Any]:
    """R6 NLP DIRECTIONAL relationship discovery: read the connected cross-capability subcap pairs'
    DESCRIPTIONS into a typed, directional relation (one enables/precedes/depends_on/affects the
    other), DUAL-verify each (adversarial refutation + Jira-corpus corroboration), and queue the
    survivors as gated, dashed directional ``pending_edge``s in the Change-Flags inbox for human
    approval — never written live. Live spend (enrich + adversarial models), metered + G8-gated;
    hermetic = deterministic, zero spend."""
    return await kg_svc.propose_directional_edges(version)


@router.post("/admin/use-case-gaps/{version}")
async def detect_use_case_gaps(
    version: str, _admin: dict[str, Any] = Depends(require_admin)
) -> dict[str, Any]:
    """Use-case gap detection: for each subcap, cluster the carried real-Jira stories its EXISTING
    use cases do not cover, overlap-guard each cluster against those use cases (strict, to avoid
    bloat), infer + gate a candidate NEW use case for each survivor, and queue it in the
    Change-Flags inbox for human approval — never written to the catalogue live (approve re-gates
    and inserts it into cat_<v>)."""
    return await use_case_gaps_svc.detect_use_case_gaps(version)


@router.post("/admin/embeddings/build/{version}")
async def build_embeddings(
    version: str, _admin: dict[str, Any] = Depends(require_admin)
) -> dict[str, Any]:
    """Populate the shared vector(768) embedding space for the version (F6): embed every subcap that
    has none yet, idempotent + metered. Hermetic = no spend; live spend is governed by the G8 cost
    envelope. Unlocks dense retrieval + the semantic KG Layer-B."""
    return await embeddings_svc.build_embeddings(version)


@router.post("/admin/offerings/match/{version}")
async def match_offerings(
    version: str, _admin: dict[str, Any] = Depends(require_admin)
) -> dict[str, Any]:
    """Rebuild the productized-offering -> subcap matches for the version BY MEANING (F6): each
    offering's named capabilities are hybrid-matched (dense embedding cosine + lexical) across the
    catalogue, gated + bounded, replacing the deterministic seed with scored, doc-grounded matches.
    Hermetic = no spend; live spend is governed by the G8 cost envelope."""
    from app.services import offerings_match as offerings_svc

    return await offerings_svc.match_offerings(version)


@router.post("/change-flags/{flag_id}/approve")
async def approve_flag(
    flag_id: UUID, user: dict[str, Any] = Depends(get_current_user)
) -> FlagActionOut:
    result = await flags_svc.approve(str(flag_id), str(user["uid"]))
    if result.status == "not_found":
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="change flag not found")
    return FlagActionOut(**vars(result))


@router.post("/change-flags/{flag_id}/reject")
async def reject_flag(
    flag_id: UUID, body: FlagRejectBody, user: dict[str, Any] = Depends(get_current_user)
) -> FlagActionOut:
    if not body.reason.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="a rejection reason is required")
    result = await flags_svc.reject(str(flag_id), body.reason, str(user["uid"]))
    if result.status == "not_found":
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="change flag not found")
    return FlagActionOut(**vars(result))


@router.post("/change-flags/{flag_id}/defer")
async def defer_flag(
    flag_id: UUID, user: dict[str, Any] = Depends(get_current_user)
) -> FlagActionOut:
    result = await flags_svc.defer(str(flag_id), str(user["uid"]))
    if result.status == "not_found":
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="change flag not found")
    return FlagActionOut(**vars(result))
