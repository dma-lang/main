"""F7 — benchmark ingestion (Benchmarks studio, D4; spec §D4).

Monthly job (config/schedules.yaml: benchmark_scan): fetch curated public datasets (T2) ->
dedupe (source+metric) -> bootstrap CI over the observations (seeded resample of the median —
deterministic, so a re-run reproduces the band bit-for-bit) -> ADVERSARIAL review (verdict chip
BENCHMARK / INDICATIVE / EXPLORATORY; a live 429 yields no verdict and renders "pending") ->
map to subcaps via stored-catalogue retrieval (relevance floor) -> gate -> persist evidence +
ERS + control.benchmark + reasoning chain + citation + gate run. The page writes nothing.

Honesty rails: a panel under the configured observation floor is THIN — its CI band is suppressed
(no false precision) and the coverage-gap banner names the gap; a missing methodology renders
"not documented", never invented; gate failures queue to Change Flags (never dropped, never shown
as mapped).
"""

from __future__ import annotations

import json
import random
import statistics
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app import db
from app.intelligence import benchmarks as scout
from app.intelligence import gates, retrieval
from app.intelligence.benchmarks import AdversaryVerdict, RawBenchmark
from app.jobs import schedule
from app.services import sources
from app.services.evidence import _SCHEMA_RE, _impact_scores, compute_ers
from app.services.suggestions import _catalogue_evidence
from app.versioning import Version, get_active_version, resolve_version

_FLAG_KIND = "evidence_gate_failure"
# Adversary verdict -> claim label (the hermetic stand-in for "whatever the adversary assigns"):
# a surviving band is defensible (FACT), a caveated one is directional (INFERENCE), a refused one
# is exploratory colour (HYPOTHESIS). "pending" (no verdict yet) never claims more than HYPOTHESIS.
_VERDICT_LABEL = {
    "BENCHMARK": "FACT",
    "INDICATIVE": "INFERENCE",
    "EXPLORATORY": "HYPOTHESIS",
}


@dataclass
class BenchSource:
    name: str
    type: str
    tier: str
    url: str
    ers: float
    fetched_at: str


@dataclass
class BenchRow:
    id: str
    metric: str
    unit: str
    segment: str
    date: str
    n: int
    observations: list[float]
    p25: float
    p50: float
    p75: float
    ci_low: float | None  # None = suppressed (thin coverage — no false precision)
    ci_high: float | None
    thin: bool
    coverage_note: str | None
    methodology: str  # "not documented" when the source did not publish one
    verdict: str  # BENCHMARK | INDICATIVE | EXPLORATORY | pending
    verdict_note: str
    label: str  # claim label (trust envelope)
    tier: str
    ers: float
    reliability: float
    source: BenchSource
    affects: list[list[Any]]  # [subcap_id, score, name]
    chain: str | None


@dataclass
class BenchList:
    items: list[BenchRow]
    segments: list[str]
    scan: dict[str, Any]


def bootstrap_ci(
    observations: list[float], *, resamples: int, ci_level: float, seed: str
) -> tuple[float, float]:
    """Bootstrap CI of the MEDIAN: resample-with-replacement ``resamples`` times, take the
    (1-ci)/2 and 1-(1-ci)/2 percentiles of the resampled medians. Seeded by content so hermetic
    and live runs are reproducible bit-for-bit (idempotent re-scan, honest re-derivation)."""
    rng = random.Random(seed)
    n = len(observations)
    medians = sorted(statistics.median(rng.choices(observations, k=n)) for _ in range(resamples))
    alpha = (1.0 - ci_level) / 2.0
    lo_idx = max(0, min(resamples - 1, int(alpha * resamples)))
    hi_idx = max(0, min(resamples - 1, int((1.0 - alpha) * resamples) - 1))
    return round(medians[lo_idx], 3), round(medians[hi_idx], 3)


def quartiles(observations: list[float]) -> tuple[float, float, float]:
    """(p25, median, p75) of the raw observations (linear interpolation)."""
    qs = statistics.quantiles(observations, n=4, method="inclusive")
    return round(qs[0], 3), round(qs[1], 3), round(qs[2], 3)


