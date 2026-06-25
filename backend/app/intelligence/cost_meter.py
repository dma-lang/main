"""Cost meter + G8 monthly-envelope guard (CLAUDE.md safeguard 8).

Every live model call's ``cost_usd`` is already persisted on the ``reasoning_chain`` it produced
(chat, subvertical naming, the embeddings batch, …), so that table IS the spend ledger — no extra
bookkeeping table. This module sums the current calendar month against the envelope in
``config/models.yaml::cost`` and reports alert (≥80%) / throttle (≥90%). The live wrapper consults
``over_throttle`` BEFORE a paid call and degrades to the hermetic stub when the budget is spent —
nothing crashes, and the meter feeds the QA dashboard's spend panel.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

from app import db
from app.intelligence import model_config

_SPEND_SQL = (
    "SELECT coalesce(sum(cost_usd), 0) FROM control.reasoning_chain "
    "WHERE created_at >= date_trunc('month', now())"
)


async def spend_this_month() -> float:
    """Total ``cost_usd`` recorded across all reasoning chains this calendar month (USD)."""
    engine = db.get_engine()
    if engine is None:
        return 0.0
    async with engine.connect() as conn:
        val = (await conn.execute(text(_SPEND_SQL))).scalar()
    return float(val or 0.0)


async def status() -> dict[str, Any]:
    """Spend vs the envelope: ``{spend, envelope, pct, alert, throttle, alert_at, throttle_at}``."""
    envelope, alert_at, throttle_at = model_config.cost_envelope()
    spend = await spend_this_month()
    pct = (spend / envelope * 100.0) if envelope > 0 else 0.0
    return {
        "spend": round(spend, 4),
        "envelope": envelope,
        "pct": round(pct, 2),
        "alert": pct >= alert_at,
        "throttle": pct >= throttle_at,
        "alert_at": alert_at,
        "throttle_at": throttle_at,
    }


async def over_throttle() -> bool:
    """True once the month's spend has reached the throttle threshold — stop paid work, degrade."""
    envelope, _, throttle_at = model_config.cost_envelope()
    if envelope <= 0:
        return False
    spend = await spend_this_month()
    return (spend / envelope * 100.0) >= throttle_at
