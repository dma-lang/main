"""story_use_case_link — match the delivered Jira stories to the catalogue's USE CASES

Carry-forward (F5) maps each Jira story to a SUBCAP only, so every use case under a subcap shows
that subcap's full delivery — the "static number" on the Use Case Explorer. This adds the missing
story↔use-case grain: a deterministic matcher (services/use_case_match) scores each carried story
against its subcap's use cases and writes the best match here, so per-use-case delivery is REAL
(the counts partition the subcap's stories across its use cases) and the drawer can show a use
case's own matched stories.

Mirrors story_subcap_carry / story_catalogue_link exactly: a carry table with a confidence status,
and a status-filtered view the reads join. Re-derivable from the seed on the next carry, so the
downgrade simply drops it.

Revision ID: 0013_story_use_case_link
Revises: 0012_multi_subcap_carry
Create Date: 2026-06-30
"""

from __future__ import annotations

from alembic import op

revision: str = "0013_story_use_case_link"
down_revision: str | None = "0012_multi_subcap_carry"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute(
        "CREATE TABLE IF NOT EXISTS control.story_use_case_carry ("
        "  link_id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),"
        "  story_key      text NOT NULL REFERENCES control.story(story_key) ON DELETE CASCADE,"
        "  target_version text NOT NULL,"
        "  use_case_id    text NOT NULL,"
        "  subcap_id      text NOT NULL,"
        "  score          numeric(5,4),"
        "  via            text NOT NULL,"
        "  status         carry_status NOT NULL DEFAULT 'confirmed',"
        "  created_at     timestamptz NOT NULL DEFAULT now(),"
        "  UNIQUE (story_key, target_version, use_case_id)"
        ")"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_story_uc_target "
        "ON control.story_use_case_carry (target_version, status)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_story_uc_use_case "
        "ON control.story_use_case_carry (target_version, use_case_id)"
    )
    op.execute(
        "CREATE OR REPLACE VIEW control.story_use_case_link AS "
        "SELECT story_key, target_version AS version_id, use_case_id, subcap_id, "
        "score, via, status "
        "FROM control.story_use_case_carry "
        "WHERE status IN ('confirmed', 'review')"
    )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS control.story_use_case_link")
    op.execute("DROP TABLE IF EXISTS control.story_use_case_carry")
