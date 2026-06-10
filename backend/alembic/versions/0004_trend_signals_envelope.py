"""trend signal breakdown + trust envelope (D2)

The reference DDL's control.trend is minimal (label/status/window/count). Trends monitor (D2,
spec §18.1) needs the per-trend signal breakdown the card renders (velocity/diversity/novelty/
persistence), the composite score, and the trust envelope every AI-derived value carries
(claim_label · source_tier · ers · reasoning-chain backlink). Stored as columns on control.trend:
``signals`` jsonb keeps the four sub-scores decomposable; ``novelty`` is lifted out for the
emergent test/sort; ``chain_id`` is the reasoning backlink (FK, guarded so the job is re-runnable).
Additive and reversible (expand-only); applied before the new revision takes traffic.

Revision ID: 0004_trend_signals_envelope
Revises: 0003_evidence_source_attrs
Create Date: 2026-06-10
"""

from __future__ import annotations

from alembic import op

revision: str = "0004_trend_signals_envelope"
down_revision: str | None = "0003_evidence_source_attrs"
branch_labels: str | None = None
depends_on: str | None = None

# claim_label + source_tier enums already exist (control baseline); reuse them for the envelope.
_ADD_COLS = (
    ("trend", "signals", "jsonb"),
    ("trend", "score", "numeric(4,3)"),
    ("trend", "novelty", "numeric(4,3)"),
    ("trend", "claim_label", "claim_label"),
    ("trend", "source_tier", "source_tier"),
    ("trend", "ers", "numeric(4,3)"),
    ("trend", "chain_id", "uuid"),
)


def upgrade() -> None:
    for table, col, typ in _ADD_COLS:
        op.execute(f"ALTER TABLE control.{table} ADD COLUMN IF NOT EXISTS {col} {typ}")
    # Reasoning backlink FK (guarded against duplicate so the migration stays re-runnable).
    op.execute(
        "DO $$ BEGIN "
        "ALTER TABLE control.trend ADD CONSTRAINT trend_chain_fk "
        "FOREIGN KEY (chain_id) REFERENCES control.reasoning_chain(chain_id); "
        "EXCEPTION WHEN duplicate_object THEN NULL; END $$"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE control.trend DROP CONSTRAINT IF EXISTS trend_chain_fk")
    for table, col, _typ in reversed(_ADD_COLS):
        op.execute(f"ALTER TABLE control.{table} DROP COLUMN IF EXISTS {col}")
