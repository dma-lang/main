"""per-subvertical rollups (R8)

Precomputes per-(entity x subvertical) delivery rollups so a subcap / use case can be shown TAILORED
to the subvertical being viewed: the representative stories + a synthesized narrative are drawn from
that subvertical's own delivery, falling back to an all-SV canonical row (subvertical = '') when no
lens is set. One table, two grains (entity_kind = 'subcap' | 'use_case'), rebuilt idempotently in
carry_forward. Additive + reversible (expand-only); the migration job applies it before the new
revision takes traffic.

Revision ID: 0020_sv_rollup
Revises: 0019_story_synthesis_cache
Create Date: 2026-07-01
"""

from __future__ import annotations

from alembic import op

revision: str = "0020_sv_rollup"
down_revision: str | None = "0019_story_synthesis_cache"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute(
        "CREATE TABLE IF NOT EXISTS control.sv_rollup ("
        "  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),"
        "  version_id text NOT NULL,"
        "  entity_kind text NOT NULL,"  # 'subcap' | 'use_case'
        "  entity_id text NOT NULL,"
        "  subvertical text NOT NULL DEFAULT '',"  # '' = the all-SV canonical rollup (the fallback)
        "  story_count int NOT NULL DEFAULT 0,"
        "  client_count int NOT NULL DEFAULT 0,"
        "  rep_story_keys jsonb NOT NULL DEFAULT '[]',"
        "  narrative text,"
        "  built_at timestamptz NOT NULL DEFAULT now(),"
        "  UNIQUE (version_id, entity_kind, entity_id, subvertical))"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_sv_rollup_lookup "
        "ON control.sv_rollup (version_id, entity_kind, entity_id, subvertical)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS control.sv_rollup")