async def scan_benchmarks(version: str) -> dict[str, Any]:
    """Run the monthly benchmark job once (idempotent): fetch -> dedupe -> CI -> adversary ->
    map -> gate -> persist. Re-running creates nothing new; outcomes land in ingest_run.stats."""
    v = await resolve_version(version)
    schema = v.schema_name
    if not _SCHEMA_RE.match(schema):
        raise ValueError("invalid version schema")
    engine = db.require_engine()
    async with engine.connect() as conn:
        # Registry guard BEFORE the fetch: a disabled source never pulls (and never spends).
        await sources.ensure_enabled(conn, "benchmarks")

    fetched = await scout.fetch_benchmarks()
    created = deduped = mapped = flagged = 0
    async with engine.begin() as conn:
        for raw in fetched:
            duplicate = (
                await conn.execute(
                    text(
                        "SELECT 1 FROM control.benchmark b "
                        "JOIN control.evidence_item e ON e.evidence_id = b.evidence_id "
                        "WHERE e.source_name = :s AND b.metric = :m"
                    ),
                    {"s": raw.source, "m": raw.metric},
                )
            ).first()
            if duplicate is not None:
                deduped += 1
                continue
            # Review AFTER dedupe so a re-scan never re-runs the adversary (zero marginal spend).
            verdict = await scout.adversary_review(raw)
            ok = await _ingest_one(conn, v, schema, raw, verdict)
            created += 1
            if ok:
                mapped += 1
            else:
                flagged += 1
        stats = {
            "fetched": len(fetched),
            "created": created,
            "deduped": deduped,
            "mapped": mapped,
            "flagged": flagged,
        }
        await conn.execute(
            text(
                "INSERT INTO control.ingest_run (version_id, source, status, finished_at, stats) "
                "VALUES (:ver, 'benchmarks', 'succeeded', now(), CAST(:s AS jsonb))"
            ),
            {"ver": v.version_id, "s": json.dumps(stats)},
        )
    return {"version": v.version_id, **stats}


