"""ingest source registry (Settings / admin sources)

The app's ingestion points as PERSISTED configuration: one row per source the F7 pipelines pull
from, naming BOTH origins — the recorded fixture each hermetic run replays from the database, and
the online origin the live mode calls (Vertex grounded search / Jira API / GCS upload). Which
origin is active is decided by LLM_MODE at read time (the global hermetic switch, CLAUDE.md
safeguard); ``enabled`` turns a source off without a deploy. GET /api/admin/sources composes this
registry with config/schedules.yaml (cadence) and control.ingest_run (last run + stats), so a
stale or erroring source shows its last poll — warned, never hidden.

Seed rows are the spec's source-registry table (Implementation §source registry); the seed is
idempotent (ON CONFLICT DO NOTHING) so re-running the migration job is safe.

Revision ID: 0006_ingest_source_registry
Revises: 0005_benchmark_table
Create Date: 2026-06-10
"""

from __future__ import annotations

from alembic import op

revision: str = "0006_ingest_source_registry"
down_revision: str | None = "0005_benchmark_table"
branch_labels: str | None = None
depends_on: str | None = None

# key, name, source_type, tier, recorded origin (database), live origin (online), enabled, notes
_SEED: tuple[tuple[str, str, str, str, str, str, bool, str], ...] = (
    (
        "jira",
        "Jira delivery corpus",
        "peer",
        "T1",
        "control.story — canonical 14,406-row corpus (provisioned)",
        "Jira Cloud API (hourly poll + webhook)",
        True,
        "Internal delivery reality; feeds carry-forward, G6 contradiction and the trace.",
    ),
    (
        "sow",
        "SOW library",
        "peer",
        "T1",
        "control.sow_document — uploaded corpus (DLP-redacted)",
        "GCS upload bucket (admin upload, DLP-redacted before any model)",
        True,
        "Internal contracts; scope items match to subcaps under G1/G5/G7.",
    ),
    (
        "news",
        "Public news scan",
        "regulator",
        "T1",
        "intelligence/news.py — recorded public-source fixture",
        "Vertex AI grounded search (Google Search grounding, Batch, weekly)",
        True,
        "Public sources only (D6): regulators T1, analysts T2, trade press T3.",
    ),
    (
        "trends",
        "Trend detection",
        "analyst",
        "T2",
        "control.evidence_item — clusters the stored 8-week gated window",
        "Same store — detection is derived, never fetched",
        True,
        "Derived source: trends are earned from already-gated evidence, no external pull.",
    ),
    (
        "benchmarks",
        "Benchmark panels",
        "benchmark",
        "T2",
        "intelligence/benchmarks.py — recorded curated panels",
        "Vertex AI grounded search over curated benchmark datasets (Batch, monthly)",
        True,
        "Curated benchmark datasets, normalised with confidence bands; adversarial verdict.",
    ),
    (
        "vendor",
        "Vendor developments",
        "vendor",
        "T3",
        "intelligence/vendors.py — recorded vendor-development fixture",
        "Vertex AI grounded search over vendor newsrooms/release notes (Batch, weekly)",
        True,
        "Vendor self-published material is T4; independent coverage lifts to T3.",
    ),
)


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS control.ingest_source (
            source_key      text PRIMARY KEY,
            name            text NOT NULL,
            source_type     source_type NOT NULL,
            tier            source_tier NOT NULL,
            origin_recorded text NOT NULL,
            origin_live     text NOT NULL,
            enabled         boolean NOT NULL DEFAULT true,
            notes           text,
            updated_at      timestamptz NOT NULL DEFAULT now()
        )
        """)
    for key, name, stype, tier, recorded, live, enabled, notes in _SEED:
        op.execute(
            "INSERT INTO control.ingest_source "
            "(source_key, name, source_type, tier, origin_recorded, origin_live, enabled, notes) "
            f"VALUES ('{key}', '{name}', '{stype}', '{tier}', "
            f"'{recorded.replace(chr(39), chr(39) * 2)}', "
            f"'{live.replace(chr(39), chr(39) * 2)}', {str(enabled).lower()}, "
            f"'{notes.replace(chr(39), chr(39) * 2)}') "
            "ON CONFLICT (source_key) DO NOTHING"
        )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS control.ingest_source")
