"""F7 — evidence ingestion: the five-stage news pipeline (News watch, D1; spec §17.5).

Stage 1 FETCH (intelligence.news: weekly grounded-search Batch; hermetic = recorded fixture) ->
dedupe -> stage 2 ENRICH (intelligence.news: classify expected catalogue impact, claim label,
specificity, topic terms) -> stage 3 MAP (F6 retrieval over the stored catalogue — by meaning,
never model memory) -> stage 4 GATE (G1/G3/G5/G6/G7, deterministic code) -> stage 5 PERSIST
(evidence + ERS + per-subcap impacts + reasoning chain + citation + gate run).

Relevance is enforced, not assumed (config/gates.yaml: evidence.*): retrieval matches below the
relevance floor are noise and never map — an item with NOTHING above the floor fails G5 and is
queued to Change Flags (never dropped, never shown as mapped); an item whose top match clears the
floor but not the strong-grounding bar maps with its claim label downgraded one notch and its
mapping scores scaled down, with the downgrade documented as a reasoning step. Cadence comes from
``config/schedules.yaml`` (weekly, Monday), never code.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app import db
from app.intelligence import gates, retrieval
from app.intelligence import news as scout
from app.intelligence.news import NewsEnrichment, RawNewsItem
from app.jobs import schedule
from app.services.suggestions import _catalogue_evidence
from app.versioning import Version, get_active_version, resolve_version

_SCHEMA_RE = re.compile(r"^cat_[a-z0-9_]+$")
_FLAG_KIND = "evidence_gate_failure"
_CONTRADICTION_MIN_STORIES = 25  # same delivery threshold the G3 lifecycle scan uses

# ERS blend (PRD: tier · recency · specificity · corroboration). Components are persisted in
# control.ers.components so every score is decomposable in the UI.
_ERS_WEIGHTS = {"tier": 0.35, "recency": 0.25, "specificity": 0.20, "corroboration": 0.20}
_TIER_SCORE = {"T1": 0.95, "T2": 0.78, "T3": 0.55, "T4": 0.40, "T5": 0.25}

_IMPACT_LABEL = {
    "descriptor_revision": "Descriptor revision",
    "new_use_case": "New use-case candidate",
    "net_new_subcap": "Net-new subcap",
    "retire_candidate": "Retire candidate",
    "watchlist": "Watchlist · no change yet",
}
_SOURCE_TYPE_LABEL = {
    "regulator": "Regulator",
    "analyst": "Analyst",
    "vendor": "Vendor",
    "trade_press": "Trade press",
    "peer": "Peer",
    "benchmark": "Benchmark",
}

# Weak grounding never asserts more than the evidence supports (G5 no-fabrication): one notch
# down, capped at HYPOTHESIS. CEILING_ESTIMATE is a sized-claim label — weakly grounded sizing
# is a hypothesis, not a ceiling.
_DOWNGRADE = {
    "FACT": "INFERENCE",
    "INFERENCE": "HYPOTHESIS",
    "HYPOTHESIS": "HYPOTHESIS",
    "CEILING_ESTIMATE": "HYPOTHESIS",
}


@dataclass
class NewsSource:
    name: str
    type: str
    tier: str
    url: str
    ers: float
    fetched_at: str


@dataclass
class NewsRow:
    id: str
    title: str
    date: str
    mag: str
    tier: str
    label: str
    impact: str
    impact_label: str
    impact_note: str
    reliability: float
    source: NewsSource
    affects: list[list[Any]]  # [subcap_id, score, name, mag]
    chain: str | None


@dataclass
class NewsList:
    items: list[NewsRow]
    impacts: list[dict[str, str]]  # distinct {v, l} filter options present in the data
    scan: dict[str, Any]


def _recency(published: datetime, now: datetime) -> float:
    days = max(0, (now - published).days)
    if days <= 45:
        return 1.0
    if days <= 120:
        return 0.8
    if days <= 240:
        return 0.6
    return 0.4


def compute_ers(
    *,
    tier: str,
    published: datetime,
    specificity: float,
    corroboration: float,
    now: datetime | None = None,
) -> tuple[dict[str, float], float]:
    """ERS = weighted blend of tier · recency · specificity · corroboration, with the components
    persisted alongside the score so the envelope is decomposable (no opaque numbers)."""
    t = now or datetime.now(UTC)
    components = {
        "tier": _TIER_SCORE.get(tier, 0.25),
        "recency": _recency(published, t),
        "specificity": round(specificity, 2),
        "corroboration": round(corroboration, 2),
    }
    score = round(sum(_ERS_WEIGHTS[k] * v for k, v in components.items()), 3)
    return components, score


def _item_mag(impact: str, tier: str) -> str:
    """Deterministic magnitude classification (the hermetic stand-in for the classify model)."""
    if impact in ("net_new_subcap", "retire_candidate"):
        return "HIGH" if tier in ("T1", "T2") else "MEDIUM"
    if impact == "descriptor_revision":
        return "HIGH" if tier == "T1" else "MEDIUM"
    if impact == "new_use_case":
        return "MEDIUM"
    return "LOW"


def _impact_scores(rows: list[dict[str, Any]], strength: float) -> list[tuple[str, float, str]]:
    """(subcap_id, score, mag) per grounded subcap. Within an item, scores descend with retrieval
    rank across the prototype's 0.5-0.85 band; the whole band is then scaled by ``strength`` —
    the item's ABSOLUTE grounding strength (top rank vs the strong-grounding bar, 1.0 when
    strongly grounded) — so a weakly grounded item renders visibly cooler chips and its mags
    follow the scaled scores. Garbage never reaches here: the caller floors matches first."""
    if not rows:
        return []
    top = max(float(r["rank"]) for r in rows) or 1.0
    out: list[tuple[str, float, str]] = []
    for r in rows:
        score = round((0.5 + 0.35 * (float(r["rank"]) / top)) * strength, 2)
        mag = "HIGH" if score >= 0.75 else ("MEDIUM" if score >= 0.6 else "LOW")
        out.append((str(r["subcap_id"]), score, mag))
    return out


async def _max_delivery(conn: AsyncConnection, version_id: str, subcap_ids: list[str]) -> int:
    if not subcap_ids:
        return 0
    rows = await conn.execute(
        text(
            "SELECT coalesce(max(n), 0) FROM (SELECT count(*) AS n "
            "FROM control.story_catalogue_link WHERE version_id = :ver "
            "AND subcap_id = ANY(:ids) GROUP BY subcap_id) x"
        ),
        {"ver": version_id, "ids": subcap_ids},
    )
    return int(rows.scalar() or 0)


async def scan_news(version: str) -> dict[str, Any]:
    """Run the weekly news job once (idempotent): fetch -> dedupe -> enrich -> map -> gate ->
    persist. Re-running creates nothing new; every outcome lands in ingest_run.stats."""
    v = await resolve_version(version)
    schema = v.schema_name
    if not _SCHEMA_RE.match(schema):
        raise ValueError("invalid version schema")
    engine = db.get_engine()
    if engine is None:
        raise RuntimeError("database not initialised")

    fetched = await scout.fetch_items()
    created = deduped = mapped = flagged = 0
    async with engine.begin() as conn:
        for raw in fetched:
            duplicate = (
                await conn.execute(
                    text(
                        "SELECT 1 FROM control.news_item n "
                        "JOIN control.evidence_item e ON e.evidence_id = n.evidence_id "
                        "WHERE n.source = :s AND n.headline = :h"
                    ),
                    {"s": raw.source, "h": raw.headline},
                )
            ).first()
            if duplicate is not None:
                deduped += 1
                continue
            # Enrich AFTER dedupe so a re-scan never re-classifies (zero marginal model spend);
            # the live job batch-enriches new items before opening the write transaction.
            enr = await scout.enrich(raw)
            ok = await _ingest_one(conn, v, schema, raw, enr)
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
                "VALUES (:ver, 'news', 'succeeded', now(), CAST(:s AS jsonb))"
            ),
            {"ver": v.version_id, "s": json.dumps(stats)},
        )
    return {"version": v.version_id, **stats}


async def _ingest_one(
    conn: AsyncConnection, v: Version, schema: str, raw: RawNewsItem, enr: NewsEnrichment
) -> bool:
    """Map + gate + persist ONE fetched-and-enriched item. Returns True when its impacts were
    written (gates passed); False when it was queued to Change Flags instead."""
    published = datetime.fromisoformat(raw.published).replace(tzinfo=UTC)
    floor, strong = gates.evidence_thresholds()
    matches = await retrieval.retrieve(conn, schema, enr.topics, k=3)
    # Relevance floor (G5): matches below it are noise — an off-catalogue story maps to nothing.
    grounded = [m for m in matches if float(m["rank"]) >= floor]
    top_rank = max((float(m["rank"]) for m in grounded), default=0.0)
    strength = min(1.0, top_rank / strong) if grounded else 0.0
    weak = bool(grounded) and top_rank < strong
    # Weak grounding lowers the claim, never the other way (G5 no-fabrication).
    claim_label = _DOWNGRADE[enr.claim_label] if weak else enr.claim_label
    impacts = _impact_scores(grounded, strength)
    contradicts = False
    if enr.impact == "retire_candidate":
        # A retire signal against a subcap with active delivery is a genuine G6 contradiction.
        delivery = await _max_delivery(conn, v.version_id, [s for s, _, _ in impacts])
        contradicts = delivery >= _CONTRADICTION_MIN_STORIES
    results, verdict = gates.evaluate_evidence(
        source_tier=raw.tier,
        retrieval_count=len(matches),
        grounded_count=len(grounded),
        cited=True,
        contradicts=contradicts,
    )
    components, ers = compute_ers(
        tier=raw.tier,
        published=published,
        specificity=enr.specificity,
        corroboration=min(1.0, 0.4 + 0.2 * len(impacts)),
    )

    evidence_id = (
        await conn.execute(
            text(
                "INSERT INTO control.evidence_item (kind, title, url, source_tier, published_at, "
                "source_name, source_type, catalogue_impact, impact_note) "
                "VALUES ('news', :t, :u, CAST(:tier AS source_tier), :p, :sn, "
                "CAST(:st AS source_type), CAST(:ci AS catalogue_impact), :note) "
                "RETURNING evidence_id"
            ),
            {
                "t": raw.headline,
                "u": raw.url,
                "tier": raw.tier,
                "p": published,
                "sn": raw.source,
                "st": raw.source_type,
                "ci": enr.impact,
                "note": enr.impact_note,
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
    news_id = (
        await conn.execute(
            text(
                "INSERT INTO control.news_item "
                "(evidence_id, source, headline, published_at, fs_relevance) "
                "VALUES (:e, :s, :h, :p, :r) RETURNING news_id"
            ),
            {
                "e": evidence_id,
                "s": raw.source,
                "h": raw.headline,
                "p": published,
                "r": enr.specificity,
            },
        )
    ).scalar_one()

    summary = (
        f"{_IMPACT_LABEL[enr.impact]}: {enr.impact_note}. Mapped to "
        f"{len(impacts)} subcap(s) via catalogue retrieval; ERS {ers:.2f}."
    )
    chain_id = (
        await conn.execute(
            text(
                "INSERT INTO control.reasoning_chain "
                "(operation, subject_ref, claim_label, summary, model, cost_usd) "
                "VALUES ('enrich', :subj, CAST(:cl AS claim_label), :sum, :model, 0) "
                "RETURNING chain_id"
            ),
            {"subj": raw.headline, "cl": claim_label, "sum": summary, "model": enr.model},
        )
    ).scalar_one()
    retrieved = (
        ", ".join(f"{s} ({sc:.2f})" for s, sc, _ in impacts)
        or "no subcap above the relevance floor"
    )
    steps = [
        (
            "retrieve",
            f"Weekly grounded scan fetched the item from {raw.source} "
            f"({raw.tier}); topic retrieval over the {v.version_id} catalogue "
            f"(relevance floor {floor}) mapped it to {retrieved}.",
            evidence_id,
        ),
        (
            "weigh",
            "ERS components — tier {tier:.2f} · recency {recency:.2f} · specificity "
            "{specificity:.2f} · corroboration {corroboration:.2f} -> ".format(**components)
            + f"{ers:.2f}.",
            None,
        ),
    ]
    if weak:
        steps.append(
            (
                "weigh",
                f"Grounding is weak (top retrieval rank {top_rank:.4f} is under the "
                f"strong-grounding bar {strong}): claim label downgraded "
                f"{enr.claim_label} -> {claim_label} and mapping scores scaled by "
                f"{strength:.2f} — never assert more than the evidence supports (G5).",
                None,
            )
        )
    steps.append(
        (
            "conclude",
            f"Expected catalogue impact: {_IMPACT_LABEL[enr.impact]} — " f"{enr.impact_note}.",
            None,
        )
    )
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
    await conn.execute(
        text(
            "INSERT INTO control.validation_gate_run (chain_id, target_ref, gate_results, verdict)"
            " VALUES (:c, :t, CAST(:r AS jsonb), CAST(:v AS gate_verdict))"
        ),
        {"c": chain_id, "t": f"news:{news_id}", "r": json.dumps(results), "v": verdict},
    )

    if verdict != "pass":
        # Queued, not dropped: the item is never shown as mapped; a human resolves it (G3 inbox).
        gate = gates.first_failing(results) or "G5_similarity_grounding"
        detail = {
            "title": f"News item failed {gate.split('_')[0]}: {raw.headline}",
            "body": (
                f"{raw.source} ({raw.tier}) · {_IMPACT_LABEL[enr.impact]}. "
                f"{enr.impact_note}. The gate run failed {gate}, so no subcap impact was "
                "written — review the source before it can influence the catalogue."
            ),
            "gate_failed": gate,
            "version": v.version_id,
            "news_id": str(news_id),
            "source": raw.source,
            "tier": raw.tier,
            "url": raw.url,
        }
        await conn.execute(
            text(
                "INSERT INTO control.change_flag (kind, severity, target_ref, detail, chain_id) "
                "VALUES (:k, :sev, :t, CAST(:d AS jsonb), :c)"
            ),
            {
                "k": _FLAG_KIND,
                "sev": "HIGH" if raw.tier == "T1" else "MED",
                "t": f"news:{news_id}",
                "d": json.dumps(detail),
                "c": chain_id,
            },
        )
        return False

    for subcap_id, score, mag in impacts:
        await conn.execute(
            text(
                "INSERT INTO control.news_subcap_impact "
                "(news_id, version_id, subcap_id, mag, chain_id, score) "
                "VALUES (:n, :ver, :s, CAST(:m AS magnitude), :c, :sc)"
            ),
            {
                "n": news_id,
                "ver": v.version_id,
                "s": subcap_id,
                "m": mag,
                "c": chain_id,
                "sc": score,
            },
        )
    return True


async def _scan_status(conn: AsyncConnection) -> dict[str, Any]:
    last = (
        await conn.execute(
            text(
                "SELECT finished_at::text FROM control.ingest_run "
                "WHERE source = 'news' AND status = 'succeeded' "
                "ORDER BY finished_at DESC LIMIT 1"
            )
        )
    ).scalar()
    sched = schedule.describe("news_scan")
    return {
        "last_scan": last,
        "next_scan": sched["next_run"],
        "cadence": "weekly",
        "cron": sched["cron"],
    }


async def list_news(
    impact: str | None = None, tier: str | None = None, version: str | None = None
) -> NewsList:
    """The News watch read model: gated items only (a failed item lives in Change Flags), each
    with the surfaceable source sub-object {name,type,tier,url,ers,fetched_at} (R6)."""
    v = await (resolve_version(version) if version else get_active_version())
    engine = db.get_engine()
    if engine is None or v is None:
        # Degraded (no DB / no version): the schedule is still known from config, so the
        # cadence stays honest even when there is nothing to list.
        sched = schedule.describe("news_scan")
        return NewsList(
            items=[],
            impacts=[],
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
    if impact:
        filters += " AND e.catalogue_impact = CAST(:impact AS catalogue_impact)"
        params["impact"] = impact
    if tier:
        filters += " AND e.source_tier = CAST(:tier AS source_tier)"
        params["tier"] = tier

    async with engine.connect() as conn:
        rows = (
            (
                await conn.execute(
                    text(
                        "SELECT n.news_id::text AS id, e.title, e.url, "
                        "e.source_tier::text AS tier, e.source_name, e.source_type::text AS stype,"
                        " e.catalogue_impact::text AS impact, e.impact_note, "
                        "to_char(e.published_at, 'Mon YYYY') AS date, "
                        "e.created_at::text AS fetched_at, "
                        "(SELECT score::float FROM control.ers er WHERE er.evidence_id = "
                        "e.evidence_id ORDER BY er.computed_at DESC LIMIT 1) AS ers, "
                        "(SELECT vr.chain_id::text FROM control.validation_gate_run vr "
                        "WHERE vr.target_ref = 'news:' || n.news_id::text "
                        "ORDER BY vr.created_at DESC LIMIT 1) AS chain, "
                        "(SELECT rc.claim_label::text FROM control.reasoning_chain rc "
                        "JOIN control.validation_gate_run vr2 ON vr2.chain_id = rc.chain_id "
                        "WHERE vr2.target_ref = 'news:' || n.news_id::text "
                        "ORDER BY vr2.created_at DESC LIMIT 1) AS label "
                        "FROM control.news_item n "
                        "JOIN control.evidence_item e ON e.evidence_id = n.evidence_id "
                        "WHERE EXISTS (SELECT 1 FROM control.news_subcap_impact i "
                        f"WHERE i.news_id = n.news_id AND i.version_id = :ver){filters} "
                        "ORDER BY e.published_at DESC, n.news_id"
                    ),
                    params,
                )
            )
            .mappings()
            .all()
        )
        impact_rows = (
            (
                await conn.execute(
                    text(
                        "SELECT i.news_id::text AS id, i.subcap_id, i.score::float AS score, "
                        "i.mag::text AS mag, s.name "
                        "FROM control.news_subcap_impact i "
                        f"JOIN {schema}.subcap s ON s.subcap_id = i.subcap_id "
                        "WHERE i.version_id = :ver ORDER BY i.news_id, i.score DESC, i.subcap_id"
                    ),
                    {"ver": v.version_id},
                )
            )
            .mappings()
            .all()
        )
        scan = await _scan_status(conn)

    affects: dict[str, list[list[Any]]] = {}
    for r in impact_rows:
        affects.setdefault(r["id"], []).append(
            [r["subcap_id"], float(r["score"] or 0), r["name"], r["mag"]]
        )
    items = [
        NewsRow(
            id=r["id"],
            title=r["title"],
            date=r["date"],
            mag=_item_mag(r["impact"], r["tier"]),
            tier=r["tier"],
            label=r["label"] or "INFERENCE",
            impact=r["impact"],
            impact_label=_IMPACT_LABEL.get(r["impact"], r["impact"]),
            impact_note=r["impact_note"] or "",
            reliability=float(r["ers"] or 0),
            source=NewsSource(
                name=r["source_name"] or "",
                type=_SOURCE_TYPE_LABEL.get(r["stype"] or "", r["stype"] or ""),
                tier=r["tier"],
                url=r["url"] or "",
                ers=float(r["ers"] or 0),
                fetched_at=r["fetched_at"],
            ),
            affects=affects.get(r["id"], []),
            chain=r["chain"],
        )
        for r in rows
    ]
    present = sorted({i.impact for i in items})
    options = [{"v": k, "l": _IMPACT_LABEL.get(k, k)} for k in present]
    return NewsList(items=items, impacts=options, scan=scan)


# The consultant loop (cia-loop): raise a GATED suggestion from a news item — never a live edit.
# The expected-catalogue-impact class drives the suggestion kind (R5); only classes whose mutation
# the apply path supports stage one, the rest refuse with the product reason.
_LOOP_REFUSALS = {
    "watchlist": "Watchlist items are monitored only — no catalogue edit is warranted yet.",
    "net_new_subcap": (
        "Net-new subcap creation runs through the mapping studio (J1) so the taxonomy stays "
        "MECE — it cannot be staged as an in-place edit."
    ),
}


async def propose_from_news(news_id: str, actor: str) -> dict[str, Any]:
    """Stage a pending suggestion from a gated news item: thesis -> cited evidence (the news item
    + the target's catalogue entry) -> G1-G8 -> control.suggestion. Apply stays in D3 and
    RE-GATES server-side; nothing here touches cat_<v>."""
    engine = db.get_engine()
    if engine is None:
        raise RuntimeError("database not initialised")
    async with engine.begin() as conn:
        item = (
            (
                await conn.execute(
                    text(
                        "SELECT n.news_id, n.evidence_id, e.title, e.source_name, "
                        "e.source_tier::text AS tier, e.catalogue_impact::text AS impact, "
                        "e.impact_note, "
                        "(SELECT er.score::float FROM control.ers er "
                        "WHERE er.evidence_id = e.evidence_id "
                        "ORDER BY er.computed_at DESC LIMIT 1) AS ers "
                        "FROM control.news_item n "
                        "JOIN control.evidence_item e ON e.evidence_id = n.evidence_id "
                        "WHERE n.news_id = CAST(:id AS uuid)"
                    ),
                    {"id": news_id},
                )
            )
            .mappings()
            .first()
        )
        if item is None:
            return {"staged": False, "status": "not_found"}
        refusal = _LOOP_REFUSALS.get(item["impact"] or "")
        if refusal:
            return {"staged": False, "status": "refused", "reason": refusal}

        top = (
            (
                await conn.execute(
                    text(
                        "SELECT i.version_id, i.subcap_id, i.score::float AS score "
                        "FROM control.news_subcap_impact i WHERE i.news_id = CAST(:id AS uuid) "
                        "ORDER BY i.score DESC, i.subcap_id LIMIT 1"
                    ),
                    {"id": news_id},
                )
            )
            .mappings()
            .first()
        )
        if top is None:  # gate-failed item: lives in Change Flags, cannot seed a suggestion
            return {
                "staged": False,
                "status": "refused",
                "reason": "This item failed gating and is queued in Change Flags — resolve it "
                "there first.",
            }
        v = await resolve_version(str(top["version_id"]))
        schema = v.schema_name
        if not _SCHEMA_RE.match(schema):
            raise ValueError("invalid version schema")
        target = str(top["subcap_id"])
        sub = (
            (
                await conn.execute(
                    text(
                        f"SELECT name, description, lifecycle_state FROM {schema}.subcap "
                        "WHERE subcap_id = :t"
                    ),
                    {"t": target},
                )
            )
            .mappings()
            .first()
        )
        if sub is None:
            return {"staged": False, "status": "refused", "reason": "target subcap not found"}

        kind, payload_delta, breaking = _loop_payload(dict(item), dict(sub), target)
        dup = (
            await conn.execute(
                text(
                    "SELECT 1 FROM control.suggestion WHERE target_subcap = :t AND kind = :k "
                    "AND status = 'pending' AND payload ->> 'news_id' = :n"
                ),
                {"t": target, "k": kind, "n": str(item["news_id"])},
            )
        ).first()
        if dup is not None:
            return {"staged": False, "status": "duplicate", "kind": kind, "target": target}

        results, verdict = gates.evaluate_suggestion(
            target_exists=True,
            evidence_count=2,  # the news evidence + the target's catalogue evidence, both cited
            source_tier=str(item["tier"]),
            cited=True,
            contradicts=False,
            cost_usd=0.0,
        )
        title = f"{_IMPACT_LABEL[item['impact']]}: {sub['name']}"
        rationale = (
            f"{item['source_name']} ({item['tier']}) — {item['title']}. "
            f"{item['impact_note']}. Staged from News watch; the impact class drives the kind."
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
                    f"News evidence {item['title']!r} mapped to {target} "
                    f"(score {float(top['score'] or 0):.2f}).",
                    item["evidence_id"],
                ),
                (
                    "conclude",
                    f"Propose a {kind} on {target}, grounded in the cited news item and the "
                    "catalogue entry.",
                    catalogue_ev,
                ),
            ),
            start=1,
        ):
            await conn.execute(
                text(
                    "INSERT INTO control.reasoning_step "
                    "(chain_id, ordinal, kind, text, evidence_id) "
                    "VALUES (:c, :o, :k, :t, :e)"
                ),
                {"c": chain_id, "o": ordinal, "k": kind_s, "t": txt, "e": ev},
            )
        for ev in (item["evidence_id"], catalogue_ev):
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
        payload = {
            "title": title,
            "rationale": rationale,
            "subcap_name": sub["name"],
            "pillar": target[:2],
            "news_id": str(item["news_id"]),
            "impact": item["impact"],
            "gate_results": results,
            "verdict": verdict,
            "breaking": breaking,
            **payload_delta,
        }
        suggestion_id = (
            await conn.execute(
                text(
                    "INSERT INTO control.suggestion (target_version, target_subcap, kind, "
                    "payload, claim_label, source_tier, ers, chain_id, status, created_by) "
                    "VALUES (:ver, :sub, :k, CAST(:p AS jsonb), 'INFERENCE', "
                    "CAST(:tier AS source_tier), :ers, :chain, 'pending', "
                    "(SELECT uid FROM control.users WHERE uid = :actor)) RETURNING suggestion_id"
                ),
                {
                    "ver": v.version_id,
                    "sub": target,
                    "k": kind,
                    "p": json.dumps(payload),
                    "tier": item["tier"],
                    "ers": item["ers"],
                    "chain": chain_id,
                    "actor": actor,
                },
            )
        ).scalar_one()
    return {
        "staged": True,
        "status": "pending",
        "suggestion_id": str(suggestion_id),
        "kind": kind,
        "target": target,
    }


def _loop_payload(
    item: dict[str, Any], sub: dict[str, Any], target: str
) -> tuple[str, dict[str, Any], bool]:
    """The impact class -> (suggestion kind, before/after mutation payload, breaking)."""
    if item["impact"] == "retire_candidate":
        return (
            "lifecycle_demotion",
            {
                "before": {"lifecycle_state": sub["lifecycle_state"]},
                "after": {"lifecycle_state": "declining"},
            },
            False,
        )
    if item["impact"] == "new_use_case":
        uc_id = f"UC-NEWS-{str(item['news_id'])[:8]}"
        return (
            "new_use_case",
            {
                "before": {},
                "after": {
                    "use_case": {
                        "use_case_id": uc_id,
                        "archetype": "Emerging",
                        "name": str(item["title"])[:80],
                        "description": f"{item['impact_note']} (per {item['source_name']}, "
                        f"{item['tier']}).",
                    }
                },
            },
            False,
        )
    # descriptor_revision: a deterministic drafted edit in hermetic mode (the enrich model drafts
    # this text in live mode); apply writes it only after a clean server-side re-gate.
    current = str(sub["description"] or "").rstrip()
    drafted = (
        f"{current} 2026 update ({item['source_name']}, {item['tier']}): {item['title']}."
    ).strip()
    return (
        "descriptor_update",
        {"before": {"description": current}, "after": {"description": drafted}},
        False,
    )
