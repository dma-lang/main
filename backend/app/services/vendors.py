"""F2 — vendor intelligence: weekly developments -> eight typed events -> subcap impact.

Pipeline (spec §F2): fetch vendor newsrooms/release notes (weekly Batch; hermetic = recorded
fixture) -> dedupe (vendor + headline) -> TYPE each development into the eight vendor_event_type
classes on the pinned flash-lite model (an untypable event lands in REVIEW, never mis-typed
silently) -> map to subcaps via stored-catalogue retrieval (relevance floor) -> gate
(G1/G5/G6/G7 — the G3 tier floor is deliberately NOT applied to the display path: vendor signal
is honestly T4/T5 and the feed says so; the floor bites where it matters, in the consultant loop)
-> persist control.vendor + vendor_event + vendor_subcap_impact (mag · recency_weight · chain).

The heatmap is EVIDENCE-DRIVEN: cell intensity = sum(impact score x recency_weight) per
(vendor, subcap) — frequency x recency, never the static platform join. A development naming a
vendor absent from the catalogue's vendor dimension raises a registry flag (and still ingests).
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app import db
from app.intelligence import gates, retrieval
from app.intelligence import vendors as scout
from app.intelligence.vendors import RawVendorEvent, VendorTyping
from app.jobs import schedule
from app.services import sources
from app.services.evidence import (
    _CONTRADICTION_MIN_STORIES,
    _SCHEMA_RE,
    _impact_scores,
    _max_delivery,
    compute_ers,
)
from app.services.suggestions import _catalogue_evidence
from app.versioning import Version, get_active_version, resolve_version

_FLAG_KIND = "evidence_gate_failure"
_REGISTRY_FLAG_KIND = "vendor_registry"
_TYPE_LABEL = {
    "product_launch": "Product launch",
    "partnership": "Partnership",
    "deprecation": "Deprecation",
    "pricing_change": "Pricing change",
    "executive_move": "Executive move",
    "security_incident": "Security incident",
    "regulatory_action": "Regulatory action",
    "case_study": "Case study",
}
# Deterministic event-level magnitude (the hermetic stand-in for the typing model's impact size).
_TYPE_MAG = {
    "deprecation": "HIGH",
    "security_incident": "HIGH",
    "regulatory_action": "HIGH",
    "product_launch": "MEDIUM",
    "partnership": "MEDIUM",
    "pricing_change": "MEDIUM",
    "case_study": "LOW",
    "executive_move": "LOW",
}


def _slug(name: str) -> str:
    return "VEN-" + re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _recency_weight(published: datetime, now: datetime | None = None) -> float:
    """The recency dimension of the heatmap's frequency x recency product (numeric(4,3))."""
    days = max(0, ((now or datetime.now(UTC)) - published).days)
    if days <= 30:
        return 1.0
    if days <= 90:
        return 0.85
    if days <= 180:
        return 0.6
    return 0.4


@dataclass
class VendorProfile:
    vendor_id: str
    name: str
    platforms: int  # L3 platforms this vendor provides in the active catalogue
    developments_90d: int
    subcaps_touched: int
    heat: float  # sum of impact x recency across its events


@dataclass
class VendorEventRow:
    id: str
    vendor: str
    vendor_id: str
    event_type: str
    type_label: str
    title: str
    date: str
    mag: str
    tier: str
    label: str
    impact_note: str
    reliability: float
    source: dict[str, Any]  # {name,type,tier,url,ers,fetched_at} (R6)
    affects: list[list[Any]]  # [subcap_id, score, name, mag]
    chain: str | None


@dataclass
class HeatCell:
    vendor: str
    subcap_id: str
    name: str
    score: float


@dataclass
class VendorList:
    vendors: list[VendorProfile]
    items: list[VendorEventRow]
    heat: list[HeatCell]
    types: list[dict[str, str]]
    scan: dict[str, Any]


