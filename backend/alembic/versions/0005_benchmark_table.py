"""control.benchmark (D4)

One of the four tables the reference DDL omits (plan Part C / ADR 0001): the benchmark payload +
subcap mapping behind ``/evidence?kind=benchmark``. The observations' provenance lives on the
linked ``evidence_item (kind='benchmark')`` row; this table carries the quantitative core the
Benchmarks studio renders — raw observations, the bootstrap CI band (p25/p50/p75 · ci_low/ci_high),
the methodology (NULL renders "not documented"), the adversarial verdict (NULL renders "pending",
e.g. a 429'd adversary call) and its note, the mapped subcaps (``affects`` jsonb id->score;
``subcap_id`` = top match, the C3 trace key) and the reasoning-chain backlink. Additive and
reversible; applied before the new revision takes traffic.

Revision ID: 0005_benchmark_table
Revises: 0004_trend_signals_envelope
Create Date: 2026-06-10
"""

from __future__ import annotations

from alembic import op

revision: str = "0005_benchmark_table"
down_revision: str | None = "0004_trend_signals_envelope"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS control.benchmark (
            benchmark_id  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            evidence_id   uuid NOT NULL REFERENCES control.evidence_item(evidence_id),
            version_id    text NOT NULL,
            subcap_id     text,
            segment       text,
            metric        text NOT NULL,
            unit          text,
            observations  jsonb NOT NULL DEFAULT '[]',
            n             integer NOT NULL DEFAULT 0,
            p25           numeric(12,3),
            p50           numeric(12,3),
            p75           numeric(12,3),
            ci_low        numeric(12,3),
            ci_high       numeric(12,3),
            methodology   text,
            verdict       text,
            verdict_note  text,
            affects       jsonb NOT NULL DEFAULT '[]',
            chain_id      uuid REFERENCES control.reasoning_chain(chain_id),
            created_at    timestamptz NOT NULL DEFAULT now()
        )
        """)
    # The C3 project-subcap trace unions benchmark events per (version, subcap).
    op.execute(
        "CREATE INDEX IF NOT EXISTS benchmark_version_subcap_idx "
        "ON control.benchmark (version_id, subcap_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS control.benchmark_version_subcap_idx")
    op.execute("DROP TABLE IF EXISTS control.benchmark")
