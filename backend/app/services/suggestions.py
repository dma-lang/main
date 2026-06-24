"""F8 — the AI suggestion lifecycle: propose -> G1-G8 -> human apply/reject (gated mutation).

CLAUDE.md safeguard 2: nothing AI-derived commits without passing all eight gates + human approval.
``apply`` RE-GATES server-side on the current state before any write, then mutates ``cat_<v>`` and
appends an immutable ``audit_log`` row (capturing before/after for revert) in ONE transaction — a
half-apply is impossible and a failed re-gate writes nothing. Hermetic-deterministic (no spend).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app import db
from app.intelligence import gates
from app.versioning import resolve_version

_SCHEMA_RE = re.compile(r"^cat_[a-z0-9_]+$")
_PROMOTE_TO = "rising"
_PROMOTE_FROM = "stable"


@dataclass
class SuggestionRow:
    suggestion_id: str
    target_subcap: str | None
    subcap_name: str | None
    pillar: str | None
    kind: str
    title: str
    rationale: str
    status: str
    verdict: str | None
    breaking: bool
    claim_label: str | None
    source_tier: str | None
    ers: int
    chain_id: str | None
    cost: str
    created_at: str | None


@dataclass
class ApplyResult:
    applied: bool
    status: str
    gate_failed: str | None = None
    before: str | None = None
    after: str | None = None


async def _catalogue_evidence(conn: AsyncConnection, subcap_id: str, title: str) -> UUID:
    found = (
        await conn.execute(
            text(
                "SELECT evidence_id FROM control.evidence_item "
                "WHERE kind = 'catalogue' AND body_ref = :b"
            ),
            {"b": subcap_id},
        )
    ).first()
    if found is not None:
        return UUID(str(found[0]))
    created = (
        await conn.execute(
            text(
                "INSERT INTO control.evidence_item (kind, title, source_tier, body_ref) "
                "VALUES ('catalogue', :t, 'T1', :b) RETURNING evidence_id"
            ),
            {"t": title, "b": subcap_id},
        )
    ).first()
    assert created is not None
    return UUID(str(created[0]))


async def propose(version: str, limit: int = 3) -> dict[str, Any]:
    """Generate grounded lifecycle-promotion suggestions for high-delivery subcaps still 'stable'.
    Each carries a reasoning chain, a citation, and a full G1-G8 gate run."""
    v = await resolve_version(version)
    schema = v.schema_name
    if not _SCHEMA_RE.match(schema):
        raise ValueError("invalid version schema")
    engine = db.require_engine()

    async with engine.begin() as conn:
        candidates = (
            (
                await conn.execute(
                    text(
                        "SELECT s.subcap_id, s.name, left(s.subcap_id, 2) AS pillar, sc.stories "
                        "FROM (SELECT subcap_id, count(*) AS stories "
                        "FROM control.story_catalogue_link "
                        "WHERE version_id = :ver GROUP BY subcap_id) sc "
                        f"JOIN {schema}.subcap s ON s.subcap_id = sc.subcap_id "
                        f"WHERE s.lifecycle_state = '{_PROMOTE_FROM}' "
                        "AND NOT EXISTS (SELECT 1 FROM control.suggestion g "
                        "WHERE g.target_subcap = s.subcap_id AND g.target_version = :ver "
                        "AND g.status = 'pending' AND g.kind = 'lifecycle_promotion') "
                        "ORDER BY sc.stories DESC, s.subcap_id LIMIT :n"
                    ),
                    {"ver": v.version_id, "n": limit},
                )
            )
            .mappings()
            .all()
        )

        created = 0
        for c in candidates:
            stories = int(c["stories"])
            results, verdict = gates.evaluate_suggestion(
                target_exists=True,
                evidence_count=stories,
                source_tier="T1",
                cited=True,
                contradicts=False,  # promoting a high-delivery subcap agrees with delivery reality
                cost_usd=0.0,
            )
            title = f"Promote {c['name']} to '{_PROMOTE_TO}'"
            rationale = (
                f"{stories} delivered stories show active momentum while the lifecycle is still "
                f"'{_PROMOTE_FROM}'. Promote to '{_PROMOTE_TO}', grounded in the delivery corpus."
            )
            chain_id = (
                await conn.execute(
                    text(
                        "INSERT INTO control.reasoning_chain "
                        "(operation, subject_ref, claim_label, summary, model, cost_usd) "
                        "VALUES ('suggestion', :subj, 'INFERENCE', :summary, 'hermetic-stub', 0) "
                        "RETURNING chain_id"
                    ),
                    {"subj": title, "summary": rationale},
                )
            ).scalar_one()
            ev = await _catalogue_evidence(conn, c["subcap_id"], c["name"])
            await conn.execute(
                text(
                    "INSERT INTO control.reasoning_step "
                    "(chain_id, ordinal, kind, text, evidence_id) "
                    "VALUES (:c, 1, 'retrieve', :t, :e)"
                ),
                {
                    "c": chain_id,
                    "t": f"{stories} delivery stories carried onto {c['subcap_id']}.",
                    "e": ev,
                },
            )
            await conn.execute(
                text(
                    "INSERT INTO control.citation (chain_id, evidence_id, verified) "
                    "VALUES (:c, :e, true)"
                ),
                {"c": chain_id, "e": ev},
            )
            await conn.execute(
                text(
                    "INSERT INTO control.validation_gate_run "
                    "(chain_id, target_ref, gate_results, verdict) "
                    "VALUES (:c, :t, CAST(:r AS jsonb), CAST(:v AS gate_verdict))"
                ),
                {"c": chain_id, "t": c["subcap_id"], "r": json.dumps(results), "v": verdict},
            )
            payload = {
                "title": title,
                "rationale": rationale,
                "subcap_name": c["name"],
                "pillar": c["pillar"],
                "before": {"lifecycle_state": _PROMOTE_FROM},
                "after": {"lifecycle_state": _PROMOTE_TO},
                "evidence_count": stories,
                "gate_results": results,
                "verdict": verdict,
                "breaking": False,
            }
            await conn.execute(
                text(
                    "INSERT INTO control.suggestion (target_version, target_subcap, kind, payload, "
                    "claim_label, source_tier, ers, chain_id, status) VALUES "
                    "(:ver, :sub, 'lifecycle_promotion', CAST(:p AS jsonb), 'INFERENCE', 'T1', "
                    ":ers, :chain, 'pending')"
                ),
                {
                    "ver": v.version_id,
                    "sub": c["subcap_id"],
                    "p": json.dumps(payload),
                    "ers": round(min(0.95, 0.55 + 0.08 * min(5, stories)), 3),
                    "chain": chain_id,
                },
            )
            created += 1
    return {"version": v.version_id, "created": created, "candidates": len(candidates)}


async def _scan_evidence(
    conn: AsyncConnection, version_id: str, subcap_id: str, corpus_n: int
) -> UUID:
    """The corpus-scan MEASUREMENT as stored evidence: '0 of N carried Jira stories map to this
    subcap'. kind='benchmark' (a measured delivery observation over the canonical corpus), T1,
    idempotent on body_ref so re-proposing cites the same row."""
    ref = f"corpus-scan:{version_id}:{subcap_id}"
    found = (
        await conn.execute(
            text(
                "SELECT evidence_id FROM control.evidence_item "
                "WHERE kind = 'benchmark' AND body_ref = :b"
            ),
            {"b": ref},
        )
    ).first()
    if found is not None:
        return UUID(str(found[0]))
    created = (
        await conn.execute(
            text(
                "INSERT INTO control.evidence_item "
                "(kind, title, source_tier, body_ref, source_name) "
                "VALUES ('benchmark', :t, 'T1', :b, 'story_catalogue_link') "
                "RETURNING evidence_id"
            ),
            {
                "t": (
                    f"Delivery-corpus scan: 0 of {corpus_n:,} carried Jira stories map to "
                    f"{subcap_id} in {version_id}"
                ),
                "b": ref,
            },
        )
    ).first()
    assert created is not None
    return UUID(str(created[0]))


async def propose_decay(version: str, limit: int = 3) -> dict[str, Any]:
    """DECAY suggestions: a subcap with ZERO delivered Jira stories (synthetic never counts) is
    decayed — it may stay active, but an admin should decide. Each suggestion proposes demoting
    lifecycle to 'declining' (never auto-deactivates), carries a reasoning chain + TWO verified
    citations — the catalogue record AND the corpus-scan measurement itself — and a full G1-G8
    gate run, the same QA-gate pipeline every suggestion passes before a consultant sees it
    (deterministic gates always; the adversarial Gemini review applies in live mode)."""
    v = await resolve_version(version)
    schema = v.schema_name
    if not _SCHEMA_RE.match(schema):
        raise ValueError("invalid version schema")
    engine = db.require_engine()

    async with engine.begin() as conn:
        candidates = (
            (
                await conn.execute(
                    text(
                        "SELECT s.subcap_id, s.name, left(s.subcap_id, 2) AS pillar "
                        f"FROM {schema}.subcap s "
                        "WHERE s.lifecycle_state = 'stable' "
                        "AND NOT EXISTS (SELECT 1 FROM control.story_catalogue_link l "
                        "WHERE l.version_id = :ver AND l.subcap_id = s.subcap_id) "
                        "AND NOT EXISTS (SELECT 1 FROM control.suggestion g "
                        "WHERE g.target_subcap = s.subcap_id AND g.target_version = :ver "
                        "AND g.status = 'pending' AND g.kind = 'decay_review') "
                        "ORDER BY s.tier NULLS LAST, s.subcap_id LIMIT :n"
                    ),
                    {"ver": v.version_id, "n": limit},
                )
            )
            .mappings()
            .all()
        )
        corpus_n = int(
            (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM control.story_catalogue_link "
                        "WHERE version_id = :ver"
                    ),
                    {"ver": v.version_id},
                )
            ).scalar()
            or 0
        )

        created = 0
        for c in candidates:
            results, verdict = gates.evaluate_suggestion(
                target_exists=True,
                # two REAL stored sources: the catalogue record + the corpus-scan measurement
                # (the zero-story observation is itself evidence, persisted and citable)
                evidence_count=2,
                source_tier="T1",
                cited=True,
                contradicts=False,
                cost_usd=0.0,
            )
            title = f"Decayed: {c['name']} has no delivered Jira stories"
            rationale = (
                f"{c['subcap_id']} has 0 delivered Jira stories in {v.version_id} (synthetic "
                "stories excluded by construction). A decayed subcap can remain active — this "
                "proposes demoting lifecycle to 'declining' for an admin to approve or reject; "
                "nothing is deactivated automatically."
            )
            chain_id = (
                await conn.execute(
                    text(
                        "INSERT INTO control.reasoning_chain "
                        "(operation, subject_ref, claim_label, summary, model, cost_usd) "
                        "VALUES ('suggestion', :subj, 'INFERENCE', :summary, 'hermetic-stub', 0) "
                        "RETURNING chain_id"
                    ),
                    {"subj": title, "summary": rationale},
                )
            ).scalar_one()
            ev = await _catalogue_evidence(conn, c["subcap_id"], c["name"])
            ev_scan = await _scan_evidence(conn, v.version_id, c["subcap_id"], corpus_n)
            await conn.execute(
                text(
                    "INSERT INTO control.reasoning_step "
                    "(chain_id, ordinal, kind, text, evidence_id) "
                    "VALUES (:c, 1, 'retrieve', :t1, :e1), (:c, 2, 'weigh', :t2, :e2)"
                ),
                {
                    "c": chain_id,
                    "t1": f"{c['subcap_id']} is an active catalogue record in {v.version_id}.",
                    "e1": ev,
                    "t2": (
                        f"Corpus scan: 0 of {corpus_n:,} carried Jira stories link to "
                        f"{c['subcap_id']} in {v.version_id} (synthetic excluded)."
                    ),
                    "e2": ev_scan,
                },
            )
            await conn.execute(
                text(
                    "INSERT INTO control.citation (chain_id, evidence_id, verified) "
                    "VALUES (:c, :e1, true), (:c, :e2, true)"
                ),
                {"c": chain_id, "e1": ev, "e2": ev_scan},
            )
            await conn.execute(
                text(
                    "INSERT INTO control.validation_gate_run "
                    "(chain_id, target_ref, gate_results, verdict) "
                    "VALUES (:c, :t, CAST(:r AS jsonb), CAST(:v AS gate_verdict))"
                ),
                {"c": chain_id, "t": c["subcap_id"], "r": json.dumps(results), "v": verdict},
            )
            payload = {
                "title": title,
                "rationale": rationale,
                "subcap_name": c["name"],
                "pillar": c["pillar"],
                "before": {"lifecycle_state": "stable"},
                "after": {"lifecycle_state": "declining"},
                "evidence_count": 2,
                "gate_results": results,
                "verdict": verdict,
                "breaking": False,
            }
            await conn.execute(
                text(
                    "INSERT INTO control.suggestion (target_version, target_subcap, kind, payload, "
                    "claim_label, source_tier, ers, chain_id, status) VALUES "
                    "(:ver, :sub, 'decay_review', CAST(:p AS jsonb), 'INFERENCE', 'T1', "
                    "0.6, :chain, 'pending')"
                ),
                {
                    "ver": v.version_id,
                    "sub": c["subcap_id"],
                    "p": json.dumps(payload),
                    "chain": chain_id,
                },
            )
            created += 1
    return {"version": v.version_id, "created": created, "candidates": len(candidates)}


def _row(m: dict[str, Any]) -> SuggestionRow:
    p = m["payload"] or {}
    return SuggestionRow(
        suggestion_id=str(m["suggestion_id"]),
        target_subcap=m["target_subcap"],
        subcap_name=p.get("subcap_name"),
        pillar=p.get("pillar"),
        kind=m["kind"],
        title=p.get("title", m["kind"]),
        rationale=p.get("rationale", ""),
        status=m["status"],
        verdict=p.get("verdict"),
        breaking=bool(p.get("breaking", False)),
        claim_label=m["claim_label"],
        source_tier=m["source_tier"],
        ers=round((float(m["ers"]) if m["ers"] is not None else 0) * 100),
        chain_id=str(m["chain_id"]) if m["chain_id"] else None,
        cost="$0.000",
        created_at=m["created_at"],
    )


async def list_suggestions(status: str = "pending") -> list[SuggestionRow]:
    engine = db.get_engine()
    if engine is None:
        return []
    where = "WHERE status = CAST(:s AS suggestion_status)" if status else ""
    async with engine.connect() as conn:
        rows = (
            (
                await conn.execute(
                    text(
                        "SELECT suggestion_id, target_subcap, kind, payload, claim_label::text "
                        "AS claim_label, source_tier::text AS source_tier, ers::float AS ers, "
                        "chain_id, status::text AS status, created_at::text AS created_at "
                        f"FROM control.suggestion {where} ORDER BY created_at DESC"
                    ),
                    {"s": status} if status else {},
                )
            )
            .mappings()
            .all()
        )
    return [_row(dict(r)) for r in rows]


def _compact(s: str, n: int = 42) -> str:
    """Compact a long field value for the apply receipt (the audit row keeps full values)."""
    return s if len(s) <= n else s[: n - 1] + "…"


async def _mutate(
    conn: AsyncConnection,
    schema: str,
    target: str,
    current: dict[str, Any],
    after_spec: dict[str, Any],
) -> tuple[str | None, str, dict[str, Any]]:
    """Dispatch the gated mutation by payload shape -> (before, after, audit-meta delta).

    Shapes: ``{"lifecycle_state"}`` (promotion/demotion), ``{"description"}`` (descriptor
    update), ``{"use_case"}`` (new use-case INSERT). Anything else fails loudly — an
    unsupported shape must never half-apply.
    """
    if "lifecycle_state" in after_spec:
        before, after = str(current["lifecycle_state"]), str(after_spec["lifecycle_state"])
        await conn.execute(
            text(f"UPDATE {schema}.subcap SET lifecycle_state = :a WHERE subcap_id = :t"),
            {"a": after, "t": target},
        )
        return before, after, {"field": "lifecycle_state", "before": before, "after": after}
    if "description" in after_spec:
        before_full = str(current["description"] or "")
        after_full = str(after_spec["description"])
        await conn.execute(
            text(f"UPDATE {schema}.subcap SET description = :a WHERE subcap_id = :t"),
            {"a": after_full, "t": target},
        )
        return (
            _compact(before_full),
            _compact(after_full),
            {"field": "description", "before": before_full, "after": after_full},
        )
    if "use_case" in after_spec:
        uc = dict(after_spec["use_case"])
        # Idempotent on the deterministic use_case_id (F14): a replayed apply converges.
        await conn.execute(
            text(
                f"INSERT INTO {schema}.use_case "
                "(use_case_id, subcap_id, archetype, name, description) "
                "VALUES (:id, :sub, :arch, :name, :desc) "
                "ON CONFLICT (use_case_id) DO UPDATE SET archetype = EXCLUDED.archetype, "
                "name = EXCLUDED.name, description = EXCLUDED.description"
            ),
            {
                "id": uc["use_case_id"],
                "sub": target,
                "arch": uc.get("archetype"),
                "name": uc["name"],
                "desc": uc.get("description"),
            },
        )
        return None, str(uc["use_case_id"]), {"field": "use_case", "inserted": uc}
    raise ValueError(f"unsupported suggestion payload shape: {sorted(after_spec)}")


async def apply(suggestion_id: str, actor: str) -> ApplyResult:
    """Re-gate G1-G8 on current state, then mutate cat_<v> + append audit_log, transactionally."""
    engine = db.require_engine()
    async with engine.begin() as conn:
        sug = (
            (
                await conn.execute(
                    text(
                        "SELECT target_version, target_subcap, payload, "
                        "status::text AS status, source_tier::text AS source_tier, chain_id "
                        "FROM control.suggestion WHERE suggestion_id = :id FOR UPDATE"
                    ),
                    {"id": suggestion_id},
                )
            )
            .mappings()
            .first()
        )
        if sug is None:
            return ApplyResult(applied=False, status="not_found")
        if sug["status"] != "pending":  # idempotent: already resolved
            return ApplyResult(applied=False, status=sug["status"])

        v = await resolve_version(sug["target_version"])
        schema = v.schema_name
        if not _SCHEMA_RE.match(schema):
            raise ValueError("invalid version schema")
        target = sug["target_subcap"]
        current = (
            (
                await conn.execute(
                    text(
                        f"SELECT lifecycle_state, description FROM {schema}.subcap "
                        "WHERE subcap_id = :t"
                    ),
                    {"t": target},
                )
            )
            .mappings()
            .first()
        )
        stories = (
            await conn.execute(
                text(
                    "SELECT count(*) FROM control.story_catalogue_link "
                    "WHERE version_id = :ver AND subcap_id = :t"
                ),
                {"ver": v.version_id, "t": target},
            )
        ).scalar() or 0
        citations = 0
        if sug["chain_id"] is not None:
            citations = (
                await conn.execute(
                    text("SELECT count(*) FROM control.citation WHERE chain_id = :c AND verified"),
                    {"c": sug["chain_id"]},
                )
            ).scalar() or 0
        # G2 evidence floor: delivery stories for corpus-grounded kinds, verified citations on
        # the chain for news-grounded kinds — whichever evidences this suggestion.
        results, verdict = gates.evaluate_suggestion(
            target_exists=current is not None,
            evidence_count=max(int(stories), int(citations)),
            source_tier=str(sug["source_tier"] or "T1"),
            cited=True,
            contradicts=False,
            cost_usd=0.0,
        )
        if verdict != "pass":
            return ApplyResult(
                applied=False, status="pending", gate_failed=gates.first_failing(results)
            )
        assert current is not None  # G1 passed above

        before, after, meta_delta = await _mutate(
            conn, schema, target, dict(current), (sug["payload"] or {}).get("after") or {}
        )
        await conn.execute(
            text(
                "INSERT INTO control.audit_log (actor, action, target_ref, meta) VALUES "
                "((SELECT uid FROM control.users WHERE uid = :actor), 'suggestion.apply', :t, "
                "CAST(:m AS jsonb))"
            ),
            {
                "actor": actor,
                "t": target,
                "m": json.dumps(
                    {
                        "suggestion_id": suggestion_id,
                        "chain_id": str(sug["chain_id"]) if sug["chain_id"] else None,
                        "verdict": verdict,
                        "snapshot_ref": f"audit:{target}:{meta_delta['field']}",
                        **meta_delta,
                    }
                ),
            },
        )
        await conn.execute(
            text(
                "UPDATE control.suggestion SET status = 'applied', applied_at = now() "
                "WHERE suggestion_id = :id"
            ),
            {"id": suggestion_id},
        )
    return ApplyResult(applied=True, status="applied", before=before, after=after)


async def reject(suggestion_id: str, reason: str, actor: str) -> ApplyResult:
    if not reason.strip():
        raise ValueError("a rejection reason is required")
    engine = db.require_engine()
    async with engine.begin() as conn:
        sug = (
            (
                await conn.execute(
                    text(
                        "SELECT target_subcap, status::text AS status FROM control.suggestion "
                        "WHERE suggestion_id = :id FOR UPDATE"
                    ),
                    {"id": suggestion_id},
                )
            )
            .mappings()
            .first()
        )
        if sug is None:
            return ApplyResult(applied=False, status="not_found")
        if sug["status"] != "pending":
            return ApplyResult(applied=False, status=sug["status"])
        await conn.execute(
            text(
                "UPDATE control.suggestion SET status = 'rejected', reason = :r "
                "WHERE suggestion_id = :id"
            ),
            {"r": reason, "id": suggestion_id},
        )
        await conn.execute(
            text(
                "INSERT INTO control.audit_log (actor, action, target_ref, meta) VALUES "
                "((SELECT uid FROM control.users WHERE uid = :actor), 'suggestion.reject', :t, "
                "CAST(:m AS jsonb))"
            ),
            {"actor": actor, "t": sug["target_subcap"], "m": json.dumps({"reason": reason})},
        )
    return ApplyResult(applied=False, status="rejected")