async def _ingest_one(
    conn: AsyncConnection, v: Version, schema: str, raw: RawBenchmark, adv: AdversaryVerdict
) -> bool:
    """CI + map + gate + persist ONE benchmark. Returns True when mapped (gates passed); False
    when queued to Change Flags instead."""
    cfg = gates.benchmarks_config()
    published = datetime.fromisoformat(raw.published).replace(tzinfo=UTC)
    obs = list(raw.observations)
    n = len(obs)
    thin = n < cfg.min_observations
    p25, p50, p75 = quartiles(obs)
    # Thin coverage shows the distribution but never a confidence band (no false precision).
    ci_low: float | None = None
    ci_high: float | None = None
    if not thin:
        ci_low, ci_high = bootstrap_ci(
            obs,
            resamples=cfg.bootstrap_resamples,
            ci_level=cfg.ci_level,
            seed=f"{raw.metric}|{n}",
        )

    floor, strong = gates.evidence_thresholds()
    matches = await retrieval.retrieve(conn, schema, raw.topics, k=3)
    grounded = [m for m in matches if float(m["rank"]) >= floor]
    top_rank = max((float(m["rank"]) for m in grounded), default=0.0)
    strength = min(1.0, top_rank / strong) if grounded else 0.0
    impacts = _impact_scores(grounded, strength)
    results, gate_verdict = gates.evaluate_evidence(
        source_tier=raw.tier,
        retrieval_count=len(matches),
        grounded_count=len(grounded),
        cited=True,
        contradicts=False,
    )
    components, ers = compute_ers(
        tier=raw.tier,
        published=published,
        specificity=raw.specificity,
        corroboration=min(1.0, 0.4 + 0.025 * n),  # more independent observations corroborate
    )
    claim_label = _VERDICT_LABEL.get(adv.verdict, "HYPOTHESIS")

    evidence_id = (
        await conn.execute(
            text(
                "INSERT INTO control.evidence_item (kind, title, url, source_tier, published_at, "
                "source_name, source_type) VALUES ('benchmark', :t, :u, "
                "CAST(:tier AS source_tier), :p, :sn, 'benchmark') RETURNING evidence_id"
            ),
            {
                "t": f"{raw.metric} — {raw.source}",
                "u": raw.url,
                "tier": raw.tier,
                "p": published,
                "sn": raw.source,
            },
        )
    ).scalar_one()
    await conn.execute(
        text(
            "INSERT INTO control.ers (evidence_id, score, components) "
            "VALUES (:e, :s, CAST(:c AS jsonb))"
        ),
        {"e": evidence_id, "s": ers, "c": json.dumps(components)},
    )

    band = (
        f"median {p50} {raw.unit} with no confidence band ({n} observations is under the "
        f"floor {cfg.min_observations} — no false precision)"
        if thin
        else f"median {p50} {raw.unit}, bootstrap {int(cfg.ci_level * 100)}% CI "
        f"[{ci_low}, {ci_high}] over {n} observations"
    )
    summary = f"{raw.metric} ({raw.segment}): {band}. Adversary verdict {adv.verdict}."
    chain_id = (
        await conn.execute(
            text(
                "INSERT INTO control.reasoning_chain "
                "(operation, subject_ref, claim_label, summary, model, cost_usd) "
                "VALUES ('adversarial', :subj, CAST(:cl AS claim_label), :sum, :model, 0) "
                "RETURNING chain_id"
            ),
            {"subj": raw.metric, "cl": claim_label, "sum": summary, "model": adv.model},
        )
    ).scalar_one()
    retrieved = (
        ", ".join(f"{s} ({sc:.2f})" for s, sc, _ in impacts)
        or "no subcap above the relevance floor"
    )
    steps = [
        (
            "retrieve",
            f"Monthly ingest fetched the curated panel from {raw.source} ({raw.tier}); topic "
            f"retrieval over the {v.version_id} catalogue (relevance floor {floor}) mapped it "
            f"to {retrieved}.",
            evidence_id,
        ),
        (
            "weigh",
            f"Quantitative core: {band}; quartiles p25 {p25} · p50 {p50} · p75 {p75} {raw.unit}."
            + ("" if raw.methodology else " Methodology not documented by the source."),
            None,
        ),
        (
            "adversarial",
            f"Adversarial review ({adv.verdict}): {adv.note}",
            None,
        ),
        (
            "conclude",
            f"Claim label {claim_label} follows the adversary verdict — never assert more than "
            "the evidence supports.",
            None,
        ),
    ]
    for ordinal, (kind, step_text, ev) in enumerate(steps, start=1):
        await conn.execute(
            text(
                "INSERT INTO control.reasoning_step (chain_id, ordinal, kind, text, evidence_id) "
                "VALUES (:c, :o, :k, :t, :e)"
            ),
            {"c": chain_id, "o": ordinal, "k": kind, "t": step_text, "e": ev},
        )
    await conn.execute(
        text(
            "INSERT INTO control.citation (chain_id, evidence_id, verified) VALUES (:c, :e, true)"
        ),
        {"c": chain_id, "e": evidence_id},
    )

    if gate_verdict != "pass":
        gate = gates.first_failing(results) or "G5_similarity_grounding"
        await conn.execute(
            text(
                "INSERT INTO control.validation_gate_run (chain_id, target_ref, gate_results, "
                "verdict) VALUES (:c, :t, CAST(:r AS jsonb), CAST(:v AS gate_verdict))"
            ),
            {
                "c": chain_id,
                "t": f"benchmark:{evidence_id}",
                "r": json.dumps(results),
                "v": gate_verdict,
            },
        )
        detail = {
            "title": f"Benchmark failed {gate.split('_')[0]}: {raw.metric}",
            "body": (
                f"{raw.source} ({raw.tier}). The gate run failed {gate}, so the benchmark was "
                "not mapped — review the panel before it can influence the catalogue."
            ),
            "gate_failed": gate,
            "version": v.version_id,
            "source": raw.source,
            "tier": raw.tier,
            "url": raw.url,
        }
        await conn.execute(
            text(
                "INSERT INTO control.change_flag (kind, severity, target_ref, detail, chain_id) "
                "VALUES (:k, 'MED', :t, CAST(:d AS jsonb), :c)"
            ),
            {
                "k": _FLAG_KIND,
                "t": f"benchmark:{evidence_id}",
                "d": json.dumps(detail),
                "c": chain_id,
            },
        )
        return False

    benchmark_id = (
        await conn.execute(
            text(
                "INSERT INTO control.benchmark (evidence_id, version_id, subcap_id, segment, "
                "metric, unit, observations, n, p25, p50, p75, ci_low, ci_high, methodology, "
                "verdict, verdict_note, affects, chain_id) "
                "VALUES (:e, :ver, :sub, :seg, :m, :u, CAST(:obs AS jsonb), :n, :p25, :p50, "
                ":p75, :cl, :ch, :meth, :vd, :vn, CAST(:aff AS jsonb), :chain) "
                "RETURNING benchmark_id"
            ),
            {
                "e": evidence_id,
                "ver": v.version_id,
                "sub": impacts[0][0] if impacts else None,
                "seg": raw.segment,
                "m": raw.metric,
                "u": raw.unit,
                "obs": json.dumps(obs),
                "n": n,
                "p25": p25,
                "p50": p50,
                "p75": p75,
                "cl": ci_low,
                "ch": ci_high,
                "meth": raw.methodology,
                "vd": adv.verdict,
                "vn": adv.note,
                "aff": json.dumps([[s, sc] for s, sc, _ in impacts]),
                "chain": chain_id,
            },
        )
    ).scalar_one()
    await conn.execute(
        text(
            "INSERT INTO control.validation_gate_run (chain_id, target_ref, gate_results, "
            "verdict) VALUES (:c, :t, CAST(:r AS jsonb), CAST(:v AS gate_verdict))"
        ),
        {
            "c": chain_id,
            "t": f"benchmark:{benchmark_id}",
            "r": json.dumps(results),
            "v": gate_verdict,
        },
    )
    return True


