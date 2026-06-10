"""admin grant list (runtime-editable administrators)

Administrators are resolved from TWO sources: the ADMIN_EMAILS env (break-glass bootstrap — always
admin, cannot be revoked from the UI, so you can never lock yourself out) UNION this persisted
grant list, which admins edit at runtime (Settings -> Administrators) without a redeploy. Seeded
with the named app administrators so they are admins on first login. Grants are domain-restricted
and audited at the service layer.

Revision ID: 0009_admin_grants
Revises: 0008_digest_envelope
Create Date: 2026-06-10
"""

from __future__ import annotations

from alembic import op

revision: str = "0009_admin_grants"
down_revision: str | None = "0008_digest_envelope"
branch_labels: str | None = None
depends_on: str | None = None

_SEED_ADMINS = ("tom.hedgecoth@zennify.com", "mishley.otiende@zennify.com")


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS control.admin_grant (
            email       text PRIMARY KEY,
            granted_by  text,
            note        text,
            created_at  timestamptz NOT NULL DEFAULT now()
        )
        """)
    for email in _SEED_ADMINS:
        op.execute(
            "INSERT INTO control.admin_grant (email, granted_by, note) "
            f"VALUES ('{email}', 'seed', 'named app administrator') "
            "ON CONFLICT (email) DO NOTHING"
        )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS control.admin_grant")
