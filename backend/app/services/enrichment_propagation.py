"""R7 cross-version enrichment propagation — escalate an approved enrichment to EVERY version it
belongs in.

When a use case is approved on one version (change_flags._approve_use_case_gap), this "saves it to
all versions": for every OTHER provisioned/active version it maps the owning subcap into that
version (exact id -> id-governance crosswalk -> semantic nearest-neighbour, subcap_xref's tiers),
runs the deep-NLP NECESSITY gate (services/enrichment_relevance — a relevant, non-duplicate fit
THERE), re-gates G1-G8 for that version, and — on both passing — AUTO-SAVES it into
``cat_<target>.use_case`` with an immutable audit row. A version where it does not belong is skipped
with the reason recorded. All in the caller's transaction (all-or-nothing). Generic by design
(``propagate_use_case`` is the first concrete kind); nothing is written where the gate says no, so
never enrich the wrong things.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.intelligence import gates
from app.services import enrichment_relevance

_SCHEMA_RE = re.compile(r"^cat_[a-z0-9_]+$")


async def _other_versions(conn: AsyncConnection, source_version: str) -> list[tuple[str, str]]:
    """Every committable version OTHER than the source (provisioned or active) with its schema."""
    rows = (
        await conn.execute(
            text(
                "SELECT version_id, schema_name FROM control.catalogue_version "
                "WHERE status IN ('provisioned', 'active') AND version_id <> :src "
                "ORDER BY version_id"
            ),
            {"src": source_version},
        )
    ).all()
    return [(str(r[0]), str(r[1])) for r in rows if _SCHEMA_RE.match(str(r[1]))]


async def _map_subcap(
    conn: AsyncConnection,
    source_version: str,
    source_schema: str,
    subcap_id: str,
    target_version: str,
    target_schema: str,
) -> str | None:
    """Find the owning subcap's home in the target version: exact id (the stable 851-subcap core is
    shared across versions) -> id-governance crosswalk -> semantic nearest-neighbour over the subcap
    embeddings (for a drifted legacy version). None when it genuinely has no home there."""
    exact = (
        await conn.execute(
            text(f"SELECT 1 FROM {target_schema}.subcap WHERE subcap_id = :s"),
            {"s": subcap_id},
        )
    ).first()
    if exact is not None:
        return subcap_id
    cw = (
        await conn.execute(
            text(
                "SELECT to_subcap FROM control.version_crosswalk "
                "WHERE from_version = :fv AND from_subcap = :fs AND to_version = :tv "
                "AND to_subcap IS NOT NULL "
                "UNION ALL "
                "SELECT from_subcap FROM control.version_crosswalk "
                "WHERE to_version = :fv AND to_subcap = :fs AND from_version = :tv LIMIT 1"
            ),
            {"fv": source_version, "fs": subcap_id, "tv": target_version},
        )
    ).first()
    if cw is not None and cw[0]:
        return str(cw[0])
    # semantic tier: nearest target subcap to the source subcap's embedding (pgvector), gated by the
    # xref semantic floor — how a legacy version whose ids drifted still finds the subcap's home.
    subcap_min, _ = gates.xref_semantic_config()
    row = (
        await conn.execute(
            text(
                f"SELECT t.subcap_id, 1 - (t.embedding <=> s.embedding) AS cos "
                f"FROM {target_schema}.subcap t, {source_schema}.subcap s "
                "WHERE s.subcap_id = :src AND t.embedding IS NOT NULL AND s.embedding IS NOT NULL "
                "ORDER BY t.embedding <=> s.embedding LIMIT 1"
            ),
            {"src": subcap_id},
        )
    ).first()
    if row is not None and float(row[1] or 0.0) >= subcap_min:
        return str(row[0])
    return None


def _prop_use_case_id(use_case_id: str, target_version: str, target_subcap: str) -> str:
    """A collision-safe, deterministic id for the propagated copy (stable across re-runs -> the
    INSERT is idempotent)."""
    h = hashlib.blake2b(f"{use_case_id}:{target_version}".encode(), digest_size=5).hexdigest()
    return f"UC-PROP-{target_subcap}-{h}".upper()


async def _audit(
    conn: AsyncConnection, actor: str, action: str, target_ref: str, meta: dict[str, Any]
) -> None:
    await conn.execute(
        text(
            "INSERT INTO control.audit_log (actor, action, target_ref, meta) "
            "VALUES (:a, :ac, :t, CAST(:m AS jsonb))"
        ),
        {"a": actor, "ac": action, "t": target_ref, "m": json.dumps(meta)},
    )


async def propagate_use_case(
    conn: AsyncConnection,
    *,
    source_version: str,
    source_schema: str,
    subcap_id: str,
    name: str,
    description: str | None,
    archetype: str | None,
    use_case_id: str,
    actor: str,
) -> dict[str, Any]:
    """Escalate an approved use case to every OTHER provisioned version where the necessity gate
    it belongs, auto-saving it there (re-gated + audited). Returns
    ``{saved: [{version, subcap, use_case_id}], skipped: [{version, reason}]}``. Idempotent (the
    propagated id is deterministic + ON CONFLICT DO NOTHING; the relevance verdict is cached)."""
    enrichment_text = f"{name}. {(description or '').strip()} [{archetype or ''}]".strip()
    saved: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []
    for tv, ts in await _other_versions(conn, source_version):
        tgt_subcap = await _map_subcap(conn, source_version, source_schema, subcap_id, tv, ts)
        if tgt_subcap is None:
            skipped.append(
                {"version": tv, "reason": "the owning subcap has no home in this version"}
            )
            continue
        verdict = await enrichment_relevance.relevance(
            conn,
            kind="use_case",
            enrichment_key=use_case_id,
            enrichment_text=enrichment_text,
            target_version=tv,
            target_schema=ts,
            target_subcap=tgt_subcap,
        )
        if not verdict.relevant:
            skipped.append({"version": tv, "reason": verdict.rationale})
            continue
        results, gverdict = gates.evaluate_suggestion(
            target_exists=True,
            evidence_count=2,  # the source approval + the necessity judgment
            source_tier="T1",
            cited=True,
            contradicts=False,
            cost_usd=verdict.cost_usd,
        )
        if gverdict != "pass":
            skipped.append(
                {"version": tv, "reason": f"re-gate failed: {gates.first_failing(results)}"}
            )
            continue
        new_id = _prop_use_case_id(use_case_id, tv, tgt_subcap)
        await conn.execute(
            text(
                f"INSERT INTO {ts}.use_case "
                "(use_case_id, subcap_id, archetype, name, description, is_new) "
                "VALUES (:id, :sub, :arch, :name, :desc, true) "
                "ON CONFLICT (use_case_id) DO NOTHING"
            ),
            {
                "id": new_id,
                "sub": tgt_subcap,
                "arch": archetype,
                "name": name or f"Use case for {tgt_subcap}",
                "desc": description,
            },
        )
        await _audit(
            conn,
            actor,
            "change_flag.propagate",
            tgt_subcap,
            {
                "accepted": "use_case_propagated",
                "from_version": source_version,
                "from_use_case": use_case_id,
                "target_version": tv,
                "target_subcap": tgt_subcap,
                "use_case_id": new_id,
                "relevance": round(verdict.confidence, 3),
                "rationale": verdict.rationale,
                "snapshot_ref": f"audit:use_case:{new_id}",
            },
        )
        saved.append({"version": tv, "subcap": tgt_subcap, "use_case_id": new_id})
    return {"saved": saved, "skipped": skipped}
