"""kg_edge.detail / pending_edge.detail — carry the "why" on a knowledge-graph edge

R5 gives every inferred KG edge a rich basis ("co-delivered in 30 projects, lift 5.2"; "cosine
0.91 in the shared embedding space"), a unified strength, and its cross-capability / cross-pillar
reach. That envelope lives on the change_flag today, but a pending_edge PROMOTED to a kg_edge would
lose it, so an accepted edge could no longer explain itself. This adds an expand-only
``detail jsonb`` to both control.pending_edge and control.kg_edge; promote_pending_edge copies it
across, so a confirmed Layer-B edge still shows its "why". Nullable + additive — the downgrade drops
the columns and existing rows keep working (the endpoint falls back to weight/kind).

Revision ID: 0014_kg_edge_detail
Revises: 0013_story_use_case_link
Create Date: 2026-07-01
"""

from __future__ import annotations

from alembic import op

revision: str = "0014_kg_edge_detail"
down_revision: str | None = "0013_story_use_case_link"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE control.pending_edge ADD COLUMN IF NOT EXISTS detail jsonb")
    op.execute("ALTER TABLE control.kg_edge ADD COLUMN IF NOT EXISTS detail jsonb")


def downgrade() -> None:
    op.execute("ALTER TABLE control.kg_edge DROP COLUMN IF EXISTS detail")
    op.execute("ALTER TABLE control.pending_edge DROP COLUMN IF EXISTS detail")
