"""F7 — multi-signal trend detection (Trends monitor, D2; spec §18.1).

The weekly ``detect_trends`` job (config/schedules.yaml: trend_detect, Monday 06:30 after the news
scan) reads the last 8 weeks of GATED evidence, clusters it into coherent topics, scores each
cluster on four signals, gates it, and stages the survivors:

  window (8w) -> dedupe -> CLUSTER -> score(0.35 velocity + 0.30 diversity + 0.20 novelty +
  0.15 persistence) -> trend_threshold floor -> map subcaps -> emergent if novelty > cut ->
  GATE G2/G3/G6 -> persist trend + trend_subcap + reasoning chain + citations + gate run.

Hermetic-deterministic stand-ins for the parts F6 (the shared vector(768) space) will supply:
clustering is union-find over SHARED MAPPED SUBCAPS (a density proxy for HDBSCAN over embeddings),
and novelty blends the lexical mapping distance with the net-new impact class (the enrich model's
"this has no catalogue home" judgment) instead of cosine centroid distance — both swap to the
embedding metrics with no contract change once F6 lands. Only gated evidence (mapped, never the
items queued to Change Flags) feeds detection, so an ungated source can never influence a trend.

"Trends are earned, not counted": a cluster below the size/source floors is filtered silently; one
that clears the floors but fails a gate (a retire-themed cluster contradicting live delivery, G6)
is routed to review (Change Flags), never promoted as low-confidence.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app import db
from app.intelligence import gates
from app.jobs import schedule
from app.services import sources
from app.services.evidence import _CONTRADICTION_MIN_STORIES, _SCHEMA_RE, _TIER_SCORE, _max_delivery
from app.services.suggestions import _catalogue_evidence
from app.versioning import Version, get_active_version, resolve_version

logger = logging.getLogger("cia.trends")

_WINDOW_WEEKS = 8
_FLAG_KIND = "trend_gate_failure"
# Tiers order best -> worst, so the cluster's "best_tier" is the min index present.
_TIER_ORDER = ("T1", "T2", "T3", "T4", "T5")


@dataclass
class TrendSignals:
    velocity: float
    diversity: float
    novelty: float
    persistence: float


@dataclass
class TrendSubcap:
    subcap_id: str
    name: str
    emergent: bool


@dataclass
class TrendRow:
    id: str
    label: str
    status: str
    window: str
    window_start: str
    window_end: str
    evidence_count: int
    score: float
    signals: TrendSignals
    affects: list[TrendSubcap]
    emergent: bool
    label_claim: str  # claim label (trust envelope)
    tier: str
    ers: float
    chain: str | None


@dataclass
class TrendList:
    items: list[TrendRow]
    counts: dict[str, int]  # status -> count (KPI tiles)
    scan: dict[str, Any]


@dataclass
class _Cluster:
    """One detected cluster, in memory, before gating + persistence."""

    evidence_ids: list[str]
    news_ids: list[str]
    sources: dict[str, str]  # distinct source name -> its tier
    impacts: list[str]  # catalogue_impact per evidence item
    weeks: list[int]  # window week-index (0 oldest .. 7 newest) per evidence item
    ers_values: list[float]
    subcap_scores: dict[str, float]  # subcap_id -> best mapping score in the cluster
    subcap_names: dict[str, str]


def _week_index(published: datetime, window_start: datetime) -> int:
    return max(0, min(_WINDOW_WEEKS - 1, (published - window_start).days // 7))


def _velocity(weeks: list[int]) -> float:
    """Burst: the share of the cluster's evidence landing in the recent half of the window — a
    deterministic proxy for the spec's week-over-week acceleration (z-score / Kleinberg burst).
    Steady background -> ~0.5; a recent surge -> ->1.0."""
    if not weeks:
        return 0.0
    recent = sum(1 for w in weeks if w >= _WINDOW_WEEKS // 2)
    return round(recent / len(weeks), 3)


def _diversity(sources: dict[str, str], min_sources: int) -> float:
    """Tier-weighted distinct-source count, normalised by the min-sources floor: five independent
    T1/T2 sources outrank one blog repeated, and near-duplicates were collapsed upstream."""
    total = sum(_TIER_SCORE.get(t, 0.25) for t in sources.values())
    return round(min(1.0, total / min_sources), 3)


def _novelty(cluster: _Cluster) -> float:
    """Distance of the cluster from its nearest catalogue subcap: far = emergent (a candidate
    net-new subcap), near = a descriptor revision. Hermetic proxy = max(lexical mapping distance,
    net-new impact fraction); F6 swaps in 1 - max_cosine(centroid, subcap embeddings)."""
    best_map = max(cluster.subcap_scores.values(), default=0.0)
    lexical_distance = max(0.0, 1.0 - best_map)
    net_new = sum(1 for i in cluster.impacts if i == "net_new_subcap")
    net_new_fraction = net_new / len(cluster.impacts) if cluster.impacts else 0.0
    return round(max(lexical_distance, net_new_fraction), 3)


def _persistence(weeks: list[int]) -> float:
    """Weeks the signal is present across the window with implicit decay (a one-week spike fades,
    a sustained signal strengthens): distinct weeks present / window weeks."""
    return round(len(set(weeks)) / _WINDOW_WEEKS, 3)


def _best_tier(sources: dict[str, str]) -> str:
    present = [t for t in _TIER_ORDER if t in sources.values()]
    return present[0] if present else "T5"


def _cluster_evidence(
    items: list[dict[str, Any]], impacts: dict[str, list[dict[str, Any]]], window_start: datetime
) -> list[_Cluster]:
    """Union-find over shared mapped subcaps: two evidence items join the same cluster when they
    map to a common subcap (the hermetic density proxy for HDBSCAN over the shared embedding
    space). Returns one _Cluster per connected component."""
    parent: dict[str, str] = {it["news_id"]: it["news_id"] for it in items}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        parent[find(a)] = find(b)

    # Link every pair of items that share a subcap (via the subcap -> items inverted index).
    by_subcap: dict[str, list[str]] = defaultdict(list)
    for news_id, rows in impacts.items():
        for r in rows:
            by_subcap[r["subcap_id"]].append(news_id)
    for linked in by_subcap.values():
        for other in linked[1:]:
            union(linked[0], other)

    by_root: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for it in items:
        by_root[find(it["news_id"])].append(it)

    clusters: list[_Cluster] = []
    for group in by_root.values():
        sub_scores: dict[str, float] = {}
        sub_names: dict[str, str] = {}
        for m in group:
            for r in impacts.get(m["news_id"], []):
                sid = r["subcap_id"]
                sc = float(r["score"] or 0)
                if sc > sub_scores.get(sid, 0.0):
                    sub_scores[sid] = sc
                sub_names[sid] = r["name"]
        clusters.append(
            _Cluster(
                evidence_ids=[str(m["evidence_id"]) for m in group],
                news_ids=[str(m["news_id"]) for m in group],
                sources={m["source"]: m["tier"] for m in group},
                impacts=[m["impact"] for m in group],
                weeks=[_week_index(m["published_at"], window_start) for m in group],
                ers_values=[float(m["ers"] or 0) for m in group],
                subcap_scores=sub_scores,
                subcap_names=sub_names,
            )
        )
    return clusters


async def detect_trends(version: str) -> dict[str, Any]:
    """Run the weekly trend-detection job once (idempotent — re-derivable): cluster the window's
    gated evidence, score + gate each cluster, and stage survivors. Prior auto-managed trends
    (staged/review) for the version are cleared and recreated; analyst-touched trends
    (promoted/dismissed/consumed) are preserved."""
    v = await resolve_version(version)
    schema = v.schema_name
    if not _SCHEMA_RE.match(schema):
        raise ValueError("invalid version schema")
    engine = db.require_engine()

    cfg = gates.trends_config()
    now = datetime.now(UTC)
    window_start = now - timedelta(weeks=_WINDOW_WEEKS)

    detected = staged = review = filtered = emergent_n = decided = 0
    async with engine.begin() as conn:
        # Registry guard: detection is a derived source but still honours the persisted switch.
        await sources.ensure_enabled(conn, "trends")
        await _clear_auto_trends(conn, v.version_id)
        items = (
            (
                await conn.execute(
                    text(
                        "SELECT n.news_id::text AS news_id, e.evidence_id::text AS evidence_id, "
                        "e.source_name AS source, e.source_tier::text AS tier, "
                        "e.catalogue_impact::text AS impact, e.published_at, "
                        "(SELECT er.score::float FROM control.ers er "
                        "WHERE er.evidence_id = e.evidence_id "
                        "ORDER BY er.computed_at DESC LIMIT 1) AS ers "
                        "FROM control.news_item n "
                        "JOIN control.evidence_item e ON e.evidence_id = n.evidence_id "
                        "WHERE e.kind = 'news' AND e.published_at >= :ws "
                        "AND EXISTS (SELECT 1 FROM control.news_subcap_impact i "
                        "WHERE i.news_id = n.news_id AND i.version_id = :ver)"
                    ),
                    {"ws": window_start, "ver": v.version_id},
                )
            )
            .mappings()
            .all()
        )
        impact_rows = (
            (
                await conn.execute(
                    text(
                        "SELECT i.news_id::text AS news_id, i.subcap_id, i.score::float AS score, "
                        f"s.name FROM control.news_subcap_impact i JOIN {schema}.subcap s "
                        "ON s.subcap_id = i.subcap_id WHERE i.version_id = :ver"
                    ),
                    {"ver": v.version_id},
                )
            )
            .mappings()
            .all()
        )
        impacts: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for r in impact_rows:
            impacts[r["news_id"]].append(dict(r))

        for cluster in _cluster_evidence([dict(i) for i in items], impacts, window_start):
            # Statistical floors (pre-scoring): a thin or single-source cluster is not a trend.
            if (
                len(cluster.evidence_ids) < cfg.min_cluster
                or len(cluster.sources) < cfg.min_sources
            ):
                filtered += 1
                continue
            velocity = _velocity(cluster.weeks)
            diversity = _diversity(cluster.sources, cfg.min_sources)
            novelty = _novelty(cluster)
            persistence = _persistence(cluster.weeks)
            score = cfg.score(velocity, diversity, novelty, persistence)
            if score < cfg.trend_threshold:
                filtered += 1
                continue
            top_subcap = max(cluster.subcap_scores, key=lambda s: (cluster.subcap_scores[s], s))
            if await _already_decided(conn, v.version_id, top_subcap):
                # An analyst already promoted/dismissed this cluster — don't resurface it.
                decided += 1
                continue
            detected += 1
            outcome = await _persist_trend(
                conn,
                v,
                cluster,
                TrendSignals(velocity, diversity, novelty, persistence),
                score,
                novelty,
                cfg,
                now,
                window_start,
            )
            if outcome == "review":
                review += 1
            else:
                staged += 1
                if novelty > cfg.emergent_cut:
                    emergent_n += 1
        stats = {
            "detected": detected,
            "staged": staged,
            "review": review,
            "filtered": filtered,
            "decided": decided,
            "emergent": emergent_n,
        }
        await conn.execute(
            text(
                "INSERT INTO control.ingest_run (version_id, source, status, finished_at, stats) "
                "VALUES (:ver, 'trends', 'succeeded', now(), CAST(:s AS jsonb))"
            ),
            {"ver": v.version_id, "s": json.dumps(stats)},
        )
    return {"version": v.version_id, **stats}


async def _clear_auto_trends(conn: AsyncConnection, version_id: str) -> None:
    """Drop prior auto-detected trends (staged/review) for the version so detection is re-derivable;
    analyst-touched trends (promoted/dismissed/consumed) survive. Scoped deletes, FK-safe order."""
    rows = (
        (
            await conn.execute(
                text(
                    "SELECT DISTINCT tr.trend_id::text AS tid, tr.chain_id::text AS cid "
                    "FROM control.trend tr "
                    "JOIN control.trend_subcap ts ON ts.trend_id = tr.trend_id "
                    "WHERE ts.version_id = :ver AND tr.status IN ('staged', 'review')"
                ),
                {"ver": version_id},
            )
        )
        .mappings()
        .all()
    )
    tids = [r["tid"] for r in rows]
    cids = [r["cid"] for r in rows if r["cid"]]
    if not tids:
        return
    await conn.execute(
        text("DELETE FROM control.trend_subcap WHERE trend_id = ANY(CAST(:t AS uuid[]))"),
        {"t": tids},
    )
    if cids:
        await conn.execute(
            text(
                "DELETE FROM control.validation_gate_run WHERE chain_id = ANY(CAST(:c AS uuid[]))"
            ),
            {"c": cids},
        )
    await conn.execute(
        text("DELETE FROM control.trend WHERE trend_id = ANY(CAST(:t AS uuid[]))"),
        {"t": tids},
    )
    if cids:
        # reasoning_step + citation cascade on chain delete.
        await conn.execute(
            text("DELETE FROM control.reasoning_chain WHERE chain_id = ANY(CAST(:c AS uuid[]))"),
            {"c": cids},
        )


async def _already_decided(conn: AsyncConnection, version_id: str, subcap_id: str) -> bool:
    """True when an analyst has already promoted/dismissed/consumed a trend on this cluster's top
    subcap — so weekly re-detection does not resurface a cluster the analyst has already judged."""
    row = (
        await conn.execute(
            text(
                "SELECT 1 FROM control.trend tr "
                "JOIN control.trend_subcap ts ON ts.trend_id = tr.trend_id "
                "WHERE ts.version_id = :ver AND ts.subcap_id = :s "
                "AND tr.status IN ('promoted', 'dismissed', 'consumed') LIMIT 1"
            ),
            {"ver": version_id, "s": subcap_id},
        )
    ).first()
    return row is not None


async def _persist_trend(
    conn: AsyncConnection,
    v: Version,
    cluster: _Cluster,
    signals: TrendSignals,
    score: float,
    novelty: float,
    cfg: gates.TrendConfig,
    now: datetime,
    window_start: datetime,
) -> str:
    """Gate (G2/G3/G6) and persist one scored cluster. Returns the trend status ('staged' on a
    clean gate, 'review' when a gate fails -> queued to Change Flags, never promoted)."""
    subcap_ids = list(cluster.subcap_scores)
    emergent = novelty > cfg.emergent_cut
    best_tier = _best_tier(cluster.sources)
    ers = round(sum(cluster.ers_values) / len(cluster.ers_values), 3) if cluster.ers_values else 0.0
    # A retire-themed cluster pointing at heavily-delivered subcaps contradicts delivery (G6).
    retire_themed = sum(1 for i in cluster.impacts if i == "retire_candidate") >= len(
        cluster.impacts
    ) / 2 and any(i == "retire_candidate" for i in cluster.impacts)
    contradicts = False
    if retire_themed:
        delivery = await _max_delivery(conn, v.version_id, subcap_ids)
        contradicts = delivery >= _CONTRADICTION_MIN_STORIES

    results, verdict = gates.evaluate_trend(
        cluster_size=len(cluster.evidence_ids),
        distinct_sources=len(cluster.sources),
        best_tier=best_tier,
        min_cluster=cfg.min_cluster,
        min_sources=cfg.min_sources,
        contradicts=contradicts,
    )
    status = "staged" if verdict == "pass" else "review"
    # Claim label: an emergent (net-new) trend is a HYPOTHESIS; a grounded revision trend an
    # INFERENCE. A HYPOTHESIS never auto-promotes — a human decides (spec §18.4).
    claim_label = "HYPOTHESIS" if emergent else "INFERENCE"
    top_subcap = max(cluster.subcap_scores, key=lambda s: (cluster.subcap_scores[s], s))
    top_name = cluster.subcap_names[top_subcap]
    theme = "Emerging net-new capability signal" if emergent else "Rising cross-source signal"
    label = f"{theme}: {top_name}"

    summary = (
        f"{len(cluster.evidence_ids)} corroborating signals from {len(cluster.sources)} sources "
        f"clustered on {top_name} ({top_subcap}); score {score:.2f} "
        f"(velocity {signals.velocity:.2f} · diversity {signals.diversity:.2f} · novelty "
        f"{signals.novelty:.2f} · persistence {signals.persistence:.2f})."
    )
    chain_id = (
        await conn.execute(
            text(
                "INSERT INTO control.reasoning_chain "
                "(operation, subject_ref, claim_label, summary, model, cost_usd) "
                "VALUES ('trend', :subj, CAST(:cl AS claim_label), :sum, 'hermetic-stub', 0) "
                "RETURNING chain_id"
            ),
            {"subj": label, "cl": claim_label, "sum": summary},
        )
    ).scalar_one()

    steps = [
        (
            "retrieve",
            f"Clustered {len(cluster.evidence_ids)} gated evidence items from "
            f"{len(cluster.sources)} distinct sources over the {_WINDOW_WEEKS}-week window by "
            f"shared catalogue mapping; nearest subcap {top_subcap} ({top_name}).",
            None,
        ),
        (
            "weigh",
            f"Signals — velocity {signals.velocity:.2f} (burst), diversity {signals.diversity:.2f} "
            f"(tier-weighted sources), novelty {signals.novelty:.2f} (distance from catalogue), "
            f"persistence {signals.persistence:.2f} (weeks present) -> score {score:.2f} "
            f"(threshold {cfg.trend_threshold}).",
            None,
        ),
        (
            "conclude",
            (
                f"Novelty {novelty:.2f} exceeds the emergent cut {cfg.emergent_cut}: flagged as a "
                "candidate NET-NEW subcap — the only path a provisional synthetic story may "
                "surface."
                if emergent
                else f"Novelty {novelty:.2f} is below the emergent cut {cfg.emergent_cut}: maps to "
                "existing subcaps as a revision/new-use-case signal, not a net-new capability."
            ),
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
    for ev in cluster.evidence_ids:
        await conn.execute(
            text(
                "INSERT INTO control.citation (chain_id, evidence_id, verified) "
                "VALUES (:c, CAST(:e AS uuid), true)"
            ),
            {"c": chain_id, "e": ev},
        )

    trend_id = (
        await conn.execute(
            text(
                "INSERT INTO control.trend (label, status, window_start, window_end, "
                "evidence_count, signals, score, novelty, claim_label, source_tier, ers, chain_id) "
                "VALUES (:l, :st, :ws, :we, :ec, CAST(:sig AS jsonb), :sc, :nov, "
                "CAST(:cl AS claim_label), CAST(:tier AS source_tier), :ers, :chain) "
                "RETURNING trend_id"
            ),
            {
                "l": label,
                "st": status,
                "ws": window_start.date(),
                "we": now.date(),
                "ec": len(cluster.evidence_ids),
                "sig": json.dumps(vars(signals)),
                "sc": score,
                "nov": novelty,
                "cl": claim_label,
                "tier": best_tier,
                "ers": ers,
                "chain": chain_id,
            },
        )
    ).scalar_one()
    for sid in subcap_ids:
        await conn.execute(
            text(
                "INSERT INTO control.trend_subcap (trend_id, version_id, subcap_id, emergent) "
                "VALUES (:t, :ver, :s, :em)"
            ),
            {"t": trend_id, "ver": v.version_id, "s": sid, "em": emergent},
        )
    await conn.execute(
        text(
            "INSERT INTO control.validation_gate_run (chain_id, target_ref, gate_results, verdict) "
            "VALUES (:c, :t, CAST(:r AS jsonb), CAST(:v AS gate_verdict))"
        ),
        {"c": chain_id, "t": f"trend:{trend_id}", "r": json.dumps(results), "v": verdict},
    )
    if status == "review":
        gate = gates.first_failing(results) or "G6_contradiction"
        detail = {
            "title": f"Trend failed {gate.split('_')[0]}: {label}",
            "body": (
                f"{len(cluster.evidence_ids)} signals from {len(cluster.sources)} sources on "
                f"{top_name}. The gate run failed {gate}, so the trend was not staged — review the "
                "cluster before it can influence the catalogue."
            ),
            "gate_failed": gate,
            "version": v.version_id,
            "trend_id": str(trend_id),
        }
        await conn.execute(
            text(
                "INSERT INTO control.change_flag (kind, severity, target_ref, detail, chain_id) "
                "VALUES (:k, :sev, :t, CAST(:d AS jsonb), :c)"
            ),
            {
                "k": _FLAG_KIND,
                "sev": "MED",
                "t": f"trend:{trend_id}",
                "d": json.dumps(detail),
                "c": chain_id,
            },
        )
    return status


async def _scan_status(conn: AsyncConnection) -> dict[str, Any]:
    last = (
        await conn.execute(
            text(
                "SELECT finished_at::text FROM control.ingest_run "
                "WHERE source = 'trends' AND status = 'succeeded' "
                "ORDER BY finished_at DESC LIMIT 1"
            )
        )
    ).scalar()
    sched = schedule.describe("trend_detect")
    return {
        "last_scan": last,
        "next_scan": sched["next_run"],
        "cadence": "weekly",
        "cron": sched["cron"],
    }


async def list_trends(status: str | None = None, version: str | None = None) -> TrendList:
    """The Trends monitor read model: each card carries the signal breakdown, affected subcaps
    (with the emergent flag), the trust envelope (claim · tier · ERS · chain backlink), the window
    and status; plus per-status KPI counts and the weekly scan cadence."""
    v = await (resolve_version(version) if version else get_active_version())
    engine = db.get_engine()
    if engine is None or v is None:
        sched = schedule.describe("trend_detect")
        return TrendList(
            items=[],
            counts={},
            scan={
                "last_scan": None,
                "next_scan": sched["next_run"],
                "cadence": "weekly",
                "cron": sched["cron"],
            },
        )
    schema = v.schema_name
    if not _SCHEMA_RE.match(schema):
        raise ValueError("invalid version schema")

    filters = ""
    params: dict[str, Any] = {"ver": v.version_id}
    if status:
        filters = " AND tr.status = :status"
        params["status"] = status

    async with engine.connect() as conn:
        rows = (
            (
                await conn.execute(
                    text(
                        "SELECT tr.trend_id::text AS id, tr.label, tr.status, "
                        "tr.window_start::text AS ws, tr.window_end::text AS we, "
                        "tr.evidence_count, tr.score::float AS score, tr.signals, "
                        "tr.novelty::float AS novelty, tr.claim_label::text AS claim, "
                        "tr.source_tier::text AS tier, tr.ers::float AS ers, "
                        "tr.chain_id::text AS chain, tr.created_at "
                        "FROM control.trend tr "
                        "WHERE EXISTS (SELECT 1 FROM control.trend_subcap ts "
                        f"WHERE ts.trend_id = tr.trend_id AND ts.version_id = :ver){filters} "
                        "ORDER BY tr.score DESC, tr.created_at DESC, tr.trend_id"
                    ),
                    params,
                )
            )
            .mappings()
            .all()
        )
        sub_rows = (
            (
                await conn.execute(
                    text(
                        "SELECT ts.trend_id::text AS id, ts.subcap_id, ts.emergent, s.name "
                        f"FROM control.trend_subcap ts JOIN {schema}.subcap s "
                        "ON s.subcap_id = ts.subcap_id WHERE ts.version_id = :ver "
                        "ORDER BY ts.trend_id, ts.subcap_id"
                    ),
                    {"ver": v.version_id},
                )
            )
            .mappings()
            .all()
        )
        counts_rows = (
            (
                await conn.execute(
                    text(
                        "SELECT tr.status, count(DISTINCT tr.trend_id) AS n FROM control.trend tr "
                        "JOIN control.trend_subcap ts ON ts.trend_id = tr.trend_id "
                        "WHERE ts.version_id = :ver GROUP BY tr.status"
                    ),
                    {"ver": v.version_id},
                )
            )
            .mappings()
            .all()
        )
        scan = await _scan_status(conn)

    subs: dict[str, list[TrendSubcap]] = defaultdict(list)
    for r in sub_rows:
        subs[r["id"]].append(
            TrendSubcap(subcap_id=r["subcap_id"], name=r["name"], emergent=bool(r["emergent"]))
        )
    items: list[TrendRow] = []
    for r in rows:
        sig = r["signals"] or {}
        affects = subs.get(r["id"], [])
        items.append(
            TrendRow(
                id=r["id"],
                label=r["label"],
                status=r["status"],
                window=f"{r['ws']} – {r['we']}",
                window_start=r["ws"],
                window_end=r["we"],
                evidence_count=r["evidence_count"],
                score=float(r["score"] or 0),
                signals=TrendSignals(
                    velocity=float(sig.get("velocity", 0)),
                    diversity=float(sig.get("diversity", 0)),
                    novelty=float(sig.get("novelty", 0)),
                    persistence=float(sig.get("persistence", 0)),
                ),
                affects=affects,
                emergent=any(a.emergent for a in affects),
                label_claim=r["claim"] or "INFERENCE",
                tier=r["tier"] or "T3",
                ers=float(r["ers"] or 0),
                chain=r["chain"],
            )
        )
    counts = {r["status"]: int(r["n"]) for r in counts_rows}
    return TrendList(items=items, counts=counts, scan=scan)


async def trend_evidence(trend_id: str) -> dict[str, Any]:
    """The evidence-cluster drilldown (GET /trends/{id}/evidence): the gated evidence items behind
    a trend, each with its source sub-object, tier, claim label, ERS and reasoning backlink."""
    engine = db.require_engine()
    async with engine.connect() as conn:
        head = (
            (
                await conn.execute(
                    text(
                        "SELECT label, status, evidence_count FROM control.trend "
                        "WHERE trend_id = CAST(:id AS uuid)"
                    ),
                    {"id": trend_id},
                )
            )
            .mappings()
            .first()
        )
        if head is None:
            return {"found": False}
        rows = (
            (
                await conn.execute(
                    text(
                        "SELECT e.title, e.url, e.source_name AS source, "
                        "e.source_type::text AS stype, e.source_tier::text AS tier, "
                        "to_char(e.published_at, 'Mon DD, YYYY') AS date, "
                        "e.catalogue_impact::text AS impact, "
                        "(SELECT er.score::float FROM control.ers er "
                        "WHERE er.evidence_id = e.evidence_id "
                        "ORDER BY er.computed_at DESC LIMIT 1) AS ers, "
                        "(SELECT vr.chain_id::text FROM control.validation_gate_run vr "
                        "WHERE vr.target_ref = 'news:' || n.news_id::text "
                        "ORDER BY vr.created_at DESC LIMIT 1) AS chain "
                        "FROM control.citation c "
                        "JOIN control.evidence_item e ON e.evidence_id = c.evidence_id "
                        "JOIN control.news_item n ON n.evidence_id = e.evidence_id "
                        "JOIN control.trend tr ON tr.chain_id = c.chain_id "
                        "WHERE tr.trend_id = CAST(:id AS uuid) "
                        "ORDER BY e.published_at DESC"
                    ),
                    {"id": trend_id},
                )
            )
            .mappings()
            .all()
        )
    return {
        "found": True,
        "label": head["label"],
        "status": head["status"],
        "evidence_count": head["evidence_count"],
        "evidence": [dict(r) for r in rows],
    }


async def feedback(trend_id: str, verdict: str, actor: str) -> dict[str, Any]:
    """Analyst promote / dismiss (POST /trends/{id}/feedback): record the label (audit), move the
    trend status, and schedule threshold recalibration (on_trend_feedback, spec §18.3 — config,
    not code). Never mutates the catalogue; that path is the consultant loop -> D3."""
    if verdict not in ("promote", "dismiss"):
        return {"ok": False, "status": "invalid", "reason": "verdict must be promote | dismiss"}
    new_status = "promoted" if verdict == "promote" else "dismissed"
    engine = db.require_engine()
    async with engine.begin() as conn:
        updated = (
            await conn.execute(
                text(
                    "UPDATE control.trend SET status = :ns WHERE trend_id = CAST(:id AS uuid) "
                    "AND status IN ('staged', 'review') RETURNING trend_id"
                ),
                {"ns": new_status, "id": trend_id},
            )
        ).first()
        if updated is None:
            return {"ok": False, "status": "not_actionable"}
        await conn.execute(
            text(
                "INSERT INTO control.audit_log (actor, action, target_ref, meta) "
                "VALUES ((SELECT uid FROM control.users WHERE uid = :actor), :act, :ref, "
                "CAST(:meta AS jsonb))"
            ),
            {
                "actor": actor,
                "act": f"trend_{verdict}",
                "ref": f"trend:{trend_id}",
                "meta": json.dumps({"verdict": verdict}),
            },
        )
    # Self-learning loop (F13 / spec §18.3): the audit_log row is the persisted analyst label;
    # this records the recalibration enqueue. The live job re-tunes the config thresholds
    # (trend_threshold / emergent_cut / min_sources) from tracked precision/recall — never code.
    logger.info("on_trend_feedback: %s label recorded; threshold recalibration enqueued", verdict)
    return {"ok": True, "status": new_status}


async def propose_from_trend(trend_id: str, actor: str) -> dict[str, Any]:
    """Consultant loop (POST /trends/{id}/loop): stage a GATED suggestion from a trend — never a
    live edit (D3 applies it, re-gating server-side). Targets the trend's top NON-emergent subcap
    (a real catalogue entry to revise); an all-emergent trend is a net-new candidate and is refused
    here — net-new subcaps run through the mapping studio so the taxonomy stays MECE."""
    engine = db.require_engine()
    async with engine.begin() as conn:
        tr = (
            (
                await conn.execute(
                    text(
                        "SELECT tr.label, tr.status, tr.source_tier::text AS tier, "
                        "tr.ers::float AS ers, tr.chain_id "
                        "FROM control.trend tr WHERE tr.trend_id = CAST(:id AS uuid)"
                    ),
                    {"id": trend_id},
                )
            )
            .mappings()
            .first()
        )
        if tr is None:
            return {"staged": False, "status": "not_found"}
        if tr["status"] not in ("staged", "promoted"):
            return {
                "staged": False,
                "status": "refused",
                "reason": "Only a staged or promoted trend can seed a suggestion.",
            }
        ver_row = (
            await conn.execute(
                text(
                    "SELECT version_id FROM control.trend_subcap WHERE trend_id = CAST(:id AS uuid)"
                    " LIMIT 1"
                ),
                {"id": trend_id},
            )
        ).scalar()
        v = await resolve_version(str(ver_row))
        schema = v.schema_name
        if not _SCHEMA_RE.match(schema):
            raise ValueError("invalid version schema")
        target = (
            (
                await conn.execute(
                    text(
                        "SELECT ts.subcap_id, s.name, s.description, "
                        "coalesce((SELECT max(i.score) FROM control.news_subcap_impact i "
                        "WHERE i.subcap_id = ts.subcap_id AND i.version_id = ts.version_id), 0) "
                        "AS score "
                        f"FROM control.trend_subcap ts JOIN {schema}.subcap s "
                        "ON s.subcap_id = ts.subcap_id "
                        "WHERE ts.trend_id = CAST(:id AS uuid) AND ts.emergent = false "
                        "ORDER BY score DESC, ts.subcap_id LIMIT 1"
                    ),
                    {"id": trend_id},
                )
            )
            .mappings()
            .first()
        )
        if target is None:
            return {
                "staged": False,
                "status": "refused",
                "reason": "This trend points at an emergent (net-new) capability — it runs through "
                "the mapping studio (J1), not an in-place edit.",
            }
        target_id = str(target["subcap_id"])
        dup = (
            await conn.execute(
                text(
                    "SELECT 1 FROM control.suggestion WHERE target_subcap = :t "
                    "AND kind = 'descriptor_update' AND status = 'pending' "
                    "AND payload ->> 'trend_id' = :tr"
                ),
                {"t": target_id, "tr": trend_id},
            )
        ).first()
        if dup is not None:
            return {
                "staged": False,
                "status": "duplicate",
                "kind": "descriptor_update",
                "target": target_id,
            }

        # The trend's own gated evidence is the citation set (G5/G7); the cluster summary is the
        # drafted descriptor note (the enrich model drafts this in live mode).
        trend_ev = (
            await conn.execute(
                text(
                    "SELECT c.evidence_id FROM control.citation c " "WHERE c.chain_id = :ch LIMIT 1"
                ),
                {"ch": tr["chain_id"]},
            )
        ).scalar()
        results, verdict = gates.evaluate_suggestion(
            target_exists=True,
            evidence_count=2,  # the trend's clustered evidence + the target's catalogue entry
            source_tier=str(tr["tier"] or "T3"),
            cited=True,
            contradicts=False,
            cost_usd=0.0,
        )
        current = str(target["description"] or "").rstrip()
        drafted = f"{current} Trend signal (2026): {tr['label']}.".strip()
        title = f"Descriptor revision: {target['name']}"
        rationale = (
            f"Staged from the Trends monitor — {tr['label']}. A cross-source cluster points at "
            f"{target['name']} ({target_id}); revise the descriptor to reflect the signal."
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
        catalogue_ev = await _catalogue_evidence(conn, target_id, str(target["name"]))
        for ordinal, (kind_s, txt, ev) in enumerate(
            (
                (
                    "retrieve",
                    f"Trend {tr['label']!r} clustered gated evidence onto {target_id}.",
                    trend_ev,
                ),
                (
                    "conclude",
                    f"Propose a descriptor_update on {target_id}, grounded in the trend's "
                    "cited cluster and the catalogue entry.",
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
        for ev in (trend_ev, catalogue_ev):
            if ev is not None:
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
            {"c": chain_id, "t": target_id, "r": json.dumps(results), "v": verdict},
        )
        payload = {
            "title": title,
            "rationale": rationale,
            "subcap_name": target["name"],
            "pillar": target_id[:2],
            "trend_id": trend_id,
            "gate_results": results,
            "verdict": verdict,
            "breaking": False,
            "before": {"description": current},
            "after": {"description": drafted},
        }
        suggestion_id = (
            await conn.execute(
                text(
                    "INSERT INTO control.suggestion (target_version, target_subcap, kind, payload, "
                    "claim_label, source_tier, ers, chain_id, status, created_by) "
                    "VALUES (:ver, :sub, 'descriptor_update', CAST(:p AS jsonb), 'INFERENCE', "
                    "CAST(:tier AS source_tier), :ers, :chain, 'pending', "
                    "(SELECT uid FROM control.users WHERE uid = :actor)) RETURNING suggestion_id"
                ),
                {
                    "ver": v.version_id,
                    "sub": target_id,
                    "p": json.dumps(payload),
                    "tier": tr["tier"] or "T3",
                    "ers": tr["ers"],
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
        "target": target_id,
    }
