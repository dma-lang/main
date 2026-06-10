"""story sub-scores (F5)

Adds the graded acceptance-criteria / solution-design / story sub-scores to control.story. These are
distinct from the binary ac_quality / sd_quality flags already in the baseline and back the Story
library drilldown (ac/sd/ss). Additive and reversible (expand-only); the migration job applies it
before the new revision takes traffic.

Revision ID: 0002_story_subscores
Revises: 0001_control_baseline
Create Date: 2026-06-09
"""

from __future__ import annotations

from alembic import op

revision: str = "0002_story_subscores"
down_revision: str | None = "0001_control_baseline"
branch_labels: str | None = None
depends_on: str | None = None

_COLS = ("ac_score", "sd_score", "story_score")


def upgrade() -> None:
    for col in _COLS:
        op.execute(f"ALTER TABLE control.story ADD COLUMN IF NOT EXISTS {col} numeric")


def downgrade() -> None:
    for col in _COLS:
        op.execute(f"ALTER TABLE control.story DROP COLUMN IF EXISTS {col}")
