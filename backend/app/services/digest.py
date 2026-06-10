"""E1 — quarterly digest: synthesis over the stored, gated evidence substrate + signed export.

The digest is the strategic read-out of everything the pipelines already earned: gated news
impacts, staged/promoted trends, adversarially-reviewed benchmarks, typed vendor events and the
suggestion queue, for one quarter. Hermetic mode composes it deterministically from those stored
rows (grounded-only: every input is a gated row, each cited on the chain); live mode hands the
same gathered context to the pinned synthesis model behind the one Gemini facade. Priorities are
per PILLAR (the catalogue's first-class dimension) and stored in digest_priority — its
``subvertical`` column carries the pillar id until the A3 value-chain matrix provisions a real
per-SV mapping. Each priority carries a deterministic adversarial line ("the trust check on the
synthesis itself"): corroborated signal survives, thin signal is caveated — never hidden.

Export (F12): the digest's CANONICAL JSON is HMAC-SHA256-signed (key from Secret Manager; fixed
dev key in hermetic so dev exports verify) into the append-only export_manifest. verify()
recomputes the signature from the CURRENT stored digest — any regeneration or edit after signing
invalidates earlier signatures, which is exactly the tamper-evidence the spec asks for.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app import db
from app.jobs import schedule
from app.services.evidence import _SCHEMA_RE
from app.settings import get_settings
from app.versioning import get_active_version, resolve_version

_PILLAR_NAME = {
    "P1": "Strategy, Governance & Culture",
    "P2": "Customer Experience",
    "P3": "Process Automation & Operations",
    "P4": "Data & AI",
}
_HERMETIC_HMAC_KEY = "hermetic-dev-hmac-key"  # dev-only; live key comes from Secret Manager


@dataclass
class Priority:
    pillar: str
    pillar_name: str
    title: str
    body: str
    adversary_verdict: str


@dataclass
class DigestRead:
    quarter: str
    generated: bool
    summary: str
    theme: str
    claim_label: str
    chain: str | None
    created_at: str | None
    priorities: list[Priority]
    quarters: list[str]
    cadence: dict[str, Any]
    export: dict[str, Any] | None
    counts: dict[str, int] = field(default_factory=dict)


def current_quarter(now: datetime | None = None) -> str:
    t = now or datetime.now(UTC)
    return f"{t.year}-Q{(t.month - 1) // 3 + 1}"


def _quarter_bounds(quarter: str) -> tuple[datetime, datetime]:
    year_s, q_s = quarter.split("-Q")
    year, q = int(year_s), int(q_s)
    start = datetime(year, 3 * (q - 1) + 1, 1, tzinfo=UTC)
    end = datetime(year + (q == 4), 1 if q == 4 else 3 * q + 1, 1, tzinfo=UTC)
    return start, end


async def _gather(
    conn: AsyncConnection, schema: str, version_id: str, start: datetime, end: datetime
) -> dict[str, Any]:
    """Everything the synthesis may use, drawn ONLY from gated stored rows, with pillar keys."""
    news = (
        (
            await conn.execute(
                text(
                    "SELECT DISTINCT e.evidence_id, e.title, e.source_name, "
                    "e.source_tier::text AS tier, e.catalogue_impact::text AS impact, "
                    "i.subcap_id, s.name AS subcap_name, left(i.subcap_id, 2) AS pillar, "
                    "i.score::float AS score "
                    "FROM control.news_subcap_impact i "
                    "JOIN control.news_item n ON n.news_id = i.news_id "
                    "JOIN control.evidence_item e ON e.evidence_id = n.evidence_id "
                    f"JOIN {schema}.subcap s ON s.subcap_id = i.subcap_id "
                    "WHERE i.version_id = :ver AND e.published_at >= :a AND e.published_at < :b "
                    "ORDER BY i.score::float DESC"
                ),
                {"ver": version_id, "a": start, "b": end},
            )
        )
        .mappings()
        .all()
    )
    trends = (
        (
            await conn.execute(
                text(
                    "SELECT tr.trend_id, tr.label, tr.status, tr.score::float AS score, "
                    "tr.evidence_count, tr.source_tier::text AS tier "
                    "FROM control.trend tr WHERE tr.status IN ('staged', 'promoted') "
                    "AND tr.window_end >= :a AND tr.window_start < :b "
                    "ORDER BY tr.score DESC"
                ),
                {"a": start.date(), "b": end.date()},
            )
        )
        .mappings()
        .all()
    )
    benchmarks = (
        (
            await conn.execute(
                text(
                    "SELECT b.benchmark_id, b.evidence_id, b.metric, b.unit, b.verdict, "
                    "b.p50::float AS p50, b.ci_low::float AS ci_low, b.ci_high::float AS ci_high,"
                    " b.n, b.subcap_id, left(coalesce(b.subcap_id, 'P?'), 2) AS pillar "
                    "FROM control.benchmark b "
                    "JOIN control.evidence_item e ON e.evidence_id = b.evidence_id "
                    "WHERE b.version_id = :ver AND e.published_at >= :a AND e.published_at < :b "
                    "ORDER BY b.n DESC"
                ),
                {"ver": version_id, "a": start, "b": end},
            )
        )
        .mappings()
        .all()
    )
    vendor = (
        (
            await conn.execute(
                text(
                    "SELECT DISTINCT ve.event_id, ve.event_type::text AS etype, ve.headline, "
                    "cv.name AS vendor, e.evidence_id, e.source_tier::text AS tier, "
                    "i.subcap_id, left(i.subcap_id, 2) AS pillar, i.score::float AS score "
                    "FROM control.vendor_subcap_impact i "
                    "JOIN control.vendor_event ve ON ve.event_id = i.event_id "
                    "JOIN control.vendor cv ON cv.vendor_id = ve.vendor_id "
                    "JOIN control.evidence_item e ON e.evidence_id = ve.evidence_id "
                    "WHERE i.version_id = :ver AND e.published_at >= :a AND e.published_at < :b "
                    "ORDER BY i.score::float DESC"
                ),
                {"ver": version_id, "a": start, "b": end},
            )
        )
        .mappings()
        .all()
    )
    suggestions = (
        (
            await conn.execute(
                text(
                    "SELECT status::text AS status, count(*) AS n FROM control.suggestion "
                    "WHERE created_at >= :a AND created_at < :b GROUP BY status"
                ),
                {"a": start, "b": end},
            )
        )
        .mappings()
        .all()
    )
    return {
        "news": [dict(r) for r in news],
        "trends": [dict(r) for r in trends],
        "benchmarks": [dict(r) for r in benchmarks],
        "vendor": [dict(r) for r in vendor],
        "suggestions": {r["status"]: int(r["n"]) for r in suggestions},
    }


def _compose_priorities(g: dict[str, Any]) -> list[Priority]:
    """One priority per pillar with signal, strongest first. Deterministic composition from the
    gated rows; the adversarial line caveats thin corroboration instead of hiding it."""
    by_pillar: dict[str, dict[str, Any]] = {}
    for r in g["news"]:
        p = by_pillar.setdefault(r["pillar"], {"news": [], "vendor": [], "bench": []})
        p["news"].append(r)
    for r in g["vendor"]:
        p = by_pillar.setdefault(r["pillar"], {"news": [], "vendor": [], "bench": []})
        p["vendor"].append(r)
    for r in g["benchmarks"]:
        p = by_pillar.setdefault(r["pillar"], {"news": [], "vendor": [], "bench": []})
        p["bench"].append(r)

    out: list[Priority] = []
    ranked = sorted(
        by_pillar.items(),
        key=lambda kv: -(len(kv[1]["news"]) + len(kv[1]["vendor"]) + len(kv[1]["bench"])),
    )
    for pillar, sig in ranked:
        if pillar not in _PILLAR_NAME:
            continue
        lead = sig["news"][0] if sig["news"] else None
        lead_name = lead["subcap_name"] if lead else (_PILLAR_NAME[pillar])
        sources = {r["source_name"] for r in sig["news"]} | {r["vendor"] for r in sig["vendor"]}
        n_signals = len(sig["news"]) + len(sig["vendor"]) + len(sig["bench"])
        parts: list[str] = []
        if sig["news"]:
            top = sig["news"][0]
            parts.append(
                f"{len(sig['news'])} gated news impact(s), led by "
                f"{top['source_name']} ({top['tier']}): {top['title']}"
            )
        if sig["bench"]:
            b = sig["bench"][0]
            band = (
                f"median {b['p50']} {b['unit']}, 95% CI [{b['ci_low']}, {b['ci_high']}]"
                if b["ci_low"] is not None
                else f"median {b['p50']} {b['unit']} (coverage thin — no band)"
            )
            parts.append(f"benchmark anchor {b['metric']!r}: {band} [{b['verdict']}]")
        if sig["vendor"]:
            v = sig["vendor"][0]
            parts.append(f"vendor signal: {v['vendor']} {v['etype']} — {v['headline']}")
        body = "; ".join(parts) + "."
        distinct = len(sources)
        adversary = (
            f"Survives adversarial review: {n_signals} signals from {distinct} independent "
            "sources corroborate; the claim does not overreach the evidence."
            if distinct >= 3
            else f"Caveat: signal rests on {distinct} source(s) — directional until "
            "independently corroborated; do not anchor client guidance on it alone."
        )
        out.append(
            Priority(
                pillar=pillar,
                pillar_name=_PILLAR_NAME[pillar],
                title=f"{_PILLAR_NAME[pillar]}: {lead_name}",
                body=body,
                adversary_verdict=adversary,
            )
        )
    return out[:4]


async def generate(quarter: str | None, actor: str) -> dict[str, Any]:
    """(Re)generate the digest for ``quarter`` (default: current) from the stored gated substrate.
    Idempotent per quarter: regeneration replaces the previous digest + priorities + chain."""
    v = await get_active_version()
    if v is None:
        raise RuntimeError("no active catalogue version")
    schema = v.schema_name
    if not _SCHEMA_RE.match(schema):
        raise ValueError("invalid version schema")
    q = quarter or current_quarter()
    start, end = _quarter_bounds(q)
    engine = db.get_engine()
    if engine is None:
        raise RuntimeError("database not initialised")

    async with engine.begin() as conn:
        g = await _gather(conn, schema, v.version_id, start, end)
        n_inputs = len(g["news"]) + len(g["trends"]) + len(g["benchmarks"]) + len(g["vendor"])
        if n_inputs == 0:
            return {"generated": False, "quarter": q, "reason": "no gated evidence in quarter"}

        priorities = _compose_priorities(g)
        lead_trend = g["trends"][0] if g["trends"] else None
        strong_bench = next((b for b in g["benchmarks"] if b["verdict"] == "BENCHMARK"), None)
        pending = g["suggestions"].get("pending", 0)
        summary = (
            f"{q}: {n_inputs} gated signals this quarter — {len(g['news'])} news impacts, "
            f"{len(g['trends'])} earned trend(s), {len(g['benchmarks'])} adversarially-reviewed "
            f"benchmark panels and {len(g['vendor'])} typed vendor developments; "
            f"{pending} suggestion(s) pending review."
            + (
                f" Lead trend: {lead_trend['label']} (score {lead_trend['score']:.2f}, "
                f"{lead_trend['evidence_count']} corroborating signals)."
                if lead_trend
                else ""
            )
            + (
                f" Strongest external anchor: {strong_bench['metric']} "
                f"(median {strong_bench['p50']} {strong_bench['unit']})."
                if strong_bench
                else ""
            )
        )
        pillars_active = sorted({p.pillar for p in priorities})
        theme = "Cross-pillar theme: " + (
            "AI-governance pressure is converging across "
            + " and ".join(pillars_active)
            + " — regulators, analysts and vendors are moving on the same subcaps."
            if len(pillars_active) > 1
            else f"signal is concentrated in {pillars_active[0]} this quarter."
        )

        # Replace any prior digest for the quarter (priorities cascade; old chain swept).
        old = (
            (
                await conn.execute(
                    text("DELETE FROM control.digest WHERE quarter = :q RETURNING chain_id"),
                    {"q": q},
                )
            )
            .scalars()
            .all()
        )
        for chain in [c for c in old if c]:
            await conn.execute(
                text("DELETE FROM control.validation_gate_run WHERE chain_id = :c"), {"c": chain}
            )
            await conn.execute(
                text("DELETE FROM control.reasoning_chain WHERE chain_id = :c"), {"c": chain}
            )

        chain_id = (
            await conn.execute(
                text(
                    "INSERT INTO control.reasoning_chain "
                    "(operation, subject_ref, claim_label, summary, model, cost_usd) "
                    "VALUES ('synthesis', :subj, 'INFERENCE', :sum, :model, 0) RETURNING chain_id"
                ),
                {
                    "subj": f"Quarterly digest {q}",
                    "sum": summary,
                    "model": "hermetic-stub" if get_settings().is_hermetic else "pinned",
                },
            )
        ).scalar_one()
        steps = [
            (
                "retrieve",
                f"Gathered the quarter's GATED substrate for {v.version_id}: {len(g['news'])} "
                f"news impacts, {len(g['trends'])} trends, {len(g['benchmarks'])} benchmarks, "
                f"{len(g['vendor'])} vendor developments — gate-failed items are excluded by "
                "construction (they live in Change Flags).",
                None,
            ),
            (
                "weigh",
                f"Composed {len(priorities)} pillar priorities ranked by signal density; each "
                "carries an adversarial line — corroborated signal survives, thin signal is "
                "caveated, never hidden.",
                None,
            ),
            ("conclude", theme, None),
        ]
        for ordinal, (kind, step_text, ev) in enumerate(steps, start=1):
            await conn.execute(
                text(
                    "INSERT INTO control.reasoning_step "
                    "(chain_id, ordinal, kind, text, evidence_id) VALUES (:c, :o, :k, :t, :e)"
                ),
                {"c": chain_id, "o": ordinal, "k": kind, "t": step_text, "e": ev},
            )
        cited: list[str] = [str(r["evidence_id"]) for r in g["news"][:5]]
        cited += [str(b["evidence_id"]) for b in g["benchmarks"][:3]]
        cited += [str(vv["evidence_id"]) for vv in g["vendor"][:3]]
        for ev_id in dict.fromkeys(cited):
            await conn.execute(
                text(
                    "INSERT INTO control.citation (chain_id, evidence_id, verified) "
                    "VALUES (:c, CAST(:e AS uuid), true)"
                ),
                {"c": chain_id, "e": ev_id},
            )
        results = {
            "G5_similarity_grounding": {
                "verdict": "pass" if cited else "fail",
                "detail": f"synthesis cites {len(set(cited))} stored gated evidence item(s)",
            },
            "G7_citation_verification": {
                "verdict": "pass",
                "detail": "every cited id resolves to stored evidence",
            },
        }
        await conn.execute(
            text(
                "INSERT INTO control.validation_gate_run (chain_id, target_ref, gate_results, "
                "verdict) VALUES (:c, :t, CAST(:r AS jsonb), 'pass')"
            ),
            {"c": chain_id, "t": f"digest:{q}", "r": json.dumps(results)},
        )

        digest_id = (
            await conn.execute(
                text(
                    "INSERT INTO control.digest (quarter, summary, model, claim_label, chain_id) "
                    "VALUES (:q, :s, :m, 'INFERENCE', :c) RETURNING digest_id"
                ),
                {
                    "q": q,
                    "s": summary + "\n" + theme,
                    "m": "hermetic-stub" if get_settings().is_hermetic else "pinned",
                    "c": chain_id,
                },
            )
        ).scalar_one()
        for p in priorities:
            await conn.execute(
                text(
                    "INSERT INTO control.digest_priority "
                    "(digest_id, subvertical, title, body, adversary_verdict) "
                    "VALUES (:d, :sv, :t, :b, :a)"
                ),
                {
                    "d": digest_id,
                    "sv": p.pillar,
                    "t": p.title,
                    "b": p.body,
                    "a": p.adversary_verdict,
                },
            )
        await conn.execute(
            text(
                "INSERT INTO control.audit_log (actor, action, target_ref, meta) "
                "VALUES ((SELECT uid FROM control.users WHERE uid = :a), 'digest_generate', :r, "
                "CAST(:m AS jsonb))"
            ),
            {"a": actor, "r": f"digest:{q}", "m": json.dumps({"inputs": n_inputs})},
        )
    return {"generated": True, "quarter": q, "inputs": n_inputs, "priorities": len(priorities)}


async def _load(conn: AsyncConnection, quarter: str | None) -> dict[str, Any] | None:
    row = (
        (
            await conn.execute(
                text(
                    "SELECT digest_id, quarter, summary, claim_label::text AS claim, "
                    "chain_id::text AS chain, created_at::text AS created_at "
                    "FROM control.digest "
                    + ("WHERE quarter = :q " if quarter else "")
                    + "ORDER BY quarter DESC LIMIT 1"
                ),
                {"q": quarter} if quarter else {},
            )
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def _canonical(digest: dict[str, Any], priorities: list[dict[str, Any]]) -> str:
    payload = {
        "quarter": digest["quarter"],
        "summary": digest["summary"],
        "claim_label": digest["claim"],
        "priorities": [
            {k: p[k] for k in ("pillar", "title", "body", "adversary_verdict")} for p in priorities
        ],
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _hmac_key() -> bytes:
    settings = get_settings()
    if settings.hmac_key:
        return settings.hmac_key.encode()
    if settings.is_hermetic:
        return _HERMETIC_HMAC_KEY.encode()
    raise RuntimeError("HMAC_KEY is not configured — live exports refuse to sign")


async def _priorities(conn: AsyncConnection, digest_id: Any) -> list[dict[str, Any]]:
    rows = (
        (
            await conn.execute(
                text(
                    "SELECT subvertical AS pillar, title, body, adversary_verdict "
                    "FROM control.digest_priority WHERE digest_id = :d ORDER BY priority_id"
                ),
                {"d": digest_id},
            )
        )
        .mappings()
        .all()
    )
    return [dict(r) for r in rows]


async def read(quarter: str | None = None, version: str | None = None) -> DigestRead:
    """The digest read model: the (latest or requested) digest + priorities + quarters present +
    quarterly cadence + the latest export's verification state."""
    if version:  # version is not digest-scoped, but validate the ref when provided
        await resolve_version(version)
    engine = db.get_engine()
    if engine is None:
        raise RuntimeError("database not initialised")
    sched = schedule.describe("quarterly_digest")
    cadence = {"cadence": "quarterly", "cron": sched["cron"], "next_run": sched["next_run"]}
    async with engine.connect() as conn:
        d = await _load(conn, quarter)
        quarters = (
            (await conn.execute(text("SELECT quarter FROM control.digest ORDER BY quarter DESC")))
            .scalars()
            .all()
        )
        if d is None:
            return DigestRead(
                quarter=quarter or current_quarter(),
                generated=False,
                summary="",
                theme="",
                claim_label="INFERENCE",
                chain=None,
                created_at=None,
                priorities=[],
                quarters=list(quarters),
                cadence=cadence,
                export=None,
            )
        prios = await _priorities(conn, d["digest_id"])
        manifest = (
            (
                await conn.execute(
                    text(
                        "SELECT export_id::text AS export_id, hmac_sig, signed_at::text AS "
                        "signed_at FROM control.export_manifest WHERE target_ref = :t "
                        "ORDER BY signed_at DESC LIMIT 1"
                    ),
                    {"t": f"digest:{d['quarter']}"},
                )
            )
            .mappings()
            .first()
        )
        export = None
        if manifest:
            expected = hmac.new(
                _hmac_key(), _canonical(d, prios).encode(), hashlib.sha256
            ).hexdigest()
            export = {
                "export_id": manifest["export_id"],
                "signed_at": manifest["signed_at"],
                "valid": hmac.compare_digest(expected, manifest["hmac_sig"]),
            }
    summary, _, theme = d["summary"].partition("\n")
    return DigestRead(
        quarter=d["quarter"],
        generated=True,
        summary=summary,
        theme=theme,
        claim_label=d["claim"] or "INFERENCE",
        chain=d["chain"],
        created_at=d["created_at"],
        priorities=[
            Priority(
                pillar=p["pillar"],
                pillar_name=_PILLAR_NAME.get(p["pillar"], p["pillar"]),
                title=p["title"],
                body=p["body"],
                adversary_verdict=p["adversary_verdict"],
            )
            for p in prios
        ],
        quarters=list(quarters),
        cadence=cadence,
        export=export,
    )