async def scan_vendors(version: str) -> dict[str, Any]:
    """Run the weekly vendor job once (idempotent): fetch -> dedupe -> type -> map -> gate ->
    persist. Untypable events queue to review; unknown vendors raise a registry flag."""
    v = await resolve_version(version)
    schema = v.schema_name
    if not _SCHEMA_RE.match(schema):
        raise ValueError("invalid version schema")
    engine = db.require_engine()
    async with engine.connect() as conn:
        # Registry guard BEFORE the fetch: a disabled source never pulls (and never spends).
        await sources.ensure_enabled(conn, "vendor")

    fetched = await scout.fetch_events()
    created = deduped = mapped = flagged = review = registry_flags = 0
    async with engine.begin() as conn:
        for raw in fetched:
            vendor_id = _slug(raw.vendor)
            duplicate = (
                await conn.execute(
                    text(
                        "SELECT 1 FROM control.vendor_event "
                        "WHERE vendor_id = :v AND headline = :h"
                    ),
                    {"v": vendor_id, "h": raw.headline},
                )
            ).first()
            if duplicate is not None:
                deduped += 1
                continue
            # Untypable dedupe key lives on the review flag (no vendor_event row exists for it).
            untypable_dup = (
                await conn.execute(
                    text(
                        "SELECT 1 FROM control.change_flag "
                        "WHERE kind = :k AND detail ->> 'headline' = :h"
                    ),
                    {"k": _FLAG_KIND, "h": raw.headline},
                )
            ).first()
            if untypable_dup is not None:
                deduped += 1
                continue
            # Type AFTER dedupe so a re-scan never re-classifies (zero marginal model spend).
            typing = await scout.classify_event(raw)
            created += 1
            outcome = await _ingest_one(conn, v, schema, vendor_id, raw, typing)
            if outcome == "mapped":
                mapped += 1
            elif outcome == "review":
                review += 1
            else:
                flagged += 1
            if outcome == "mapped" and not await _known_vendor(conn, schema, raw.vendor):
                registry_flags += 1
                await _registry_flag(conn, v, vendor_id, raw)
        stats = {
            "fetched": len(fetched),
            "created": created,
            "deduped": deduped,
            "mapped": mapped,
            "review": review,
            "flagged": flagged,
            "registry_flags": registry_flags,
        }
        await conn.execute(
            text(
                "INSERT INTO control.ingest_run (version_id, source, status, finished_at, stats) "
                "VALUES (:ver, 'vendor', 'succeeded', now(), CAST(:s AS jsonb))"
            ),
            {"ver": v.version_id, "s": json.dumps(stats)},
        )
    return {"version": v.version_id, **stats}


async def _known_vendor(conn: AsyncConnection, schema: str, name: str) -> bool:
    row = (
        await conn.execute(
            text(f"SELECT 1 FROM {schema}.vendor WHERE lower(name) = lower(:n)"), {"n": name}
        )
    ).first()
    return row is not None


async def _registry_flag(
    conn: AsyncConnection, v: Version, vendor_id: str, raw: RawVendorEvent
) -> None:
    """A development names a vendor the catalogue's vendor dimension does not know: raise a
    registry flag for an admin to add/map the vendor — the event itself still ingested."""
    detail = {
        "title": f"New vendor not in the catalogue registry: {raw.vendor}",
        "body": (
            f"{raw.source} published {raw.headline!r}, but {raw.vendor!r} is not in the "
            f"{v.version_id} vendor dimension. Add or map the vendor in the mapping studio; "
            "its developments are ingested meanwhile."
        ),
        "vendor": raw.vendor,
        "vendor_id": vendor_id,
        "version": v.version_id,
        "url": raw.url,
    }
    await conn.execute(
        text(
            "INSERT INTO control.change_flag (kind, severity, target_ref, detail) "
            "VALUES (:k, 'LOW', :t, CAST(:d AS jsonb))"
        ),
        {"k": _REGISTRY_FLAG_KIND, "t": f"vendor:{vendor_id}", "d": json.dumps(detail)},
    )