async def _scan_status(conn: AsyncConnection) -> dict[str, Any]:
    last = (
        await conn.execute(
            text(
                "SELECT finished_at::text FROM control.ingest_run "
                "WHERE source = 'benchmarks' AND status = 'succeeded' "
                "ORDER BY finished_at DESC LIMIT 1"
            )
        )
    ).scalar()
    sched = schedule.describe("benchmark_scan")
    return {
        "last_scan": last,
        "next_scan": sched["next_run"],
        "cadence": "monthly",
        "cron": sched["cron"],
    }


async def list_benchmarks(segment: str | None = None, version: str | None = None) -> BenchList:
    """The Benchmarks studio read model: observations + CI band + adversary verdict + reasoning
    (the spec contract), with the trust envelope and the thin-coverage flag on every item."""
    v = await (resolve_version(version) if version else get_active_version())
    engine = db.get_engine()
    if engine is None or v is None:
        sched = schedule.describe("benchmark_scan")
        return BenchList(
            items=[],
            segments=[],
            scan={
                "last_scan": None,
                "next_scan": sched["next_run"],
                "cadence": "monthly",
                "cron": sched["cron"],
            },
        )
    schema = v.schema_name
    if not _SCHEMA_RE.match(schema):
        raise ValueError("invalid version schema")

    cfg = gates.benchmarks_config()
    filters = ""
    params: dict[str, Any] = {"ver": v.version_id}
    if segment:
        filters = " AND b.segment = :seg"
        params["seg"] = segment

    async with engine.connect() as conn:
        rows = (
            (
                await conn.execute(
                    text(
                        "SELECT b.benchmark_id::text AS id, b.metric, b.unit, b.segment, "
                        "b.observations, b.n, b.p25::float AS p25, b.p50::float AS p50, "
                        "b.p75::float AS p75, b.ci_low::float AS ci_low, "
                        "b.ci_high::float AS ci_high, b.methodology, b.verdict, b.verdict_note, "
                        "b.affects, b.chain_id::text AS chain, "
                        "to_char(e.published_at, 'Mon YYYY') AS date, "
                        "e.source_name, e.source_tier::text AS tier, e.url, "
                        "e.created_at::text AS fetched_at, "
                        "(SELECT er.score::float FROM control.ers er WHERE er.evidence_id = "
                        "e.evidence_id ORDER BY er.computed_at DESC LIMIT 1) AS ers, "
                        "(SELECT rc.claim_label::text FROM control.reasoning_chain rc "
                        "WHERE rc.chain_id = b.chain_id) AS label "
                        "FROM control.benchmark b "
                        "JOIN control.evidence_item e ON e.evidence_id = b.evidence_id "
                        f"WHERE b.version_id = :ver{filters} "
                        "ORDER BY e.published_at DESC, b.benchmark_id"
                    ),
                    params,
                )
            )
            .mappings()
            .all()
        )
        # Resolve mapped subcap names from the version schema (affects holds [id, score] pairs).
        ids = sorted({s for r in rows for s, _ in (r["affects"] or [])})
        names: dict[str, str] = {}
        if ids:
            name_rows = (
                (
                    await conn.execute(
                        text(
                            f"SELECT subcap_id, name FROM {schema}.subcap "
                            "WHERE subcap_id = ANY(:ids)"
                        ),
                        {"ids": ids},
                    )
                )
                .mappings()
                .all()
            )
            names = {r["subcap_id"]: r["name"] for r in name_rows}
        scan = await _scan_status(conn)

    items: list[BenchRow] = []
    for r in rows:
        thin = int(r["n"]) < cfg.min_observations
        items.append(
            BenchRow(
                id=r["id"],
                metric=r["metric"],
                unit=r["unit"] or "",
                segment=r["segment"] or "",
                date=r["date"],
                n=int(r["n"]),
                observations=[float(x) for x in (r["observations"] or [])],
                p25=float(r["p25"] or 0),
                p50=float(r["p50"] or 0),
                p75=float(r["p75"] or 0),
                ci_low=float(r["ci_low"]) if r["ci_low"] is not None else None,
                ci_high=float(r["ci_high"]) if r["ci_high"] is not None else None,
                thin=thin,
                coverage_note=(
                    f"{r['n']} observations (floor {cfg.min_observations}) — benchmark support "
                    "is thin; do not over-read."
                    if thin
                    else None
                ),
                methodology=r["methodology"] or "not documented",
                verdict=r["verdict"] or "pending",
                verdict_note=r["verdict_note"] or "Adversarial review pending.",
                label=r["label"] or "HYPOTHESIS",
                tier=r["tier"],
                ers=float(r["ers"] or 0),
                reliability=float(r["ers"] or 0),
                source=BenchSource(
                    name=r["source_name"] or "",
                    type="Benchmark",
                    tier=r["tier"],
                    url=r["url"] or "",
                    ers=float(r["ers"] or 0),
                    fetched_at=r["fetched_at"],
                ),
                affects=[[s, float(sc), names.get(s, s)] for s, sc in (r["affects"] or [])],
                chain=r["chain"],
            )
        )
    segments = sorted({i.segment for i in items if i.segment})
    return BenchList(items=items, segments=segments, scan=scan)


