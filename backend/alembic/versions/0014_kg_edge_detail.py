"""kg_edge.detail — carry an accepted edge's basis so the graph can explain "why related"

The KG enrichment (R5) adds explained, weighted relationships (co-delivery lift, shared offering,
semantic cosine). A pending_edge already carries its basis in the change_flag detail, but once a
human approves it and it is promoted to a ``kg_edge`` that basis was lost — the read had nothing to
show on an accepted edge. This adds a ``detail jsonb`` (the compact basis: relation kind, the
human phrase, the strength), populated on promotion, so every Layer-B edge can render its "why".

Expand-only on the control plane; existing edges default to ``{}`` (the read falls back to deriving
the basis from the edge kind + weight).

Revision ID: 0014_kg_edge_detail
Revises: 0013_story_use_case_link
Create Date: 2026-06-30
"""

from __future__ import annotations

from alembic import op

revision: str = "0014_kg_edge_detail"
down_revision: str | None = "0013_story_use_case_link"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE control.kg_edge " "ADD COLUMN IF NOT EXISTS detail jsonb NOT NULL DEFAULT '{}'"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE control.kg_edge DROP COLUMN IF EXISTS detail")
