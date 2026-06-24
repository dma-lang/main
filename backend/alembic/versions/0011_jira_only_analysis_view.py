"""story_catalogue_link excludes synthetic stories (analysis is Jira-only)

The v7 workbooks ship ~4.5k SYNTHETIC stories (gen_stories_v1 / gen_synthesized_gap_fill /
use_case_derived_public_validated) alongside the real 14,406-row Jira corpus. Per the decision
"synthetic excluded unless trend-flagged" — and the direction that the JIRA stories are what
analysis uses — the analysis-grade view now joins control.story and filters is_synthetic, so
every consumer (heatmap, subcap counts, lifecycle, trace, clients, platforms, G6 delivery
contradiction) is Jira-only by construction. The story library reads control.story directly and
keeps synthetic rows visible behind an explicit, labelled filter.

Revision ID: 0011_jira_only_analysis_view
Revises: 0010_sow_tables
Create Date: 2026-06-10
"""

from __future__ import annotations

from alembic import op

revision: str = "0011_jira_only_analysis_view"
down_revision: str | None = "0010_sow_tables"
branch_labels: str | None = None
depends_on: str | None = None

_NEW = """
CREATE OR REPLACE VIEW control.story_catalogue_link AS
SELECT c.story_key,
       c.target_version AS version_id,
       c.carried_to_subcap AS subcap_id,
       c.similarity,
       c.via,
       c.status
  FROM control.story_subcap_carry c
  JOIN control.story s ON s.story_key = c.story_key
 WHERE c.status = ANY (ARRAY['confirmed'::carry_status, 'review'::carry_status])
   AND c.carried_to_subcap IS NOT NULL
   AND NOT s.is_synthetic
"""

_OLD = """
CREATE OR REPLACE VIEW control.story_catalogue_link AS
SELECT story_key,
       target_version AS version_id,
       carried_to_subcap AS subcap_id,
       similarity,
       via,
       status
  FROM control.story_subcap_carry
 WHERE status = ANY (ARRAY['confirmed'::carry_status, 'review'::carry_status])
   AND carried_to_subcap IS NOT NULL
"""


def upgrade() -> None:
    op.execute(_NEW)


def downgrade() -> None:
    op.execute(_OLD)