async def _ingest_one(
    conn: AsyncConnection,
    v: Version,
    schema: str,
    vendor_id: str,
    raw: RawVendorEvent,
    typing: VendorTyping,
) -> str:
    """Persist ONE fetched-and-typed development. Returns 'mapped' | 'review' (untypable) |
    'flagged' (gate failure)."""
    published = datetime.fromisoformat(raw.published).replace(tzinfo=UTC)
    components, ers = compute_ers(
        tier=raw.tier,
        published=published,
        specificity=typing.specificity,
        corroboration=0.5,
    )
    evidence_id = (
        await conn.execute(
            text(
                "INSERT INTO control.evidence_item (kind, title, url, source_tier, published_at,"
                " source_name, source_type, impact_note) "
                "VALUES ('vendor_event', :t, :u, CAST(:tier AS source_tier), :p, :sn, "
                "CAST(:st AS source_type), :note) RETURNING evidence_id"
            ),
            {
                "t": raw.headline,
                "u": raw.url,
                "tier": raw.tier,
                "p": published,
                "sn": raw.source,
                "st": raw.source_type,
                "note": typing.impact_note,
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

    if typing.event_type is None:
        # Untypable: review queue, never mis-typed silently. No vendor_event row is written.
        chain_id = (
            await conn.execute(
                text(
                    "INSERT INTO control.reasoning_chain "
                    "(operation, subject_ref, claim_label, summary, model, cost_usd) "
                    "VALUES ('enrich', :subj, 'HYPOTHESIS', :sum, :model, 0) RETURNING chain_id"
                ),
                {
                    "subj": raw.headline,
                    "sum": f"Untypable vendor development: {typing.impact_note}",
                    "model": typing.model,
                },
            )
        ).scalar_one()
        await conn.execute(
            text(
                "INSERT INTO control.citation (chain_id, evidence_id, verified) "
                "VALUES (:c, :e, true)"
            ),
            {"c": chain_id, "e": evidence_id},
        )
        detail = {
            "title": f"Vendor development could not be typed: {raw.headline}",
            "body": (
                f"{raw.source} ({raw.tier}) · {raw.vendor}. The typing model could not place "
                "this development in the eight event classes — review and type it manually; "
                "it was not mis-typed silently."
            ),
            "headline": raw.headline,
            "vendor": raw.vendor,
            "version": v.version_id,
            "url": raw.url,
        }
        await conn.execute(
            text(
                "INSERT INTO control.change_flag (kind, severity, target_ref, detail, chain_id) "
                "VALUES (:k, 'MED', :t, CAST(:d AS jsonb), :c)"
            ),
            {"k": _FLAG_KIND, "t": f"vendor:{vendor_id}", "d": json.dumps(detail), "c": chain_id},
        )
        return "review"

    # Vendor registry row (CP) — upsert keyed on the slug id.
    await conn.execute(
        text(
            "INSERT INTO control.vendor (vendor_id, name, homepage) VALUES (:i, :n, :h) "
            "ON CONFLICT (vendor_id) DO NOTHING"
        ),
        {"i": vendor_id, "n": raw.vendor, "h": raw.url},
    )

    floor, strong = gates.evidence_thresholds()
    matches = await retrieval.retrieve(conn, schema, typing.topics, k=3)
    grounded = [m for m in matches if float(m["rank"]) >= floor]
    top_rank = max((float(m["rank"]) for m in grounded), default=0.0)
    strength = min(1.0, top_rank / strong) if grounded else 0.0
    impacts = _impact_scores(grounded, strength)
    contradicts = False
    if typing.event_type == "deprecation":
        # A deprecation claim against subcaps with heavy live delivery is a G6 contradiction.
        delivery = await _max_delivery(conn, v.version_id, [s for s, _, _ in impacts])
        contradicts = delivery >= _CONTRADICTION_MIN_STORIES
    results, verdict = gates.evaluate_vendor_event(
        retrieval_count=len(matches),
        grounded_count=len(grounded),
        cited=True,
        contradicts=contradicts,
    )

    event_id = (
        await conn.execute(
            text(
                "INSERT INTO control.vendor_event "
                "(vendor_id, event_type, headline, occurred_at, evidence_id) "
                "VALUES (:v, CAST(:t AS vendor_event_type), :h, :o, :e) RETURNING event_id"
            ),
            {
                "v": vendor_id,
                "t": typing.event_type,
                "h": raw.headline,
                "o": published,
                "e": evidence_id,
            },
        )
    ).scalar_one()

    summary = (
        f"{_TYPE_LABEL[typing.event_type]} from {raw.vendor}: {typing.impact_note}. "
        f"Mapped to {len(impacts)} subcap(s); ERS {ers:.2f}."
    )
    chain_id = (
        await conn.execute(
            text(
                "INSERT INTO control.reasoning_chain "
                "(operation, subject_ref, claim_label, summary, model, cost_usd) "
                "VALUES ('enrich', :subj, CAST(:cl AS claim_label), :sum, :model, 0) "
                "RETURNING chain_id"
            ),
            {
                "subj": raw.headline,
                "cl": typing.claim_label,
                "sum": summary,
                "model": typing.model,
            },
        )
    ).scalar_one()
    retrieved = (
        ", ".join(f"{s} ({sc:.2f})" for s, sc, _ in impacts)
        or "no subcap above the relevance floor"
    )
    steps = [
        (
            "retrieve",
            f"Weekly vendor scan fetched the development from {raw.source} ({raw.tier}); typed "
            f"as {typing.event_type} and mapped over the {v.version_id} catalogue "
            f"(relevance floor {floor}) to {retrieved}.",
            evidence_id,
        ),
        (
            "weigh",
            "ERS components — tier {tier:.2f} · recency {recency:.2f} · specificity "
            "{specificity:.2f} · corroboration {corroboration:.2f} -> ".format(**components)
            + f"{ers:.2f}. Vendor-published material is low-tier by design; the tier renders "
            "on the card and the consultant loop refuses sub-T3 evidence.",
            None,
        ),
        (
            "conclude",
            f"{_TYPE_LABEL[typing.event_type]}: {typing.impact_note}.",
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
    await conn.execute(
        text(
            "INSERT INTO control.validation_gate_run (chain_id, target_ref, gate_results, "
            "verdict) VALUES (:c, :t, CAST(:r AS jsonb), CAST(:v AS gate_verdict))"
        ),
        {"c": chain_id, "t": f"vendor:{event_id}", "r": json.dumps(results), "v": verdict},
    )

    if verdict != "pass":
        gate = gates.first_failing(results) or "G5_similarity_grounding"
        detail = {
            "title": f"Vendor event failed {gate.split('_')[0]}: {raw.headline}",
            "body": (
                f"{raw.source} ({raw.tier}) · {raw.vendor} · "
                f"{_TYPE_LABEL[typing.event_type]}. {typing.impact_note}. The gate run failed "
                f"{gate}, so no subcap impact was written — review before it can influence "
                "the catalogue."
            ),
            "gate_failed": gate,
            "headline": raw.headline,
            "vendor": raw.vendor,
            "version": v.version_id,
            "url": raw.url,
        }
        await conn.execute(
            text(
                "INSERT INTO control.change_flag (kind, severity, target_ref, detail, chain_id) "
                "VALUES (:k, 'MED', :t, CAST(:d AS jsonb), :c)"
            ),
            {"k": _FLAG_KIND, "t": f"vendor:{event_id}", "d": json.dumps(detail), "c": chain_id},
        )
        return "flagged"

    rw = _recency_weight(published)
    for subcap_id, score, mag in impacts:
        await conn.execute(
            text(
                "INSERT INTO control.vendor_subcap_impact "
                "(event_id, version_id, subcap_id, mag, recency_weight, chain_id, score) "
                "VALUES (:e, :ver, :s, CAST(:m AS magnitude), :rw, :c, :sc)"
            ),
            {
                "e": event_id,
                "ver": v.version_id,
                "s": subcap_id,
                "m": mag,
                "rw": rw,
                "c": chain_id,
                "sc": score,
            },
        )
    return "mapped"


async def _scan_status(conn: AsyncConnection) -> dict[str, Any]:
    last = (
        await conn.execute(
            text(
                "SELECT finished_at::text FROM control.ingest_run "
                "WHERE source = 'vendor' AND status = 'succeeded' "
                "ORDER BY finished_at DESC LIMIT 1"
            )
        )
    ).scalar()
    sched = schedule.describe("vendor_scan")
    return {
        "last_scan": last,
        "next_scan": sched["next_run"],
        "cadence": "weekly",
        "cron": sched["cron"],
    }


async def list_vendor_events(
    event_type: str | None = None, version: str | None = None
) -> VendorList:
    """The Vendor intelligence read model: vendor profile cards, the typed developments feed
    (gated items only) and the evidence-driven vendor x subcap heat cells."""
    v = await (resolve_version(version) if version else get_active_version())
    engine = db.get_engine()
    if engine is None or v is None:
        sched = schedule.describe("vendor_scan")
        return VendorList(
            vendors=[],
            items=[],
            heat=[],
            types=[],
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
    if event_type:
        filters = " AND ve.event_type = CAST(:et AS vendor_event_type)"
        params["et"] = event_type

    async with engine.connect() as conn:
        rows = (
            (
                await conn.execute(
                    text(
                        "SELECT ve.event_id::text AS id, ve.event_type::text AS etype, "
                        "cv.name AS vendor, ve.vendor_id, e.title, e.url, "
                        "e.source_tier::text AS tier, e.source_name, "
                        "e.source_type::text AS stype, e.impact_note, "
                        "to_char(e.published_at, 'Mon YYYY') AS date, "
                        "e.created_at::text AS fetched_at, "
                        "(SELECT er.score::float FROM control.ers er WHERE er.evidence_id = "
                        "e.evidence_id ORDER BY er.computed_at DESC LIMIT 1) AS ers, "
                        "(SELECT rc.claim_label::text FROM control.reasoning_chain rc "
                        "JOIN control.validation_gate_run vr ON vr.chain_id = rc.chain_id "
                        "WHERE vr.target_ref = 'vendor:' || ve.event_id::text "
                        "ORDER BY vr.created_at DESC LIMIT 1) AS label, "
                        "(SELECT vr2.chain_id::text FROM control.validation_gate_run vr2 "
                        "WHERE vr2.target_ref = 'vendor:' || ve.event_id::text "
                        "ORDER BY vr2.created_at DESC LIMIT 1) AS chain "
                        "FROM control.vendor_event ve "
                        "JOIN control.vendor cv ON cv.vendor_id = ve.vendor_id "
                        "JOIN control.evidence_item e ON e.evidence_id = ve.evidence_id "
                        "WHERE EXISTS (SELECT 1 FROM control.vendor_subcap_impact i "
                        f"WHERE i.event_id = ve.event_id AND i.version_id = :ver){filters} "
                        "ORDER BY e.published_at DESC, ve.event_id"
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
                        "SELECT i.event_id::text AS id, i.subcap_id, i.score::float AS score, "
                        "i.mag::text AS mag, i.recency_weight::float AS rw, s.name, "
                        "cv.name AS vendor "
                        "FROM control.vendor_subcap_impact i "
                        "JOIN control.vendor_event ve ON ve.event_id = i.event_id "
                        "JOIN control.vendor cv ON cv.vendor_id = ve.vendor_id "
                        f"JOIN {schema}.subcap s ON s.subcap_id = i.subcap_id "
                        "WHERE i.version_id = :ver "
                        "ORDER BY i.event_id, i.score DESC, i.subcap_id"
                    ),
                    {"ver": v.version_id},
                )
            )
            .mappings()
            .all()
        )
        profile_rows = (
            (
                await conn.execute(
                    text(
                        "SELECT cv.vendor_id, cv.name, "
                        "(SELECT count(*) FROM control.vendor_event ve2 "
                        "WHERE ve2.vendor_id = cv.vendor_id "
                        "AND ve2.occurred_at >= now() - interval '90 days') AS dev90, "
                        f"coalesce((SELECT count(*) FROM {schema}.vendor dv "
                        f"JOIN {schema}.l3_platform lp ON lp.vendor_id = dv.vendor_id "
                        "WHERE lower(dv.name) = lower(cv.name)), 0) AS platforms "
                        "FROM control.vendor cv "
                        "WHERE EXISTS (SELECT 1 FROM control.vendor_event ve3 "
                        "JOIN control.vendor_subcap_impact i3 ON i3.event_id = ve3.event_id "
                        "WHERE ve3.vendor_id = cv.vendor_id AND i3.version_id = :ver) "
                        "ORDER BY cv.name"
                    ),
                    {"ver": v.version_id},
                )
            )
            .mappings()
            .all()
        )
        scan = await _scan_status(conn)

    affects: dict[str, list[list[Any]]] = {}
    heat_by_cell: dict[tuple[str, str], dict[str, Any]] = {}
    touched: dict[str, set[str]] = defaultdict(set)
    vendor_heat: dict[str, float] = defaultdict(float)
    for r in impact_rows:
        affects.setdefault(r["id"], []).append(
            [r["subcap_id"], float(r["score"] or 0), r["name"], r["mag"]]
        )
        cell = heat_by_cell.setdefault(
            (r["vendor"], r["subcap_id"]),
            {"vendor": r["vendor"], "subcap_id": r["subcap_id"], "name": r["name"], "score": 0.0},
        )
        # frequency x recency: each contributing event adds its impact score x recency weight
        cell["score"] += float(r["score"] or 0) * float(r["rw"] or 0)
        touched[r["vendor"]].add(r["subcap_id"])
        vendor_heat[r["vendor"]] += float(r["score"] or 0) * float(r["rw"] or 0)

    items = [
        VendorEventRow(
            id=r["id"],
            vendor=r["vendor"],
            vendor_id=r["vendor_id"],
            event_type=r["etype"],
            type_label=_TYPE_LABEL.get(r["etype"], r["etype"]),
            title=r["title"],
            date=r["date"],
            mag=_TYPE_MAG.get(r["etype"], "LOW"),
            tier=r["tier"],
            label=r["label"] or "HYPOTHESIS",
            impact_note=r["impact_note"] or "",
            reliability=float(r["ers"] or 0),
            source={
                "name": r["source_name"] or "",
                "type": r["stype"] or "",
                "tier": r["tier"],
                "url": r["url"] or "",
                "ers": float(r["ers"] or 0),
                "fetched_at": r["fetched_at"],
            },
            affects=affects.get(r["id"], []),
            chain=r["chain"],
        )
        for r in rows
    ]
    vendors = [
        VendorProfile(
            vendor_id=p["vendor_id"],
            name=p["name"],
            platforms=int(p["platforms"] or 0),
            developments_90d=int(p["dev90"] or 0),
            subcaps_touched=len(touched.get(p["name"], set())),
            heat=round(vendor_heat.get(p["name"], 0.0), 2),
        )
        for p in profile_rows
    ]
    heat = sorted(
        (HeatCell(**c) for c in heat_by_cell.values()),
        key=lambda c: (-c.score, c.vendor, c.subcap_id),
    )
    for c in heat:
        c.score = round(c.score, 2)
    present = sorted({i.event_type for i in items})
    types = [{"v": t, "l": _TYPE_LABEL.get(t, t)} for t in present]
    return VendorList(vendors=vendors, items=items, heat=heat, types=types, scan=scan)


async def propose_from_vendor_event(event_id: str, actor: str) -> dict[str, Any]:
    """Consultant loop from a development: stage a GATED suggestion — never a live edit. The G3
    source-tier floor bites HERE: sub-T3 vendor signal alone is refused (one low-tier source is
    not a basis for a catalogue edit); independent T3+ coverage stages. A deprecation stages a
    lifecycle_demotion; anything else a descriptor_update."""
    engine = db.require_engine()
    async with engine.begin() as conn:
        ev = (
            (
                await conn.execute(
                    text(
                        "SELECT ve.event_id, ve.event_type::text AS etype, ve.headline, "
                        "ve.evidence_id, cv.name AS vendor, e.source_name, "
                        "e.source_tier::text AS tier, e.impact_note, "
                        "(SELECT er.score::float FROM control.ers er "
                        "WHERE er.evidence_id = e.evidence_id "
                        "ORDER BY er.computed_at DESC LIMIT 1) AS ers "
                        "FROM control.vendor_event ve "
                        "JOIN control.vendor cv ON cv.vendor_id = ve.vendor_id "
                        "JOIN control.evidence_item e ON e.evidence_id = ve.evidence_id "
                        "WHERE ve.event_id = CAST(:id AS uuid)"
                    ),
                    {"id": event_id},
                )
            )
            .mappings()
            .first()
        )
        if ev is None:
            return {"staged": False, "status": "not_found"}
        if ev["tier"] not in ("T1", "T2", "T3"):
            return {
                "staged": False,
                "status": "refused",
                "reason": (
                    f"{ev['tier']} vendor-published signal alone cannot clear the G3 "
                    "source-tier floor — corroborate with independent (T3+) coverage first."
                ),
            }
        top = (
            (
                await conn.execute(
                    text(
                        "SELECT i.version_id, i.subcap_id, i.score::float AS score "
                        "FROM control.vendor_subcap_impact i "
                        "WHERE i.event_id = CAST(:id AS uuid) "
                        "ORDER BY i.score DESC, i.subcap_id LIMIT 1"
                    ),
                    {"id": event_id},
                )
            )
            .mappings()
            .first()
        )
        if top is None:
            return {
                "staged": False,
                "status": "refused",
                "reason": "This event failed gating and is queued in Change Flags — resolve it "
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
        kind = "lifecycle_demotion" if ev["etype"] == "deprecation" else "descriptor_update"
        dup = (
            await conn.execute(
                text(
                    "SELECT 1 FROM control.suggestion WHERE target_subcap = :t AND kind = :k "
                    "AND status = 'pending' AND payload ->> 'event_id' = :e"
                ),
                {"t": target, "k": kind, "e": str(ev["event_id"])},
            )
        ).first()
        if dup is not None:
            return {"staged": False, "status": "duplicate", "kind": kind, "target": target}

        results, verdict = gates.evaluate_suggestion(
            target_exists=True,
            evidence_count=2,  # the vendor evidence + the target's catalogue entry
            source_tier=str(ev["tier"]),
            cited=True,
            contradicts=False,
            cost_usd=0.0,
        )
        title = f"{_TYPE_LABEL.get(ev['etype'], ev['etype'])}: {sub['name']}"
        rationale = (
            f"{ev['source_name']} ({ev['tier']}) — {ev['headline']}. {ev['impact_note']}. "
            "Staged from Vendor intelligence; the event type drives the kind."
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
        for ordinal, (kind_s, txt, evd) in enumerate(
            (
                (
                    "retrieve",
                    f"Vendor development {ev['headline']!r} mapped to {target} "
                    f"(score {float(top['score'] or 0):.2f}).",
                    ev["evidence_id"],
                ),
                (
                    "conclude",
                    f"Propose a {kind} on {target}, grounded in the cited development and the "
                    "catalogue entry.",
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
                {"c": chain_id, "o": ordinal, "k": kind_s, "t": txt, "e": evd},
            )
        for evd in (ev["evidence_id"], catalogue_ev):
            await conn.execute(
                text(
                    "INSERT INTO control.citation (chain_id, evidence_id, verified) "
                    "VALUES (:c, :e, true)"
                ),
                {"c": chain_id, "e": evd},
            )
        await conn.execute(
            text(
                "INSERT INTO control.validation_gate_run "
                "(chain_id, target_ref, gate_results, verdict) "
                "VALUES (:c, :t, CAST(:r AS jsonb), CAST(:v AS gate_verdict))"
            ),
            {"c": chain_id, "t": target, "r": json.dumps(results), "v": verdict},
        )
        if kind == "lifecycle_demotion":
            payload_delta: dict[str, Any] = {
                "before": {"lifecycle_state": sub["lifecycle_state"]},
                "after": {"lifecycle_state": "declining"},
            }
        else:
            current = str(sub["description"] or "").rstrip()
            drafted = (
                f"{current} Vendor signal ({ev['source_name']}, {ev['tier']}): {ev['headline']}."
            ).strip()
            payload_delta = {
                "before": {"description": current},
                "after": {"description": drafted},
            }
        payload = {
            "title": title,
            "rationale": rationale,
            "subcap_name": sub["name"],
            "pillar": target[:2],
            "event_id": str(ev["event_id"]),
            "gate_results": results,
            "verdict": verdict,
            "breaking": False,
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
                    "tier": ev["tier"],
                    "ers": ev["ers"],
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
