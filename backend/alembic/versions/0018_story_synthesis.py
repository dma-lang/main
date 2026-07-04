"""story synthesized narrative + facets (R8)

Adds the deterministic story-synthesis output to control.story: a cohesive plain-language
``narrative`` (woven from the story's own summary / description / acceptance criteria / solution
design) and the structured ``facets`` (role / goal / benefit / acceptance outcomes / solution
approach) behind it. Precomputed at ingest by services/story_synthesis (idempotent gap-fill), so
every surface renders WHAT was delivered and HOW, not just a one-line summary + score bars.
Additive + reversible (expand-only); the migration job applies it before the new revision takes
traffic.

Revision ID: 0018_story_synthesis
Revises: 0017_story_client
Create Date: 2026-07-01
"""

from __future__ import annotations

from alembic import op

revision: str = "0018_story_synthesis"
down_revision: str | None = "0017_story_client"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE control.story ADD COLUMN IF NOT EXISTS narrative text")
    op.execute("ALTER TABLE control.story ADD COLUMN IF NOT EXISTS facets jsonb")


def downgrade() -> None:
    op.execute("ALTER TABLE control.story DROP COLUMN IF EXISTS facets")
    op.execute("ALTER TABLE control.story DROP COLUMN IF EXISTS narrative")