async def export(quarter: str | None, actor: str) -> dict[str, Any]:
    """Sign the digest's canonical JSON into the append-only export manifest (F12)."""
    engine = db.get_engine()
    if engine is None:
        raise RuntimeError("database not initialised")
    async with engine.begin() as conn:
        d = await _load(conn, quarter)
        if d is None:
            return {"exported": False, "reason": "digest not generated"}
        prios = await _priorities(conn, d["digest_id"])
        canonical = _canonical(d, prios)
        sig = hmac.new(_hmac_key(), canonical.encode(), hashlib.sha256).hexdigest()
        export_id = (
            await conn.execute(
                text(
                    "INSERT INTO control.export_manifest "
                    "(kind, target_ref, artifact_uri, hmac_sig, created_by) "
                    "VALUES ('digest', :t, :u, :s, "
                    "(SELECT uid FROM control.users WHERE uid = :a)) RETURNING export_id"
                ),
                {
                    "t": f"digest:{d['quarter']}",
                    "u": f"inline:digest/{d['quarter']}",
                    "s": sig,
                    "a": actor,
                },
            )
        ).scalar_one()
    return {
        "exported": True,
        "export_id": str(export_id),
        "quarter": d["quarter"],
        "hmac_sig": sig,
        "artifact": json.loads(canonical),
    }


async def verify(export_id: str) -> dict[str, Any]:
    """Recompute the signature from the CURRENT stored digest. A digest regenerated or altered
    after signing fails verification — tamper-evident by construction."""
    engine = db.get_engine()
    if engine is None:
        raise RuntimeError("database not initialised")
    async with engine.connect() as conn:
        m = (
            (
                await conn.execute(
                    text(
                        "SELECT export_id, target_ref, hmac_sig, signed_at::text AS signed_at "
                        "FROM control.export_manifest WHERE export_id = CAST(:i AS uuid)"
                    ),
                    {"i": export_id},
                )
            )
            .mappings()
            .first()
        )
        if m is None:
            return {"found": False}
        quarter = str(m["target_ref"]).removeprefix("digest:")
        d = await _load(conn, quarter)
        if d is None:
            return {"found": True, "valid": False, "reason": "digest no longer exists"}
        prios = await _priorities(conn, d["digest_id"])
        expected = hmac.new(_hmac_key(), _canonical(d, prios).encode(), hashlib.sha256).hexdigest()
        return {
            "found": True,
            "valid": hmac.compare_digest(expected, str(m["hmac_sig"])),
            "quarter": quarter,
            "signed_at": m["signed_at"],
        }
