"""kg_edge.relation / .direction (+ pending_edge) — carry a DIRECTIONAL, NLP-inferred relationship

R6 upgrades the knowledge graph from symmetric structural/co-occurrence edges to NLP-inferred
DIRECTIONAL relationships read from the two subcaps' descriptions ("A enables B", "A precedes B",
"A depends_on B", …). A directional edge needs two extra facts the symmetric edge never carried:

  * ``relation``  — the typed relationship (enables / depends_on / precedes / affects /
                    complements / alternative_to / subsumes). NULL on the legacy structural edges.
  * ``direction`` — how the relation flows over (from_node, to_node): ``forward`` (from_node is the
                    source that enables/precedes/affects to_node) or ``bidirectional`` (a symmetric
                    relation like complements / alternative_to). NULL on legacy edges.

Both are nullable + additive (expand-only, safeguard 5): existing rows keep working (the endpoint
falls back to ``kind`` / undirected when ``relation`` is NULL), and the downgrade drops the columns.
The rich "why" (rationale, keywords, verification verdict) rides on the existing ``detail jsonb``
(migration 0014); ``promote_pending_edge`` already copies ``detail`` and now also the two columns.

Revision ID: 0015_kg_edge_directional
Revises: 0014_kg_edge_detail
Create Date: 2026-07-01
"""

from __future__ import annotations

from alembic import op

revision: str = "0015_kg_edge_directional"
down_revision: str | None = "0014_kg_edge_detail"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE control.pending_edge ADD COLUMN IF NOT EXISTS relation text")
    op.execute("ALTER TABLE control.pending_edge ADD COLUMN IF NOT EXISTS direction text")
    op.execute("ALTER TABLE control.kg_edge ADD COLUMN IF NOT EXISTS relation text")
    op.execute("ALTER TABLE control.kg_edge ADD COLUMN IF NOT EXISTS direction text")


def downgrade() -> None:
    op.execute("ALTER TABLE control.kg_edge DROP COLUMN IF EXISTS direction")
    op.execute("ALTER TABLE control.kg_edge DROP COLUMN IF EXISTS relation")
    op.execute("ALTER TABLE control.pending_edge DROP COLUMN IF EXISTS direction")
    op.execute("ALTER TABLE control.pending_edge DROP COLUMN IF EXISTS relation")
