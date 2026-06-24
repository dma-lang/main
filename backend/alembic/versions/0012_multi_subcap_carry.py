"""story_subcap_carry allows one story to evidence SEVERAL subcaps (catalogue refs)

The v7 Capability Map sheet carries a `Story_Refs_with_UC_Links` column: per subcap, the REAL
Jira stories the catalogue authors mapped to it. 94% of those keys resolve to the canonical
14,406-row corpus, and the same story legitimately evidences multiple subcaps — so the unique key
widens from (story_key, target_version) to (story_key, target_version, carried_to_subcap). The
corpus pass still writes exactly one row per story; the catalogue-ref pass adds the additional
subcap links (via='catalogue_ref').

Revision ID: 0012_multi_subcap_carry
Revises: 0011_jira_only_analysis_view
Create Date: 2026-06-11
"""

from __future__ import annotations

from alembic import op

revision: str = "0012_multi_subcap_carry"
down_revision: str | None = "0011_jira_only_analysis_view"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE control.story_subcap_carry "
        "DROP CONSTRAINT IF EXISTS story_subcap_carry_story_key_target_version_key"
    )
    op.execute(
        "ALTER TABLE control.story_subcap_carry "
        "ADD CONSTRAINT story_subcap_carry_story_version_subcap_key "
        "UNIQUE (story_key, target_version, carried_to_subcap)"
    )


def downgrade() -> None:
    # the 2-col key cannot hold multi-links: drop the catalogue-ref rows first (they are
    # re-derivable from the seed on the next carry), then restore the original constraint.
    op.execute("DELETE FROM control.story_subcap_carry WHERE via = 'catalogue_ref'")
    op.execute(
        "ALTER TABLE control.story_subcap_carry "
        "DROP CONSTRAINT IF EXISTS story_subcap_carry_story_version_subcap_key"
    )
    op.execute(
        "ALTER TABLE control.story_subcap_carry "
        "ADD CONSTRAINT story_subcap_carry_story_key_target_version_key "
        "UNIQUE (story_key, target_version)"
    )
