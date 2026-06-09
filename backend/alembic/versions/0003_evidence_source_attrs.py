"""evidence source attributes (F7)

The surfaceable source sub-object + expected-catalogue-impact class the News watch (D1) renders
(spec R5/R6): two enums the reference DDL omits (plan: "schema additions"), the evidence_item
columns carrying {source_name, source_type, catalogue_impact, impact_note}, and the per-subcap
impact score on news_subcap_impact. Additive and reversible (expand-only); the migration job
applies it before the new revision takes traffic.

Revision ID: 0003_evidence_source_attrs
Revises: 0002_story_subscores
Create Date: 2026-06-09
"""

from __future__ import annotations

from alembic import op

revision: str = "0003_evidence_source_attrs"
down_revision: str | None = "0002_story_subscores"
branch_labels: str | None = None
depends_on: str | None = None

_IMPACTS = "'descriptor_revision','new_use_case','net_new_subcap','retire_candidate','watchlist'"
_SOURCES = "'regulator','analyst','vendor','trade_press','peer','benchmark'"

_ADD_COLS = (
    ("evidence_item", "source_name", "text"),
    ("evidence_item", "source_type", "source_type"),
    ("evidence_item", "catalogue_impact", "catalogue_impact"),
    ("evidence_item", "impact_note", "text"),
    ("news_subcap_impact", "score", "numeric(4,3)"),
)


def upgrade() -> None:
    op.execute(
        "DO $$ BEGIN "
        f"CREATE TYPE catalogue_impact AS ENUM ({_IMPACTS}); "
        "EXCEPTION WHEN duplicate_object THEN NULL; END $$"
    )
    op.execute(
        "DO $$ BEGIN "
        f"CREATE TYPE source_type AS ENUM ({_SOURCES}); "
        "EXCEPTION WHEN duplicate_object THEN NULL; END $$"
    )
    for table, col, typ in _ADD_COLS:
        op.execute(f"ALTER TABLE control.{table} ADD COLUMN IF NOT EXISTS {col} {typ}")


def downgrade() -> None:
    for table, col, _typ in reversed(_ADD_COLS):
        op.execute(f"ALTER TABLE control.{table} DROP COLUMN IF EXISTS {col}")
    op.execute("DROP TYPE IF EXISTS source_type")
    op.execute("DROP TYPE IF EXISTS catalogue_impact")
