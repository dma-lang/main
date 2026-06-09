"""control-plane baseline (F3)

Adopts docs/specs/schema.sql (control.* only) as the Alembic baseline: the control schema, the 16
shared enums, the 35 control.* tables, their indexes, and the story_catalogue_link view. The
cat_<version> data plane is generated per-version by F4, not Alembic. Transactional DDL: a failure
rolls the whole baseline back.

Revision ID: 0001_control_baseline
Revises:
Create Date: 2026-06-09
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from alembic import op

revision: str = "0001_control_baseline"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None

_SQL_DIR = Path(__file__).resolve().parents[1] / "sql"

# The 16 shared enums created by control_baseline.sql (dropped on downgrade, after the schema).
_ENUMS = (
    "claim_label",
    "source_tier",
    "lifecycle_state",
    "suggestion_status",
    "gate_verdict",
    "magnitude",
    "confidence_level",
    "mapping_status",
    "carry_status",
    "relation_type",
    "evidence_kind",
    "vendor_event_type",
    "kg_layer",
    "sheet_role",
    "cardinality",
    "cascade_kind",
)


def _statements(sql: str) -> Iterator[str]:
    """Yield DDL statements. Strip line comments first (some contain ';'), then split on ';'."""
    no_comments = "\n".join(line.split("--", 1)[0] for line in sql.splitlines())
    for chunk in no_comments.split(";"):
        statement = chunk.strip()
        if statement:
            yield statement


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    sql = (_SQL_DIR / "control_baseline.sql").read_text(encoding="utf-8")
    for statement in _statements(sql):
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP SCHEMA IF EXISTS control CASCADE")
    for enum in _ENUMS:
        op.execute(f"DROP TYPE IF EXISTS {enum}")
    # Extensions (pgcrypto, vector) are shared/idempotent; left in place.
