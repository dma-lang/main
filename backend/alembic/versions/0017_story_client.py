"""story client identity (R8)

Adds the resolved CLIENT identity to control.story so a story carries a real client name (separate
from its story_key), not just a project_key proxy: client_name + the Salesforce account id and the
match method/confidence that resolved it (all from the authoritative story catalog). The narrative
text columns (description / ac_text / solution_design_text) already exist in the baseline and are
now populated for real stories by the richer seed. Additive + reversible (expand-only); the job
applies it before the new revision takes traffic.

Revision ID: 0017_story_client
Revises: 0016_enrichment_relevance
Create Date: 2026-07-01
"""

from __future__ import annotations

from alembic import op

revision: str = "0017_story_client"
down_revision: str | None = "0016_enrichment_relevance"
branch_labels: str | None = None
depends_on: str | None = None

_COLS = (
    "client_name",
    "salesforce_account_id",
    "client_match_method",
    "client_match_confidence",
)


def upgrade() -> None:
    for col in _COLS:
        op.execute(f"ALTER TABLE control.story ADD COLUMN IF NOT EXISTS {col} text")
    op.execute("CREATE INDEX IF NOT EXISTS ix_story_client_name ON control.story (client_name)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS control.ix_story_client_name")
    for col in _COLS:
        op.execute(f"ALTER TABLE control.story DROP COLUMN IF EXISTS {col}")
