"""digest trust envelope (E1)

The quarterly digest is an AI-derived synthesis, so it carries the same envelope every AI value
does: claim label + reasoning-chain backlink (tier/ERS live on the cited evidence). The reference
DDL's control.digest has neither; add them additively. Also a uniqueness guard on quarter — the
digest is regenerated per quarter, never duplicated.

Revision ID: 0008_digest_envelope
Revises: 0007_vendor_impact_score
Create Date: 2026-06-10
"""

from __future__ import annotations

from alembic import op

revision: str = "0008_digest_envelope"
down_revision: str | None = "0007_vendor_impact_score"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE control.digest ADD COLUMN IF NOT EXISTS claim_label claim_label")
    op.execute("ALTER TABLE control.digest ADD COLUMN IF NOT EXISTS chain_id uuid")
    op.execute(
        "DO $$ BEGIN "
        "ALTER TABLE control.digest ADD CONSTRAINT digest_chain_fk "
        "FOREIGN KEY (chain_id) REFERENCES control.reasoning_chain(chain_id); "
        "EXCEPTION WHEN duplicate_object THEN NULL; END $$"
    )
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS digest_quarter_uq ON control.digest (quarter)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS control.digest_quarter_uq")
    op.execute("ALTER TABLE control.digest DROP CONSTRAINT IF EXISTS digest_chain_fk")
    op.execute("ALTER TABLE control.digest DROP COLUMN IF EXISTS chain_id")
    op.execute("ALTER TABLE control.digest DROP COLUMN IF EXISTS claim_label")
