"""control.enrichment_relevance — the persistent cache behind the deep-NLP necessity gate (R7)

R7 propagates an approved enrichment (a new use case first) to EVERY version where it belongs, and
retrofits the wholesale provision-time inheritance with the same "does this enrichment truly belong
in this version?" check — weighed DEEPLY with NLP (``Gemini.infer_relevance``). A base-only version
inherits thousands of use cases, so a fresh live judgment per (enrichment, target subcap) on every
re-provision would be unbounded spend. This table makes the gate IDEMPOTENT + budget-safe, exactly
like the deploy build-marker: a decided verdict is keyed on the enrichment's CONTENT hash, so the
same content re-uses the cached decision (zero repeat spend); only genuinely-new content pays the
model. Expand-only + reversible (safeguard 5); nothing here is a secret.

Revision ID: 0016_enrichment_relevance
Revises: 0015_kg_edge_directional
Create Date: 2026-07-01
"""

from __future__ import annotations

from alembic import op

revision: str = "0016_enrichment_relevance"
down_revision: str | None = "0015_kg_edge_directional"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute(
        "CREATE TABLE IF NOT EXISTS control.enrichment_relevance ("
        "  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),"
        "  kind text NOT NULL,"  # 'use_case' | future enrichment kinds
        "  enrichment_key text NOT NULL,"  # stable id of the source enrichment
        "  target_version text NOT NULL,"
        "  target_subcap text NOT NULL,"
        "  content_hash text NOT NULL,"  # hash of the enrichment text -> cache invalidation on edit
        "  relevant boolean NOT NULL,"
        "  confidence numeric(4,3),"
        "  rationale text,"
        "  model text,"
        "  cost_usd numeric(10,6) NOT NULL DEFAULT 0,"
        "  decided_at timestamptz NOT NULL DEFAULT now(),"
        "  UNIQUE (kind, enrichment_key, target_version, target_subcap, content_hash)"
        ")"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS control.enrichment_relevance")
