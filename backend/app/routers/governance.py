"""Validation gates log (G4) + QA & audit (G5) — read-only transparency over the trust layer.

/api/gates aggregates the per-gate pass/fail distribution from validation_gate_run; /api/qa/metrics
reports the real gate pass-rate + reasoning-chain count + spend (admin-gated, $0 hermetic) with
honest nulls where the F6 eval / F11 meter are not wired; /api/audit-log is the append-only record
of every gated mutation.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import text

from app import db
from app.deps import get_current_user

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
        total = (
            await conn.execute(text("SELECT count(*) FROM control.validation_gate_run"))
        ).scalar() or 0
        passed = (
            await conn.execute(
                text("SELECT count(*) FROM control.validation_gate_run WHERE verdict = 'pass'")
            )
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
