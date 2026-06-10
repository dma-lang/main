"""Source registry (Settings · admin) — the app's ingestion points as persisted configuration.

One row per source the F7 pipelines pull from (control.ingest_source, seeded by migration 0006):
its trust tier, BOTH origins — the recorded fixture hermetic runs replay from the database and the
online origin live mode calls — and the persisted ``enabled`` switch. The read model composes the
registry with config/schedules.yaml (cadence + next run) and control.ingest_run (last run + stats)
so a stale or erroring source shows its last poll — warned, never hidden. Which origin is ACTIVE
is decided by LLM_MODE (the global hermetic switch): the app always knows whether it is picking
from the database or from the online source, and says so.

``ensure_enabled`` is the write-path guard: every scan job checks it before fetching, so a source
disabled here is configuration that actually holds — not decoration.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app import db
from app.jobs import schedule
from app.settings import get_settings

# source_key -> schedules.yaml entry (sow has no cron: it ingests on admin upload).
_SCHEDULE_KEY = {
    "jira": "jira_ingest",
    "news": "news_scan",
    "trends": "trend_detect",
    "benchmarks": "benchmark_scan",
    "vendor": "vendor_scan",
}

# Staleness window per cadence: ~2 missed periods means the watchdog should have re-enqueued the
# job — surface the warning ("stale/erroring source -> warning + last-poll shown, not hidden").
_MAX_AGE = {
    "hourly": timedelta(hours=2),
    "daily": timedelta(days=2),
    "weekly": timedelta(days=8),
    "monthly": timedelta(days=32),
}


@dataclass
class SourceRow:
    key: str
    name: str
    type: str
    tier: str
    enabled: bool
    mode: str  # recorded | live — which origin the app is picking from right now
    origin_active: str
    origin_recorded: str
    origin_live: str
    cadence: str  # hourly | weekly | monthly | on-upload
    cron: str | None
    next_run: str | None
    last_run: str | None
    last_status: str | None
    last_stats: dict[str, Any]
    status: str  # ok | stale | never_run | disabled
    notes: str


def _cadence(cron: str) -> str:
    minute, hour, dom, _month, dow = cron.split()
    if hour == "*":
        return "hourly"
    if dow != "*":
        return "weekly"
    if dom != "*":
        return "monthly"
    return "daily"


async def _last_run(conn: AsyncConnection, key: str) -> dict[str, Any] | None:
    row = (
        (
            await conn.execute(
                text(
                    "SELECT finished_at, status, stats FROM control.ingest_run "
                    "WHERE source = :s AND finished_at IS NOT NULL "
                    "ORDER BY finished_at DESC LIMIT 1"
                ),
                {"s": key},
            )
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


async def list_sources() -> list[SourceRow]:
    """The Settings source registry: every ingestion point with its active origin (database
    fixture vs online), cadence, last poll and staleness — nothing hidden."""
    engine = db.get_engine()
    if engine is None:
        raise RuntimeError("database not initialised")
    hermetic = get_settings().is_hermetic
    now = datetime.now(UTC)

    async with engine.connect() as conn:
        rows = (
            (
                await conn.execute(
                    text(
                        "SELECT source_key, name, source_type::text AS stype, tier::text AS tier,"
                        " origin_recorded, origin_live, enabled, coalesce(notes, '') AS notes "
                        "FROM control.ingest_source ORDER BY source_key"
                    )
                )
            )
            .mappings()
            .all()
        )
        out: list[SourceRow] = []
        for r in rows:
            key = r["source_key"]
            sched_key = _SCHEDULE_KEY.get(key)
            cron = next_run = None
            cadence = "on-upload"
            if sched_key:
                entry = schedule.describe(sched_key)
                cron, next_run = entry["cron"], entry["next_run"]
                cadence = _cadence(cron)
            last = await _last_run(conn, key)
            last_at: datetime | None = last["finished_at"] if last else None
            if not r["enabled"]:
                status = "disabled"
            elif last_at is None:
                status = "never_run"
            elif cadence in _MAX_AGE and now - last_at > _MAX_AGE[cadence]:
                status = "stale"
            else:
                status = "ok"
            out.append(
                SourceRow(
                    key=key,
                    name=r["name"],
                    type=r["stype"],
                    tier=r["tier"],
                    enabled=bool(r["enabled"]),
                    mode="recorded" if hermetic else "live",
                    origin_active=r["origin_recorded"] if hermetic else r["origin_live"],
                    origin_recorded=r["origin_recorded"],
                    origin_live=r["origin_live"],
                    cadence=cadence,
                    cron=cron,
                    next_run=next_run,
                    last_run=last_at.isoformat() if last_at else None,
                    last_status=last["status"] if last else None,
                    last_stats=dict(last["stats"] or {}) if last else {},
                    status=status,
                    notes=r["notes"],
                )
            )
    return out


async def set_enabled(key: str, enabled: bool, actor: str) -> dict[str, Any]:
    """Persist the per-source switch (+ append-only audit row). The scan jobs enforce it via
    ``ensure_enabled`` — disabling a source here actually stops its ingest."""
    engine = db.get_engine()
    if engine is None:
        raise RuntimeError("database not initialised")
    async with engine.begin() as conn:
        updated = (
            await conn.execute(
                text(
                    "UPDATE control.ingest_source SET enabled = :e, updated_at = now() "
                    "WHERE source_key = :k RETURNING source_key"
                ),
                {"e": enabled, "k": key},
            )
        ).first()
        if updated is None:
            return {"ok": False, "status": "not_found"}
        await conn.execute(
            text(
                "INSERT INTO control.audit_log (actor, action, target_ref, meta) "
                "VALUES ((SELECT uid FROM control.users WHERE uid = :a), :act, :ref, "
                "CAST(:m AS jsonb))"
            ),
            {
                "a": actor,
                "act": "source_" + ("enabled" if enabled else "disabled"),
                "ref": f"source:{key}",
                "m": json.dumps({"enabled": enabled}),
            },
        )
    return {"ok": True, "key": key, "enabled": enabled}


class SourceDisabledError(RuntimeError):
    """Raised when a scan is invoked on a registry-disabled source (rendered as HTTP 409)."""


async def ensure_enabled(conn: AsyncConnection, key: str) -> None:
    """Write-path guard for the scan jobs: a disabled source refuses to ingest, loudly."""
    enabled = (
        await conn.execute(
            text("SELECT enabled FROM control.ingest_source WHERE source_key = :k"), {"k": key}
        )
    ).scalar()
    if enabled is False:
        raise SourceDisabledError(
            f"source '{key}' is disabled in the source registry — enable it in Settings to scan"
        )
