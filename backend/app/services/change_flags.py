"""Change flags inbox (G3) — the human-review choke-point (CLAUDE.md safeguard 2 + 9).

Spec: "Route any gate failure to change_flag with the gate id." A change flag is an anomaly a pillar
lead must resolve before the queue can be trusted; nothing auto-acts. This slice generates the real,
grounded class of anomaly in the v7 corpus: **contradicted-evidence** flags — a subcap whose
lifecycle is ``declining``/``fading``/``dead`` while the delivery corpus shows active delivery. The
delivery evidence contradicts the lifecycle classification (a genuine **G6** contradiction), so the
gate fails and the anomaly is queued, never silently dropped.

Each flag carries a reasoning chain + a citation + the failing **G6** gate run (so it lights up the
Gates log and the reasoning modal). ``approve`` RE-GATES the proposed correction server-side: the
correction (→ ``stable``, grounded in the active delivery) resolves the contradiction, so G1-G8 pass
and the edit is applied to ``cat_<v>`` with an immutable ``audit_log`` row — in ONE transaction. A
re-gate that still fails writes nothing and keeps the flag open with the new failing gate named;
``reject`` needs a reason; ``defer`` snoozes it. Hermetic-deterministic (no spend).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app import db
from app.intelligence import gates
from app.services.suggestions import _catalogue_evidence
from app.versioning import resolve_version

_SCHEMA_RE = re.compile(r"^cat_[a-z0-9_]+$")
_KIND = "contradicted_evidence"
_CONTRADICTED_STATES = ("declining", "fading", "dead")
_CORRECTED_STATE = "stable"
_GATE = "G6_contradiction"


def _severity(stories: int) -> str:
    """Rank by delivery magnitude — the louder the contradicted delivery, the more urgent."""
    if stories >= 150:
        return "BLOCKING"
    if stories >= 100:
        return "HIGH"
    if stories >= 50:
        return "MED"
    return "LOW"


def _age(seconds: float | int | None) -> str:
    """Human-readable relative age (matches the prototype's '5m' / '1h' / '2d')."""
    s = int(seconds or 0)
    if s < 60:
        return "just now"
    if s < 3600:
        return f"{s // 60}m"
    if s < 86400:
        return f"{s // 3600}h"
    return f"{s // 86400}d"


@dataclass
class FlagRow:
    id: str
    sev: str
    kind: str
    age: str
    chain: str | None
    title: str
    body: str
    target: str | None
    name: str | None
    pillar: str | None
    gate_failed: str | None
    before: str | None
    after: str | None
    stories: int
    status: str


@dataclass
class FlagList:
    flags: list[FlagRow]
    counts: dict[str, int]


@dataclass
class FlagResult:
    resolved: bool
    status: str
    gate_failed: str | None = None
    before: str | None = None
    after: str | None = None


async def scan(version: str, min_stories: int = 25) -> dict[str, Any]:
    """Detect lifecycle-vs-delivery contradictions and queue them as change flags (idempotent).

    A subcap classified ``declining``/``fading``/``dead`` but with >= ``min_stories`` delivered
    stories contradicts the corpus. We write the failing G6 gate run + a reasoning chain and a
    change_flag; the proposed correction (→ ``stable``) is what a pillar lead approves.
    """
    v = await resolve_version(version)
    schema = v.schema_name
    if not _SCHEMA_RE.match(schema):
        raise ValueError("invalid version schema")
    engine = db.require_engine()

    states = ", ".join(f"'{s}'" for s in _CONTRADICTED_STATES)
    async with engine.begin() as conn:
        candidates = (
            (
                await conn.execute(
                    text(
                        "SELECT s.subcap_id, s.name, left(s.subcap_id, 2) AS pillar, "
                        "s.lifecycle_state, sc.stories "
                        "FROM (SELECT subcap_id, count(*) AS stories "
                        "FROM control.story_catalogue_link "
                        "WHERE version_id = :ver GROUP BY subcap_id) sc "
                        f"JOIN {schema}.subcap s ON s.subcap_id = sc.subcap_id "
                        f"WHERE s.lifecycle_state IN ({states}) AND sc.stories >= :min "
                        "AND NOT EXISTS (SELECT 1 FROM control.change_flag cf "
                        "WHERE cf.target_ref = s.subcap_id AND cf.kind = :kind) "
                        "ORDER BY sc.stories DESC, s.subcap_id"
                    ),
                    {"ver": v.version_id, "min": min_stories, "kind": _KIND},
                )
            )
            .mappings()
            .all()
        )

        created = 0
        for c in candidates:
            await _create_flag(conn, c, v.version_id)
            created += 1
    return {"version": v.version_id, "created": created, "candidates": len(candidates)}


async def _create_flag(conn: AsyncConnection, c: Any, version_id: str) -> None:
    stories = int(c["stories"])
    state = c["lifecycle_state"]
    name = c["name"]
    subcap_id = c["subcap_id"]
    results, verdict = gates.evaluate_suggestion(
        target_exists=True,
        evidence_count=stories,
        source_tier="T1",
        cited=True,
        contradicts=True,  # active delivery contradicts a declining/dead lifecycle — G6 fails
        cost_usd=0.0,
    )
    title = f"Active delivery contradicts the '{state}' lifecycle for {name}"
    body = (
        f"{stories} delivered stories map to {subcap_id}, yet its lifecycle is '{state}'. "
        f"Sustained delivery contradicts a {state} classification — G6 flagged it. "
        f"Proposed correction: set the lifecycle to '{_CORRECTED_STATE}', grounded in the corpus."
    )
    summary = (
        f"Delivery-vs-lifecycle contradiction on {subcap_id}: " f"{stories} stories vs '{state}'."
    )
    chain_id = (
        await conn.execute(
            text(
                "INSERT INTO control.reasoning_chain "
                "(operation, subject_ref, claim_label, summary, model, cost_usd) "
                "VALUES ('contradiction', :subj, 'INFERENCE', :summary, 'hermetic-stub', 0) "
                "RETURNING chain_id"
            ),
            {"subj": title, "summary": summary},
        )
    ).scalar_one()
    ev = await _catalogue_evidence(conn, subcap_id, name)
    await conn.execute(
        text(
            "INSERT INTO control.reasoning_step (chain_id, ordinal, kind, text, evidence_id) "
            "VALUES (:c, 1, 'retrieve', :t, :e)"
        ),
        {"c": chain_id, "t": f"{stories} delivery stories carried onto {subcap_id}.", "e": ev},
    )
    await conn.execute(
        text(
            "INSERT INTO control.reasoning_step (chain_id, ordinal, kind, text) "
            "VALUES (:c, 2, 'weigh', :t)"
        ),
        {
            "c": chain_id,
            "t": (
                f"The lifecycle says '{state}' but the delivery corpus shows active, sustained "
                "delivery — the two disagree."
            ),
        },
    )
    await conn.execute(
        text(
            "INSERT INTO control.reasoning_step (chain_id, ordinal, kind, text) "
            "VALUES (:c, 3, 'conclude', :t)"
        ),
        {
            "c": chain_id,
            "t": (
                f"Route to a pillar lead. Proposed correction: '{state}' -> '{_CORRECTED_STATE}', "
                "or reject if the delivery is legacy wind-down."
            ),
        },
    )
    await conn.execute(
        text(
            "INSERT INTO control.citation (chain_id, evidence_id, verified) VALUES (:c, :e, true)"
        ),
        {"c": chain_id, "e": ev},
    )
    await conn.execute(
        text(
            "INSERT INTO control.validation_gate_run (chain_id, target_ref, gate_results, verdict) "
            "VALUES (:c, :t, CAST(:r AS jsonb), CAST(:v AS gate_verdict))"
        ),
        {"c": chain_id, "t": subcap_id, "r": json.dumps(results), "v": verdict},
    )
    detail = {
        "title": title,
        "body": body,
        "name": name,
        "pillar": c["pillar"],
        "version": version_id,
        "gate_failed": gates.first_failing(results) or _GATE,
        "stories": stories,
        "lifecycle_state": state,
        "before": {"lifecycle_state": state},
        "after": {"lifecycle_state": _CORRECTED_STATE},
    }
    await conn.execute(
        text(
            "INSERT INTO control.change_flag (kind, severity, target_ref, detail, chain_id) "
            "VALUES (:k, :sev, :t, CAST(:d AS jsonb), :c)"
        ),
        {
            "k": _KIND,
            "sev": _severity(stories),
            "t": subcap_id,
            "d": json.dumps(detail),
            "c": chain_id,
        },
    )


# ---------------------------------------------------------------------------- decay analysis
# Two decay classes (user definition): a subcap is decayed if it has NO real Jira delivery, OR it
# was genuinely removed from a previous version. Both raise change flags so an admin can decide
# whether to mark the subcap inactive — nothing is ever auto-deactivated.
_DECAY_KIND = "decay_missing_subcap"  # removed-from-previous (kept stable for existing rows)
_DECAY_NO_DELIVERY = "decay_no_delivery"  # in this version but zero real Jira stories
_INACTIVE_STATE = "dead"  # "mark inactive" target lifecycle
_LIVE_STATES = ("emerging", "rising", "stable")  # believed active -> decay is the real decision
_NO_DELIVERY_CAP = 1000  # generous: surface ALL decayed subcaps (v7 ~765) in one scan
_NEAR_DESC = 0.4  # token-overlap >= this = "descriptions near in meaning" (hermetic proxy)


def _tokens(name: str | None) -> set[str]:
    return {t for t in re.sub(r"[^a-z0-9 ]", " ", (name or "").lower()).split() if len(t) > 2}


def _jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if (a or b) else 1.0  # both empty => identical (vacuously near)


def _desc_near(a: str | None, b: str | None) -> bool:
    """Deterministic 'description nearing by meaning' proxy (token overlap). Live mode can upgrade
    this to embedding cosine over the shared vector(768) space; the contract is identical."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta and not tb:
        return True  # neither has a description -> can't say they diverged
    return _jaccard(ta, tb) >= _NEAR_DESC


def _decay_severity(life: str) -> str:
    """Decayed subcaps are HIGH alerts for the admin to action (mark inactive or keep): a subcap we
    BELIEVE is live (emerging/rising/stable) yet has zero delivery is the urgent case (HIGH); one
    already winding down (declining/fading) is consistent decay, still actionable (MED)."""
    return "HIGH" if life in _LIVE_STATES else "MED"


async def scan_decay(version: str, no_delivery_cap: int = _NO_DELIVERY_CAP) -> dict[str, Any]:
    """DECAY analysis -> change flags for the admin (explained, never auto-acted). Two classes:

    A) NO-DELIVERY decay — a subcap in this version with ZERO real Jira stories (synthetic never
       counts). It may stay active, but it is a candidate to mark INACTIVE; each flag proposes
       lifecycle -> 'dead' for the admin to approve or reject. This is the bulk (v7: almost all).
    B) REMOVED decay — a subcap present in the PREVIOUS version but genuinely gone now. Refined
       (user rule): a previous subcap counts as removed ONLY if neither its subcap-id NOR its L2
       capability name survives with a near description. A rename/reassignment/integration (same
       id or same L2 name + near description) is NOT a removal and raises no flag.
    """
    v = await resolve_version(version)
    schema = v.schema_name
    if not _SCHEMA_RE.match(schema):
        raise ValueError("invalid version schema")
    engine = db.require_engine()
    async with engine.begin() as conn:
        nod = await _scan_no_delivery(conn, schema, v.version_id, no_delivery_cap)
        rem = await _scan_removed(conn, schema, v.version_id)
    return {
        "version": v.version_id,
        "created": nod["created"] + rem["created"],
        "candidates": nod["candidates"] + rem["candidates"],
        "no_delivery": nod,
        "removed": rem,
    }


async def _scan_no_delivery(
    conn: AsyncConnection, schema: str, version_id: str, cap: int
) -> dict[str, Any]:
    """Flag every current subcap with no real Jira delivery as a candidate to mark inactive."""
    rows = (
        (
            await conn.execute(
                text(
                    "SELECT s.subcap_id, s.name, s.lifecycle_state, cap.name AS l2, "
                    "left(s.subcap_id, 2) AS pillar "
                    f"FROM {schema}.subcap s "
                    f"JOIN {schema}.capability cap ON cap.capability_id = s.capability_id "
                    "WHERE s.lifecycle_state <> :dead "
                    "AND NOT EXISTS (SELECT 1 FROM control.story_catalogue_link l "
                    "WHERE l.version_id = :ver AND l.subcap_id = s.subcap_id) "
                    "AND NOT EXISTS (SELECT 1 FROM control.change_flag cf "
                    "WHERE cf.kind = :k AND cf.target_ref = s.subcap_id) "
                    # believed-live first (the real decision), then leverage tier, then id
                    "ORDER BY (s.lifecycle_state IN ('emerging','rising','stable')) DESC, "
                    "s.tier NULLS LAST, s.subcap_id"
                ),
                {"dead": _INACTIVE_STATE, "ver": version_id, "k": _DECAY_NO_DELIVERY},
            )
        )
        .mappings()
        .all()
    )
    created = 0
    for r in rows[:cap]:
        life = str(r["lifecycle_state"])
        detail = {
            "title": f"Decayed (no Jira delivery): {r['name']}",
            "body": (
                f"{r['subcap_id']} has zero real Jira stories in {version_id} (synthetic delivery "
                f"is excluded by construction). It currently reads '{life}'. A decayed subcap can "
                "stay active — approve to mark it INACTIVE (lifecycle -> 'dead'), or reject to "
                "keep it. Nothing is deactivated automatically."
            ),
            "name": r["name"],
            "pillar": r["pillar"],
            "l2": r["l2"],
            "version": version_id,
            "explanation": "No real Jira story links to this subcap (decay candidate).",
            "before": {"lifecycle_state": life},
            "after": {"lifecycle_state": _INACTIVE_STATE},
        }
        await conn.execute(
            text(
                "INSERT INTO control.change_flag (kind, severity, target_ref, detail) "
                "VALUES (:k, :sev, :t, CAST(:d AS jsonb))"
            ),
            {
                "k": _DECAY_NO_DELIVERY,
                "sev": _decay_severity(life),
                "t": r["subcap_id"],
                "d": json.dumps(detail),
            },
        )
        created += 1
    return {"created": created, "candidates": len(rows), "flagged_cap": cap}


async def _scan_removed(conn: AsyncConnection, schema: str, version_id: str) -> dict[str, Any]:
    """Flag previous-version subcaps that are GENUINELY removed (refined id+L2-name+desc rule)."""
    prev = (
        await conn.execute(
            text(
                "SELECT version_id, schema_name FROM control.catalogue_version "
                "WHERE status IN ('active','provisioned') AND version_id <> :v "
                "AND coalesce(nullif(regexp_replace(version_id,'[^0-9]','','g'),'')::int,0) < "
                "coalesce((SELECT nullif(regexp_replace(version_id,'[^0-9]','','g'),'')::int "
                "FROM control.catalogue_version WHERE version_id = :v), 0) "
                "ORDER BY coalesce(nullif(regexp_replace(version_id,'[^0-9]','','g'),'')"
                "::int, 0) DESC LIMIT 1"
            ),
            {"v": version_id},
        )
    ).first()
    if prev is None or not _SCHEMA_RE.match(str(prev[1])):
        return {"created": 0, "candidates": 0, "note": "no previous version"}
    prev_ver, prev_schema = str(prev[0]), str(prev[1])
    cur = {str(r[0]): (str(r[1]), str(r[2]), r[3]) for r in await _subcaps_with_l2(conn, schema)}
    old = {
        str(r[0]): (str(r[1]), str(r[2]), r[3]) for r in await _subcaps_with_l2(conn, prev_schema)
    }
    cur_names = {n.strip().lower() for (n, _l2, _d) in cur.values()}
    cur_l2 = {l2.strip().lower(): (n, d) for (n, l2, d) in cur.values()}
    missing = sorted(set(old) - set(cur))
    created, genuinely_removed = 0, 0
    for sid in missing:
        name, l2, desc = old[sid]
        # SUCCESSOR test (refined user rule): same subcap name, OR same L2 capability name with a
        # near description => the subcap carried over (rename / reassignment / integration), so it
        # is NOT a removal and raises no flag.
        if name.strip().lower() in cur_names:
            continue
        l2hit = cur_l2.get(l2.strip().lower())
        if l2hit and _desc_near(desc, l2hit[1]):
            continue
        genuinely_removed += 1
        if (
            await conn.execute(
                text("SELECT 1 FROM control.change_flag WHERE kind = :k AND target_ref = :t"),
                {"k": _DECAY_KIND, "t": sid},
            )
        ).first():
            continue
        explanation = (
            f"Neither the id {sid} nor its L2 capability '{l2}' survives in {version_id} with a "
            "near description — a genuine removal (deduped or dropped at source), not a rename. "
            "A human should confirm whether anything must move."
        )
        detail = {
            "title": f"Decayed (removed): {sid} '{name}'",
            "body": f"Present in {prev_ver}, gone from {version_id}. {explanation}",
            "name": name,
            "pillar": sid[:2],
            "l2": l2,
            "version": version_id,
            "previous_version": prev_ver,
            "explanation": explanation,
        }
        await conn.execute(
            text(
                "INSERT INTO control.change_flag (kind, severity, target_ref, detail) "
                "VALUES (:k, 'MED', :t, CAST(:d AS jsonb))"
            ),
            {"k": _DECAY_KIND, "t": sid, "d": json.dumps(detail)},
        )
        created += 1
    return {
        "created": created,
        "candidates": genuinely_removed,
        "missing_total": len(missing),
        "previous_version": prev_ver,
    }


async def _subcaps_with_l2(conn: AsyncConnection, schema: str) -> Any:
    return await conn.execute(
        text(
            "SELECT s.subcap_id, s.name, cap.name AS l2, s.description "
            f"FROM {schema}.subcap s "
            f"JOIN {schema}.capability cap ON cap.capability_id = s.capability_id"
        )
    )


def _flag_row(m: dict[str, Any]) -> FlagRow:
    d = m["detail"] or {}
    before = (d.get("before") or {}).get("lifecycle_state")
    after = (d.get("after") or {}).get("lifecycle_state")
    return FlagRow(
        id=str(m["flag_id"]),
        sev=m["severity"],
        kind=m["kind"],
        age=_age(m["age_s"]),
        chain=str(m["chain_id"]) if m["chain_id"] else None,
        title=d.get("title", m["kind"]),
        body=d.get("body", ""),
        target=m["target_ref"],
        name=d.get("name"),
        pillar=d.get("pillar"),
        gate_failed=d.get("gate_failed"),
        before=before,
        after=after,
        stories=int(d.get("stories", 0)),
        status=m["status"],
    )


async def list_flags(status: str = "open") -> FlagList:
    engine = db.get_engine()
    if engine is None:
        return FlagList(flags=[], counts={"BLOCKING": 0, "HIGH": 0, "MED": 0, "LOW": 0})
    where = "WHERE status = :s" if status else ""
    async with engine.connect() as conn:
        rows = (
            (
                await conn.execute(
                    text(
                        "SELECT flag_id, kind, severity, target_ref, detail, chain_id, "
                        "status, extract(epoch FROM (now() - created_at))::bigint AS age_s "
                        f"FROM control.change_flag {where} "
                        "ORDER BY CASE severity WHEN 'BLOCKING' THEN 0 WHEN 'HIGH' THEN 1 "
                        "WHEN 'MED' THEN 2 ELSE 3 END, created_at DESC"
                    ),
                    {"s": status} if status else {},
                )
            )
            .mappings()
            .all()
        )
        count_rows = (
            (
                await conn.execute(
                    text(
                        "SELECT severity, count(*) AS n FROM control.change_flag "
                        "WHERE status = 'open' GROUP BY severity"
                    )
                )
            )
            .mappings()
            .all()
        )
    counts = {"BLOCKING": 0, "HIGH": 0, "MED": 0, "LOW": 0}
    for cr in count_rows:
        counts[cr["severity"]] = int(cr["n"])
    return FlagList(flags=[_flag_row(dict(r)) for r in rows], counts=counts)


async def _audit(
    conn: AsyncConnection, actor: str, action: str, target: str | None, meta: dict[str, Any]
) -> None:
    await conn.execute(
        text(
            "INSERT INTO control.audit_log (actor, action, target_ref, meta) VALUES "
            "((SELECT uid FROM control.users WHERE uid = :actor), :action, :t, CAST(:m AS jsonb))"
        ),
        {"actor": actor, "action": action, "t": target, "m": json.dumps(meta)},
    )


async def approve(flag_id: str, actor: str) -> FlagResult:
    """Re-gate the proposed correction; if G1-G8 pass, apply to cat_<v> + audit, all-or-nothing."""
    engine = db.require_engine()
    async with engine.begin() as conn:
        flag = await _flag_for_update(conn, flag_id)
        if flag is None:
            return FlagResult(resolved=False, status="not_found")
        if flag["status"] != "open":
            return FlagResult(resolved=False, status=flag["status"])
        detail = flag["detail"] or {}
        target = flag["target_ref"]

        # REMOVED-from-previous decay: the subcap is gone from cat_<v> — there is nothing to
        # mutate. Approving ACKNOWLEDGES the removal (audited), it never re-creates a row.
        if flag["kind"] == _DECAY_KIND:
            await _audit(
                conn,
                actor,
                "change_flag.approve",
                target,
                {"flag_id": flag_id, "acknowledged": "removal", "version": detail.get("version")},
            )
            await conn.execute(
                text(
                    "UPDATE control.change_flag SET status = 'approved', resolved_at = now() "
                    "WHERE flag_id = :id"
                ),
                {"id": flag_id},
            )
            return FlagResult(resolved=True, status="approved")

        if flag["kind"] not in (_KIND, _DECAY_NO_DELIVERY):
            # Evidence-gate failures (F7 ingest) have no lifecycle correction to apply; the
            # source must be fixed or the item rejected. Stays open, failing gate named, and
            # no re-gate run is written (there is nothing to re-gate).
            return FlagResult(
                resolved=False,
                status="open",
                gate_failed=(flag["detail"] or {}).get("gate_failed"),
            )

        v = await resolve_version(str(detail.get("version") or ""))
        schema = v.schema_name
        if not _SCHEMA_RE.match(schema):
            raise ValueError("invalid version schema")
        current = (
            await conn.execute(
                text(f"SELECT lifecycle_state FROM {schema}.subcap WHERE subcap_id = :t"),
                {"t": target},
            )
        ).scalar()
        stories = int(
            (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM control.story_catalogue_link "
                        "WHERE version_id = :ver AND subcap_id = :t"
                    ),
                    {"ver": v.version_id, "t": target},
                )
            ).scalar()
            or 0
        )
        if flag["kind"] == _DECAY_NO_DELIVERY:
            # Marking a decayed subcap INACTIVE is grounded in the corpus-scan absence (catalogue
            # record + the zero-delivery measurement = 2 sources). The grounded self-check: if
            # delivery has since appeared, the decay premise is gone — G6 fails and nothing is
            # marked inactive (the flag stays open, naming the contradiction).
            results, verdict = gates.evaluate_suggestion(
                target_exists=current is not None,
                evidence_count=2,
                source_tier="T1",
                cited=True,
                contradicts=stories > 0,
                cost_usd=0.0,
            )
        else:
            # contradicted_evidence: the correction (-> 'stable') resolves the contradiction
            # (active delivery now agrees with the state).
            results, verdict = gates.evaluate_suggestion(
                target_exists=current is not None,
                evidence_count=stories,
                source_tier="T1",
                cited=True,
                contradicts=False,
                cost_usd=0.0,
            )
        await conn.execute(
            text(
                "INSERT INTO control.validation_gate_run "
                "(chain_id, target_ref, gate_results, verdict) "
                "VALUES (:c, :t, CAST(:r AS jsonb), CAST(:v AS gate_verdict))"
            ),
            {
                "c": flag["chain_id"],
                "t": target,
                "r": json.dumps(results),
                "v": verdict,
            },
        )
        if verdict != "pass":
            # Failed re-gate writes nothing; flag stays open, naming the new failing gate.
            return FlagResult(
                resolved=False, status="open", gate_failed=gates.first_failing(results)
            )

        after = (detail.get("after") or {}).get("lifecycle_state", _CORRECTED_STATE)
        before = str(current)
        await conn.execute(
            text(f"UPDATE {schema}.subcap SET lifecycle_state = :a WHERE subcap_id = :t"),
            {"a": after, "t": target},
        )
        await _audit(
            conn,
            actor,
            "change_flag.approve",
            target,
            {
                "flag_id": flag_id,
                "before": before,
                "after": after,
                "chain_id": str(flag["chain_id"]) if flag["chain_id"] else None,
                "verdict": verdict,
                "snapshot_ref": f"audit:{target}:{before}",
            },
        )
        await conn.execute(
            text(
                "UPDATE control.change_flag SET status = 'approved', resolved_at = now() "
                "WHERE flag_id = :id"
            ),
            {"id": flag_id},
        )
    return FlagResult(resolved=True, status="approved", before=before, after=after)


async def _flag_for_update(conn: AsyncConnection, flag_id: str) -> Any:
    return (
        (
            await conn.execute(
                text(
                    "SELECT target_ref, detail, status, chain_id, kind "
                    "FROM control.change_flag WHERE flag_id = :id FOR UPDATE"
                ),
                {"id": flag_id},
            )
        )
        .mappings()
        .first()
    )


async def reject(flag_id: str, reason: str, actor: str) -> FlagResult:
    if not reason.strip():
        raise ValueError("a rejection reason is required")
    engine = db.require_engine()
    async with engine.begin() as conn:
        flag = await _flag_for_update(conn, flag_id)
        if flag is None:
            return FlagResult(resolved=False, status="not_found")
        if flag["status"] != "open":
            return FlagResult(resolved=False, status=flag["status"])
        await conn.execute(
            text(
                "UPDATE control.change_flag SET status = 'rejected', "
                "detail = detail || CAST(:r AS jsonb), resolved_at = now() WHERE flag_id = :id"
            ),
            {"r": json.dumps({"reason": reason}), "id": flag_id},
        )
        await _audit(
            conn,
            actor,
            "change_flag.reject",
            flag["target_ref"],
            {"flag_id": flag_id, "reason": reason},
        )
    return FlagResult(resolved=False, status="rejected")


async def defer(flag_id: str, actor: str) -> FlagResult:
    engine = db.require_engine()
    async with engine.begin() as conn:
        flag = await _flag_for_update(conn, flag_id)
        if flag is None:
            return FlagResult(resolved=False, status="not_found")
        if flag["status"] != "open":
            return FlagResult(resolved=False, status=flag["status"])
        await conn.execute(
            text("UPDATE control.change_flag SET status = 'deferred' WHERE flag_id = :id"),
            {"id": flag_id},
        )
        await _audit(conn, actor, "change_flag.defer", flag["target_ref"], {"flag_id": flag_id})
    return FlagResult(resolved=False, status="deferred")
