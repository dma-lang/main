"""vendor impact score (F2)

The per-subcap impact score on vendor_subcap_impact, mirroring 0003's news_subcap_impact.score:
the heatmap multiplies it by recency_weight (frequency x recency, never the static platform
join). Additive and reversible.

Revision ID: 0007_vendor_impact_score
Revises: 0006_ingest_source_registry
Create Date: 2026-06-10
"""

from __future__ import annotations

from alembic import op

revision: str = "0007_vendor_impact_score"
down_revision: str | None = "0006_ingest_source_registry"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE control.vendor_subcap_impact ADD COLUMN IF NOT EXISTS score numeric(4,3)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE control.vendor_subcap_impact DROP COLUMN IF EXISTS score")