async def propose_from_benchmark(benchmark_id: str, actor: str) -> dict[str, Any]:
    """Consultant loop (spec: the loop opens from Benchmarks too): stage a GATED descriptor_update
    on the benchmark's top mapped subcap, citing the benchmark evidence — never a live edit."""
    engine = db.require_engine()
    async with engine.begin() as conn:
        b = (
            (
                await conn.execute(
                    text(
                        "SELECT b.benchmark_id, b.evidence_id, b.version_id, b.subcap_id, "
                        "b.metric, b.unit, b.p50::float AS p50, b.ci_low::float AS ci_low, "
                        "b.ci_high::float AS ci_high, b.n, b.verdict, e.source_name, "
                        "e.source_tier::text AS tier, "
                        "(SELECT er.score::float FROM control.ers er "
                        "WHERE er.evidence_id = e.evidence_id "
                        "ORDER BY er.computed_at DESC LIMIT 1) AS ers "
                        "FROM control.benchmark b "
                        "JOIN control.evidence_item e ON e.evidence_id = b.evidence_id "
                        "WHERE b.benchmark_id = CAST(:id AS uuid)"
                    ),
                    {"id": benchmark_id},
                )
            )
            .mappings()
            .first()
        )
        if b is None:
            return {"staged": False, "status": "not_found"}
        if b["verdict"] == "EXPLORATORY":
            return {
                "staged": False,
                "status": "refused",
                "reason": "An EXPLORATORY benchmark cannot ground a catalogue edit — the "
                "adversary found the band unsupportable (no false precision).",
            }
        if not b["subcap_id"]:
            return {"staged": False, "status": "refused", "reason": "no mapped subcap"}
        v = await resolve_version(str(b["version_id"]))
        schema = v.schema_name
        if not _SCHEMA_RE.match(schema):
            raise ValueError("invalid version schema")
        target = str(b["subcap_id"])
        sub = (
            (
                await conn.execute(
                    text(f"SELECT name, description FROM {schema}.subcap WHERE subcap_id = :t"),
                    {"t": target},
                )
            )
            .mappings()
            .first()
        )
        if sub is None:
            return {"staged": False, "status": "refused", "reason": "target subcap not found"}
        dup = (
            await conn.execute(
                text(
                    "SELECT 1 FROM control.suggestion WHERE target_subcap = :t "
                    "AND kind = 'descriptor_update' AND status = 'pending' "
                    "AND payload ->> 'benchmark_id' = :b"
                ),
                {"t": target, "b": str(b["benchmark_id"])},
            )
        ).first()
        if dup is not None:
            return {
                "staged": False,
                "status": "duplicate",
                "kind": "descriptor_update",
                "target": target,
            }

        results, verdict = gates.evaluate_suggestion(
            target_exists=True,
            evidence_count=2,  # the benchmark evidence + the target's catalogue entry
            source_tier=str(b["tier"]),
            cited=True,
            contradicts=False,
            cost_usd=0.0,
        )
        band = (
            f"median {b['p50']} {b['unit']}"
            + (f", 95% CI [{b['ci_low']}, {b['ci_high']}]" if b["ci_low"] is not None else "")
            + f" across {b['n']} observations"
        )
        title = f"Benchmark anchor: {sub['name']}"
        rationale = (
            f"{b['source_name']} ({b['tier']}) — {b['metric']}: {band}. Anchor the descriptor "
            "to the defensible band. Staged from the Benchmarks studio."
        )
        chain_id = (
            await conn.execute(
                text(
                    "INSERT INTO control.reasoning_chain "
                    "(operation, subject_ref, claim_label, summary, model, cost_usd) "
                    "VALUES ('suggestion', :subj, 'INFERENCE', :sum, 'hermetic-stub', 0) "
                    "RETURNING chain_id"
                ),
                {"subj": title, "sum": rationale},
            )
        ).scalar_one()
        catalogue_ev = await _catalogue_evidence(conn, target, str(sub["name"]))
        for ordinal, (kind_s, txt, ev) in enumerate(
            (
                (
                    "retrieve",
                    f"Benchmark {b['metric']!r} maps to {target}; {band}.",
                    b["evidence_id"],
                ),
                (
                    "conclude",
                    f"Propose a descriptor_update on {target}, grounded in the cited benchmark "
                    "and the catalogue entry.",
                    catalogue_ev,
                ),
            ),
            start=1,
        ):
            await conn.execute(
                text(
                    "INSERT INTO control.reasoning_step "
                    "(chain_id, ordinal, kind, text, evidence_id) VALUES (:c, :o, :k, :t, :e)"
                ),
                {"c": chain_id, "o": ordinal, "k": kind_s, "t": txt, "e": ev},
            )
        for ev in (b["evidence_id"], catalogue_ev):
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
            {"c": chain_id, "t": target, "r": json.dumps(results), "v": verdict},
        )
        current = str(sub["description"] or "").rstrip()
        drafted = (
            f"{current} Benchmark anchor ({b['source_name']}, {b['tier']}): "
            f"{b['metric']} {band}."
        ).strip()
        payload = {
            "title": title,
            "rationale": rationale,
            "subcap_name": sub["name"],
            "pillar": target[:2],
            "benchmark_id": str(b["benchmark_id"]),
            "gate_results": results,
            "verdict": verdict,
            "breaking": False,
            "before": {"description": current},
            "after": {"description": drafted},
        }
        suggestion_id = (
            await conn.execute(
                text(
                    "INSERT INTO control.suggestion (target_version, target_subcap, kind, "
                    "payload, claim_label, source_tier, ers, chain_id, status, created_by) "
                    "VALUES (:ver, :sub, 'descriptor_update', CAST(:p AS jsonb), 'INFERENCE', "
                    "CAST(:tier AS source_tier), :ers, :chain, 'pending', "
                    "(SELECT uid FROM control.users WHERE uid = :actor)) RETURNING suggestion_id"
                ),
                {
                    "ver": v.version_id,
                    "sub": target,
                    "p": json.dumps(payload),
                    "tier": b["tier"],
                    "ers": b["ers"],
                    "chain": chain_id,
                    "actor": actor,
                },
            )
        ).scalar_one()
    return {
        "staged": True,
        "status": "pending",
        "suggestion_id": str(suggestion_id),
        "kind": "descriptor_update",
        "target": target,
    }
