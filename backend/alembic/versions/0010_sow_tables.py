"""control.sow_document / sow_scope_item / sow_subcap_match (C1)

Three of the four tables the reference DDL omits (plan Part C / ADR 0001): the SOW corpus behind
the SOW library and the client journey. A document is DLP-redacted BEFORE anything model-facing
reads it (``redacted`` asserts that); its scope items are the matchable clauses; matches carry the
carry-forward confidence bands (>=0.86 confirmed / >=0.70 review / else unmapped — config
``matching``), the trust envelope and the reasoning-chain backlink. ``account_key`` is the client
identity used for entity resolution against ``control.story.project_key`` (FR-19). Additive and
reversible; applied before the new revision takes traffic.

Revision ID: 0010_sow_tables
Revises: 0009_admin_grants
Create Date: 2026-06-10
"""

from __future__ import annotations

from alembic import op

revision: str = "0010_sow_tables"
down_revision: str | None = "0009_admin_grants"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # The public-source enum gains the internal-document origin (SOW chunks are evidence too).
    # Additive on PG16; enum values cannot be dropped, so downgrade leaves it (harmless).
    op.execute("ALTER TYPE source_type ADD VALUE IF NOT EXISTS 'internal'")
    # The schema-mapping registry (catalogue_sheet / source_field_mapping / relation_def) is
    # PER-VERSION metadata: provisioning re-registers it and deleting a version must take its
    # registry with it. The baseline FKs lacked ON DELETE CASCADE; tighten them here.
    op.execute(
        "ALTER TABLE control.catalogue_sheet "
        "DROP CONSTRAINT IF EXISTS catalogue_sheet_version_id_fkey, "
        "ADD CONSTRAINT catalogue_sheet_version_id_fkey FOREIGN KEY (version_id) "
        "REFERENCES control.catalogue_version(version_id) ON DELETE CASCADE"
    )
    op.execute(
        "ALTER TABLE control.source_field_mapping "
        "DROP CONSTRAINT IF EXISTS source_field_mapping_version_id_fkey, "
        "ADD CONSTRAINT source_field_mapping_version_id_fkey FOREIGN KEY (version_id) "
        "REFERENCES control.catalogue_version(version_id) ON DELETE CASCADE"
    )
    op.execute(
        "ALTER TABLE control.source_field_mapping "
        "DROP CONSTRAINT IF EXISTS source_field_mapping_sheet_id_fkey, "
        "ADD CONSTRAINT source_field_mapping_sheet_id_fkey FOREIGN KEY (sheet_id) "
        "REFERENCES control.catalogue_sheet(sheet_id) ON DELETE CASCADE"
    )
    op.execute(
        "ALTER TABLE control.relation_def "
        "DROP CONSTRAINT IF EXISTS relation_def_version_id_fkey, "
        "ADD CONSTRAINT relation_def_version_id_fkey FOREIGN KEY (version_id) "
        "REFERENCES control.catalogue_version(version_id) ON DELETE CASCADE"
    )
    op.execute("""
        CREATE TABLE IF NOT EXISTS control.sow_document (
            sow_id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            account_key   text NOT NULL,
            account_name  text NOT NULL,
            title         text NOT NULL,
            sv_code       text,
            signed_date   date,
            status        text NOT NULL DEFAULT 'active',
            redacted      boolean NOT NULL DEFAULT true,
            created_at    timestamptz NOT NULL DEFAULT now(),
            UNIQUE (account_key, title)
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS control.sow_scope_item (
            scope_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            sow_id        uuid NOT NULL REFERENCES control.sow_document(sow_id) ON DELETE CASCADE,
            ordinal       integer NOT NULL,
            clause        text NOT NULL,
            created_at    timestamptz NOT NULL DEFAULT now(),
            UNIQUE (sow_id, ordinal)
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS control.sow_subcap_match (
            match_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            scope_id      uuid NOT NULL REFERENCES control.sow_scope_item(scope_id)
                          ON DELETE CASCADE,
            version_id    text NOT NULL,
            subcap_id     text NOT NULL,
            similarity    numeric(5,3) NOT NULL,
            status        text NOT NULL CHECK (status IN ('confirmed', 'review', 'unmapped')),
            claim_label   claim_label NOT NULL DEFAULT 'INFERENCE',
            source_tier   source_tier NOT NULL DEFAULT 'T1',
            chain_id      uuid REFERENCES control.reasoning_chain(chain_id),
            evidence_id   uuid REFERENCES control.evidence_item(evidence_id),
            confirmed_by  text,
            created_at    timestamptz NOT NULL DEFAULT now(),
            UNIQUE (scope_id, version_id)
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_sow_match_subcap "
        "ON control.sow_subcap_match (version_id, subcap_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_sow_doc_account ON control.sow_document (account_key)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS control.sow_subcap_match")
    op.execute("DROP TABLE IF EXISTS control.sow_scope_item")
    op.execute("DROP TABLE IF EXISTS control.sow_document")
