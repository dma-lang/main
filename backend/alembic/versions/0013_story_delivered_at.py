"""story delivery date (A3 — value-chain Rollup quarter trend)

Adds a nullable real-delivery timestamp to control.story so the value-chain Rollup can bin stories
into a per-stage quarter trend. The canonical Jira corpus carries NO date today, so the column stays
NULL until a dated export is ingested (the loader populates it when a date is present); we never
synthesize one (grounded-only safeguard), and the Rollup hides the sparkline while it is empty.
Additive, reversible (expand-only); applied by the migration job before the revision takes traffic.

Revision ID: 0013_story_delivered_at
Revises: 0012_multi_subcap_carry
Create Date: 2026-06-25
"""

from __future__ import annotations

from alembic import op

revision: str = "0013_story_delivered_at"
down_revision: str | None = "0012_multi_subcap_carry"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE control.story ADD COLUMN IF NOT EXISTS delivered_at timestamptz")


def downgrade() -> None:
    op.execute("ALTER TABLE control.story DROP COLUMN IF EXISTS delivered_at")
