"""story synthesis cache (R8)

Backs the §10-gated LIVE deep-synthesis upgrade: when the live Gemini path is enabled it caches each
synthesized narrative on the source text's content hash (structural clone of control.enrichment_
relevance / migration 0016), so a re-provision reuses the decision with no repeat spend. The
DETERMINISTIC path (the default, hermetic) never touches this table — it is always recomputable and
free. Additive + reversible (expand-only); the migration job applies it before the new revision
takes traffic.

Revision ID: 0019_story_synthesis_cache
Revises: 0018_story_synthesis
Create Date: 2026-07-01
"""

from __future__ import annotations

from alembic import op

revision: str = "0019_story_synthesis_cache"
down_revision: str | None = "0018_story_synthesis"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute(
        "CREATE TABLE IF NOT EXISTS control.story_synthesis ("
        "  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),"
        "  kind text NOT NULL,"  # 'story' | 'use_case' | 'subcap_sv' | ...
        "  subject_key text NOT NULL,"  # story_key / use_case_id / (entity:sv)
        "  content_hash text NOT NULL,"
        "  narrative text NOT NULL,"
        "  facets jsonb,"
        "  model text NOT NULL,"
        "  cost_usd numeric NOT NULL DEFAULT 0,"
        "  decided_at timestamptz NOT NULL DEFAULT now(),"
        "  UNIQUE (kind, subject_key, content_hash))"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS control.story_synthesis")
