"""Catalogue read surfaces (version-scoped, F9 conventions) over the cat_<version> data plane.

Lights up Capability workbench (tree + detail) and Mission control (pillar summary) on real data.
"""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app import db
from app.deps import get_current_user
from app.versioning import Version, resolve_version

router = APIRouter(prefix="/api/catalogue", tags=["catalogue"])

_SCHEMA_RE = re.compile(r"^cat_[a-z0-9_]+$")


def _engine() -> AsyncEngine:
    engine = db.get_engine()
    if engine is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="database unavailable")
    return engine


def _schema(v: Version) -> str:
    # schema_name comes from control.catalogue_version (our data); validated for defence in depth
    # since it is interpolated as a SQL identifier.
    if not _SCHEMA_RE.match(v.schema_name):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="invalid version schema")
    return v.schema_name


class SubcapNode(BaseModel):
    id: str
    name: str
    pillar: str
    cat_id: str
    cat_name: str
    cluster: str
    life: str
    is_new: bool


class SubcapDetail(BaseModel):
    id: str
    name: str
    pillar: str
    category: str
    cluster: str
    description: str | None = None
    solution_type: str | None = None
    tier: str | None = None
    lifecycle_state: str
    completeness: float | None = None
    # Live counts (truthful now, auto-correct as F5 carry-forward / enrichment seed these tables).
    n_use_cases: int = 0
    n_stories: int = 0
    n_platforms: int = 0


class PillarSummary(BaseModel):
    pillar_id: str
    name: str
    subcap_count: int
    completeness: float
    decay: int


class CatalogueSummary(BaseModel):
    version_id: str
    total_subcaps: int
    pillars: list[PillarSummary]


class StoryRow(BaseModel):
    story_key: str
    project_key: str | None = None
    summary: str | None = None
    confidence_level: str | None = None
    composite_score: float | None = None
    ac_score: float | None = None
    sd_score: float | None = None
    story_score: float | None = None
    story_sv_code: str | None = None
    tier: str | None = None
    is_synthetic: bool = False


# The carried-delivery source for a subcap. The analysis-grade default is JIRA-ONLY (matches the
# story_catalogue_link view + n_stories); `include_synthetic` adds the labelled synthetic stories
# the deep-dive toggle reveals. Same status floor as the view (confirmed | review).
def _carry_where(include_synthetic: bool) -> str:
    syn = "" if include_synthetic else "AND NOT st.is_synthetic "
    return (
        "FROM control.story_subcap_carry c "
        "JOIN control.story st ON st.story_key = c.story_key "
        "WHERE c.target_version = :ver AND c.carried_to_subcap = :sid "
        "AND c.status IN ('confirmed', 'review') AND c.carried_to_subcap IS NOT NULL " + syn
    )


class StoryPage(BaseModel):
    total: int
    page: int
    size: int
    items: list[StoryRow]


class Persona(BaseModel):
    persona_id: str
    canonical_name: str
    role_description: str | None = None


class Platform(BaseModel):
    l3_id: str
    name: str
    vendor: str | None = None
    category: str | None = None


class UseCase(BaseModel):
    use_case_id: str
    archetype: str | None = None
    name: str
    description: str | None = None


class Maturity(BaseModel):
    level: str
    descriptor: str | None = None
    features: str | None = None


class OfferingRef(BaseModel):
    offering_id: str
    name: str
    category: str | None = None


class SubcapEnrichment(BaseModel):
    personas: list[Persona]
    platforms: list[Platform]
    use_cases: list[UseCase]
    maturity: list[Maturity]
    offerings: list[OfferingRef]


class ConnectionSibling(BaseModel):
    id: str
    name: str
    pillar: str
    shared_platforms: int


class ConnectionSignal(BaseModel):
    """A recent gated news impact on this subcap — full trust envelope, chain backlink."""

    title: str
    source: str
    tier: str
    label: str
    ers: float
    mag: str
    score: float
    date: str
    chain: str | None = None


class SubcapConnections(BaseModel):
    siblings: list[ConnectionSibling]
    signals: list[ConnectionSignal]


class PlatformRow(BaseModel):
    l3_id: str
    name: str
    vendor: str | None = None
    category: str | None = None
    subcap_count: int
    p1: int
    p2: int
    p3: int
    p4: int
    stories: int


class PlatformSubcap(BaseModel):
    id: str
    pillar: str
    name: str


class PlatformDetail(BaseModel):
    l3_id: str
    name: str
    vendor: str | None = None
    category: str | None = None
    subcaps: list[PlatformSubcap]


class VendorRow(BaseModel):
    vendor: str
    plats: int
    subcap_count: int
    p1: int
    p2: int
    p3: int
    p4: int


class UseCaseRow(BaseModel):
    use_case_id: str
    archetype: str | None = None
    description: str | None = None
    subcap_id: str
    subcap_name: str
    pillar: str
    category: str


class ArchetypeFacet(BaseModel):
    archetype: str
    count: int


class UseCasePage(BaseModel):
    total: int
    page: int
    size: int
    items: list[UseCaseRow]
    archetypes: list[ArchetypeFacet]


class LifecycleSubcap(BaseModel):
    id: str
    name: str
    pillar: str
    stories: int
    offering_id: str | None = None
    offering_name: str | None = None


class LifecycleSummary(BaseModel):
    subcaps_delivered: int
    offerings: int
    covered_pct: int
    gaps: int
    top: list[LifecycleSubcap]


_JOINS = (
    "FROM {s}.subcap s "
    "JOIN {s}.capability cap ON cap.capability_id = s.capability_id "
    "JOIN {s}.category cat ON cat.category_id = cap.category_id"
)


@router.get("/{version}/subcaps")
async def list_subcaps(
    version: str, _user: dict[str, Any] = Depends(get_current_user)
) -> list[SubcapNode]:
    s = _schema(await resolve_version(version))
    sql = text(
        "SELECT s.subcap_id AS id, s.name, cat.pillar_id AS pillar, cat.category_id AS cat_id, "
        "cat.name AS cat_name, cap.name AS cluster, s.lifecycle_state AS life, false AS is_new "
        + _JOINS.format(s=s)
        + " ORDER BY s.subcap_id"
    )
    async with _engine().connect() as conn:
        rows = (await conn.execute(sql)).mappings().all()
    return [SubcapNode.model_validate(dict(r)) for r in rows]


@router.get("/{version}/subcaps/{subcap_id}")
async def get_subcap(
    version: str, subcap_id: str, _user: dict[str, Any] = Depends(get_current_user)
) -> SubcapDetail:
    v = await resolve_version(version)
    s = _schema(v)
    sql = text(
        "SELECT s.subcap_id AS id, s.name, cat.pillar_id AS pillar, cat.name AS category, "
        "cap.name AS cluster, s.description, s.solution_type, s.tier, s.lifecycle_state, "
        "s.completeness, "
        f"(SELECT count(*) FROM {s}.use_case uc WHERE uc.subcap_id = s.subcap_id) AS n_use_cases, "
        f"(SELECT count(*) FROM {s}.subcap_platform sp WHERE sp.subcap_id = s.subcap_id) "
        "AS n_platforms, "
        "(SELECT count(*) FROM control.story_catalogue_link scl "
        "WHERE scl.subcap_id = s.subcap_id AND scl.version_id = :ver) AS n_stories "
        + _JOINS.format(s=s)
        + " WHERE s.subcap_id = :sid"
    )
    async with _engine().connect() as conn:
        row = (await conn.execute(sql, {"sid": subcap_id, "ver": v.version_id})).mappings().first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"subcap '{subcap_id}' not found")
    return SubcapDetail.model_validate(dict(row))


@router.get("/{version}/subcaps/{subcap_id}/stories")
async def subcap_stories(
    version: str,
    subcap_id: str,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    include_synthetic: bool = Query(False),
    _user: dict[str, Any] = Depends(get_current_user),
) -> StoryPage:
    """Delivery stories carried onto this subcap (F5), highest composite first. Jira-only by
    default (analysis grade); ``include_synthetic`` adds the labelled synthetic stories."""
    v = await resolve_version(version)
    where = _carry_where(include_synthetic)
    rows_sql = text(
        "SELECT st.story_key, st.project_key, st.summary, st.confidence_level::text, "
        "st.composite_score::float AS composite_score, st.ac_score::float AS ac_score, "
        "st.sd_score::float AS sd_score, st.story_score::float AS story_score, "
        "st.story_sv_code, st.tier, st.is_synthetic "
        + where
        + " ORDER BY st.composite_score DESC NULLS LAST, st.story_key LIMIT :size OFFSET :off"
    )
    params = {"ver": v.version_id, "sid": subcap_id}
    async with _engine().connect() as conn:
        total = (await conn.execute(text("SELECT count(*) " + where), params)).scalar() or 0
        rows = (
            (await conn.execute(rows_sql, {**params, "size": size, "off": (page - 1) * size}))
            .mappings()
            .all()
        )
    items = [StoryRow.model_validate(dict(r)) for r in rows]
    return StoryPage(total=int(total), page=page, size=size, items=items)


class ClientAgg(BaseModel):
    """One Jira project (the corpus' client/engagement proxy) that delivered this subcap."""

    project_key: str
    stories: int
    share: float  # of this subcap's carried stories
    avg_composite: float | None = None
    subverticals: list[str]
    top: list[StoryRow]  # its strongest stories, for in-place drilldown


class StoryCluster(BaseModel):
    """Stories with similar characteristics, grouped deterministically (token overlap ≥ 0.5);
    `clients` = the related engagements that delivered into the same theme."""

    cluster_id: int
    label: str
    stories: int
    clients: list[str]
    avg_composite: float | None = None
    sample: list[StoryRow]


class DeliveryDrill(BaseModel):
    subcap_id: str
    name: str
    total_stories: int
    n_clients: int
    clients: list[ClientAgg]
    clusters: list[StoryCluster]
    unclustered: int
    clustered_over: int  # how many stories the clustering pass actually scanned (cap applies)


# Clustering scans at most this many stories per subcap (highest composite first) — bounded
# everything (§15); the cap is reported in the response so the analysis is honest about scope.
_CLUSTER_SCAN_CAP = 600


@router.get("/{version}/subcaps/{subcap_id}/delivery")
async def subcap_delivery(
    version: str,
    subcap_id: str,
    include_synthetic: bool = Query(False),
    _user: dict[str, Any] = Depends(get_current_user),
) -> DeliveryDrill:
    """Drilldown UNDER the story count: which clients (Jira projects) delivered this subcap, and
    which story themes cluster together across them. Jira-only by default (so the figures reconcile
    exactly with the heatmap and n_stories); ``include_synthetic`` folds in the labelled synthetic
    stories the deep-dive toggle reveals (those carry no real client → '(no project)')."""
    from app.services.story_insights import cluster_stories

    v = await resolve_version(version)
    s = _schema(v)
    link = _carry_where(include_synthetic)
    name_sql = text(f"SELECT name FROM {s}.subcap WHERE subcap_id = :sid")
    clients_sql = text(
        "SELECT coalesce(st.project_key, '(no project)') AS project_key, "
        "count(*) AS stories, avg(st.composite_score)::float AS avg_composite, "
        "array_remove(array_agg(DISTINCT st.story_sv_code), NULL) AS subverticals "
        + link
        + " GROUP BY coalesce(st.project_key, '(no project)') ORDER BY stories DESC, project_key"
    )
    top_sql = text(
        "SELECT story_key, project_key, summary, confidence_level, composite_score, ac_score, "
        "sd_score, story_score, story_sv_code, tier, is_synthetic FROM ("
        "SELECT st.story_key, st.project_key, st.summary, st.confidence_level::text, "
        "st.composite_score::float, st.ac_score::float, st.sd_score::float, "
        "st.story_score::float, st.story_sv_code, st.tier, st.is_synthetic, "
        "row_number() OVER (PARTITION BY coalesce(st.project_key, '(no project)') "
        "ORDER BY st.composite_score DESC NULLS LAST, st.story_key) AS rn " + link + ") t "
        "WHERE rn <= 3"
    )
    scan_sql = text(
        "SELECT st.story_key, st.project_key, st.summary, st.composite_score::float "
        + link
        + " ORDER BY st.composite_score DESC NULLS LAST, st.story_key LIMIT :cap"
    )
    params = {"ver": v.version_id, "sid": subcap_id}
    async with _engine().connect() as conn:
        name_row = (await conn.execute(name_sql, {"sid": subcap_id})).first()
        if name_row is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, detail="subcap not found in this version"
            )
        total = (await conn.execute(text("SELECT count(*) " + link), params)).scalar() or 0
        crows = (await conn.execute(clients_sql, params)).mappings().all()
        trows = (await conn.execute(top_sql, params)).mappings().all()
        scan = (await conn.execute(scan_sql, {**params, "cap": _CLUSTER_SCAN_CAP})).mappings().all()
    top_by_client: dict[str, list[StoryRow]] = {}
    for r in trows:
        key = str(r["project_key"] or "(no project)")
        top_by_client.setdefault(key, []).append(StoryRow.model_validate(dict(r)))
    clients = [
        ClientAgg(
            project_key=str(r["project_key"]),
            stories=int(r["stories"]),
            share=round(int(r["stories"]) / int(total), 3) if total else 0.0,
            avg_composite=round(r["avg_composite"], 2) if r["avg_composite"] is not None else None,
            subverticals=sorted(str(x) for x in (r["subverticals"] or [])),
            top=top_by_client.get(str(r["project_key"]), []),
        )
        for r in crows[:12]
    ]
    clustered = cluster_stories([dict(r) for r in scan])
    clusters = [
        StoryCluster(
            cluster_id=c["cluster_id"],
            label=c["label"],
            stories=c["stories"],
            clients=c["clients"],
            avg_composite=c["avg_composite"],
            sample=[
                StoryRow(
                    story_key=str(m["story_key"]),
                    project_key=m.get("project_key"),
                    summary=m.get("summary"),
                    composite_score=m.get("composite_score"),
                )
                for m in c["sample"]
            ],
        )
        for c in clustered["clusters"]
    ]
    return DeliveryDrill(
        subcap_id=subcap_id,
        name=str(name_row[0]),
        total_stories=int(total),
        n_clients=len(crows),
        clients=clients,
        clusters=clusters,
        unclustered=int(clustered["unclustered"]),
        clustered_over=len(scan),
    )


class TimelineEvent(BaseModel):
    kind: str  # news | vendor | suggestion | benchmark | trend
    date: str | None
    title: str
    claim: str | None = None
    tier: str | None = None
    mag: str | None = None
    excerpt: str | None = None
    chain: str | None = None


class TimelineResp(BaseModel):
    subcap_id: str
    name: str
    stories: int  # delivery lane: carried stories (no per-story dates in the corpus)
    sources: int  # distinct evidence sources across the dated lanes
    events: list[TimelineEvent]


# Project-subcap trace (C3): one subcap, every cross-signal event on a single timeline. A union of
# the existing impact tables — each row already carries claim/tier/mag/chain, so the trust envelope
# travels with every event. Stories carry no real delivery dates (ingest-time only) so delivery is a
# summary count lane, not dated events.
_TIMELINE_SQL = {
    "news": (
        "SELECT 'news' AS kind, ei.published_at::text AS date, ni.headline AS title, "
        "rc.claim_label::text AS claim, ei.source_tier::text AS tier, i.mag::text AS mag, "
        "ei.source_name AS excerpt, i.chain_id::text AS chain "
        "FROM control.news_subcap_impact i "
        "JOIN control.news_item ni ON ni.news_id = i.news_id "
        "JOIN control.evidence_item ei ON ei.evidence_id = ni.evidence_id "
        "LEFT JOIN control.reasoning_chain rc ON rc.chain_id = i.chain_id "
        "WHERE i.version_id = :ver AND i.subcap_id = :sid"
    ),
    "vendor": (
        "SELECT 'vendor' AS kind, ve.occurred_at::text AS date, ve.headline AS title, "
        "rc.claim_label::text AS claim, ei.source_tier::text AS tier, i.mag::text AS mag, "
        "ve.event_type::text AS excerpt, i.chain_id::text AS chain "
        "FROM control.vendor_subcap_impact i "
        "JOIN control.vendor_event ve ON ve.event_id = i.event_id "
        "LEFT JOIN control.evidence_item ei ON ei.evidence_id = ve.evidence_id "
        "LEFT JOIN control.reasoning_chain rc ON rc.chain_id = i.chain_id "
        "WHERE i.version_id = :ver AND i.subcap_id = :sid"
    ),
    "suggestion": (
        "SELECT 'suggestion' AS kind, s.created_at::text AS date, "
        "(s.kind::text || ' · ' || coalesce(s.status::text,'')) AS title, "
        "s.claim_label::text AS claim, s.source_tier::text AS tier, NULL AS mag, "
        "s.reason AS excerpt, s.chain_id::text AS chain "
        "FROM control.suggestion s "
        "WHERE s.target_version = :ver AND s.target_subcap = :sid"
    ),
    "benchmark": (
        "SELECT 'benchmark' AS kind, b.created_at::text AS date, "
        "(b.metric || ' (' || b.verdict || ')') AS title, NULL AS claim, "
        "ei.source_tier::text AS tier, NULL AS mag, b.verdict_note AS excerpt, "
        "b.chain_id::text AS chain "
        "FROM control.benchmark b "
        "LEFT JOIN control.evidence_item ei ON ei.evidence_id = b.evidence_id "
        "WHERE b.version_id = :ver AND b.subcap_id = :sid"
    ),
    "trend": (
        "SELECT 'trend' AS kind, t.window_end::text AS date, t.label AS title, "
        "t.claim_label::text AS claim, t.source_tier::text AS tier, NULL AS mag, "
        "(ts.emergent::text) AS excerpt, t.chain_id::text AS chain "
        "FROM control.trend_subcap ts JOIN control.trend t ON t.trend_id = ts.trend_id "
        "WHERE ts.version_id = :ver AND ts.subcap_id = :sid"
    ),
    "sow": (
        "SELECT 'sow' AS kind, d.signed_date::text AS date, "
        "(d.account_key || ' · ' || d.title) AS title, "
        "m.claim_label::text AS claim, m.source_tier::text AS tier, NULL AS mag, "
        "si.clause AS excerpt, m.chain_id::text AS chain "
        "FROM control.sow_subcap_match m "
        "JOIN control.sow_scope_item si ON si.scope_id = m.scope_id "
        "JOIN control.sow_document d ON d.sow_id = si.sow_id "
        "WHERE m.version_id = :ver AND m.subcap_id = :sid "
        "AND m.status IN ('confirmed', 'review')"
    ),
}


@router.get("/{version}/subcaps/{subcap_id}/timeline")
async def subcap_timeline(
    version: str, subcap_id: str, _user: dict[str, Any] = Depends(get_current_user)
) -> TimelineResp:
    v = await resolve_version(version)
    s = _schema(v)
    params = {"ver": v.version_id, "sid": subcap_id}
    async with _engine().connect() as conn:
        name_row = (
            await conn.execute(
                text(f"SELECT name FROM {s}.subcap WHERE subcap_id = :sid"), {"sid": subcap_id}
            )
        ).first()
        if name_row is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, detail="subcap not found in this version"
            )
        events: list[TimelineEvent] = []
        for sql in _TIMELINE_SQL.values():
            rows = (await conn.execute(text(sql), params)).mappings().all()
            events.extend(TimelineEvent.model_validate(dict(r)) for r in rows)
        stories = (
            await conn.execute(
                text(
                    "SELECT count(*) FROM control.story_catalogue_link "
                    "WHERE version_id = :ver AND subcap_id = :sid"
                ),
                params,
            )
        ).scalar() or 0
    events.sort(key=lambda e: e.date or "", reverse=True)
    sources = len({e.excerpt for e in events if e.kind in ("news", "vendor") and e.excerpt})
    return TimelineResp(
        subcap_id=subcap_id,
        name=str(name_row[0]),
        stories=int(stories),
        sources=sources,
        events=events,
    )


@router.get("/{version}/subcaps/{subcap_id}/enrichment")
async def subcap_enrichment(
    version: str, subcap_id: str, _user: dict[str, Any] = Depends(get_current_user)
) -> SubcapEnrichment:
    """Personas, L3 platforms, use cases and M1-M5 maturity for a subcap (Overview/Use/Maturity)."""
    s = _schema(await resolve_version(version))
    q_personas = text(
        f"SELECT p.persona_id, p.canonical_name, p.role_description FROM {s}.subcap_persona sp "
        f"JOIN {s}.persona p ON p.persona_id = sp.persona_id WHERE sp.subcap_id = :sid "
        "ORDER BY p.canonical_name"
    )
    q_platforms = text(
        f"SELECT l.l3_id, l.name, v.name AS vendor, l.category FROM {s}.subcap_platform sp "
        f"JOIN {s}.l3_platform l ON l.l3_id = sp.l3_id "
        f"LEFT JOIN {s}.vendor v ON v.vendor_id = l.vendor_id WHERE sp.subcap_id = :sid "
        "ORDER BY l.name"
    )
    q_uc = text(
        f"SELECT use_case_id, archetype, name, description FROM {s}.use_case "
        "WHERE subcap_id = :sid ORDER BY use_case_id"
    )
    q_mat = text(
        f"SELECT level, descriptor, features FROM {s}.maturity_descriptor "
        "WHERE subcap_id = :sid ORDER BY level"
    )
    q_off = text(
        f"SELECT o.offering_id, o.name, o.category FROM {s}.offering_subcap os "
        f"JOIN {s}.offering o ON o.offering_id = os.offering_id WHERE os.subcap_id = :sid "
        "ORDER BY o.name"
    )
    p = {"sid": subcap_id}
    async with _engine().connect() as conn:
        personas = (await conn.execute(q_personas, p)).mappings().all()
        platforms = (await conn.execute(q_platforms, p)).mappings().all()
        use_cases = (await conn.execute(q_uc, p)).mappings().all()
        maturity = (await conn.execute(q_mat, p)).mappings().all()
        offerings = (await conn.execute(q_off, p)).mappings().all()
    return SubcapEnrichment(
        personas=[Persona.model_validate(dict(r)) for r in personas],
        platforms=[Platform.model_validate(dict(r)) for r in platforms],
        use_cases=[UseCase.model_validate(dict(r)) for r in use_cases],
        maturity=[Maturity.model_validate(dict(r)) for r in maturity],
        offerings=[OfferingRef.model_validate(dict(r)) for r in offerings],
    )


@router.get("/{version}/subcaps/{subcap_id}/connections")
async def subcap_connections(
    version: str, subcap_id: str, _user: dict[str, Any] = Depends(get_current_user)
) -> SubcapConnections:
    """KG Layer-A siblings (same capability, ranked by shared L3 platforms) + recent gated
    news signals on this subcap (each with its trust envelope + reasoning backlink)."""
    v = await resolve_version(version)
    s = _schema(v)
    sql = text(
        "SELECT s2.subcap_id AS id, s2.name, left(s2.subcap_id, 2) AS pillar, "
        f"(SELECT count(DISTINCT sp2.l3_id) FROM {s}.subcap_platform sp2 "
        f"WHERE sp2.subcap_id = s2.subcap_id AND sp2.l3_id IN "
        f"(SELECT l3_id FROM {s}.subcap_platform WHERE subcap_id = :sid)) AS shared_platforms "
        f"FROM {s}.subcap s2 "
        f"WHERE s2.capability_id = (SELECT capability_id FROM {s}.subcap WHERE subcap_id = :sid) "
        "AND s2.subcap_id <> :sid ORDER BY shared_platforms DESC, s2.subcap_id LIMIT 8"
    )
    sig_sql = text(
        "SELECT e.title, e.source_name AS source, e.source_tier::text AS tier, "
        "coalesce(rc.claim_label::text, 'INFERENCE') AS label, "
        "coalesce((SELECT er.score::float FROM control.ers er "
        "WHERE er.evidence_id = e.evidence_id "
        "ORDER BY er.computed_at DESC LIMIT 1), 0) AS ers, "
        "i.mag::text AS mag, i.score::float AS score, "
        "to_char(e.published_at, 'YYYY-MM-DD') AS date, i.chain_id::text AS chain "
        "FROM control.news_subcap_impact i "
        "JOIN control.news_item n ON n.news_id = i.news_id "
        "JOIN control.evidence_item e ON e.evidence_id = n.evidence_id "
        "LEFT JOIN control.reasoning_chain rc ON rc.chain_id = i.chain_id "
        "WHERE i.version_id = :ver AND i.subcap_id = :sid "
        "ORDER BY e.published_at DESC NULLS LAST LIMIT 6"
    )
    async with _engine().connect() as conn:
        rows = (await conn.execute(sql, {"sid": subcap_id})).mappings().all()
        sigs = (
            (await conn.execute(sig_sql, {"ver": v.version_id, "sid": subcap_id})).mappings().all()
        )
    return SubcapConnections(
        siblings=[ConnectionSibling.model_validate(dict(r)) for r in rows],
        signals=[ConnectionSignal.model_validate(dict(r)) for r in sigs],
    )


class KgNode(BaseModel):
    id: str
    kind: str  # subcap | platform | offering
    label: str
    pillar: str | None = None


class KgEdge(BaseModel):
    source: str
    target: str
    kind: str  # uses_platform | maps_to_offering | shares_platform
    layer: str  # A_deterministic | B_proposed


class KgResp(BaseModel):
    center: str
    name: str
    nodes: list[KgNode]
    edges: list[KgEdge]
    stats: dict[str, int]
    pending: list[KgEdge]  # Layer B — AI-proposed, gated in Change Flags (dashed, never fact)


@router.get("/{version}/kg")
async def knowledge_graph(
    version: str, subcap: str, _user: dict[str, Any] = Depends(get_current_user)
) -> KgResp:
    """Knowledge graph neighbourhood for a subcap. Layer A (solid) is a DETERMINISTIC projection of
    the catalogue's own link tables — platforms it uses, offerings it maps to, and sibling subcaps
    that share a platform — so every edge traces to a real row (F15, §19 schema-explicit). Layer B
    (dashed) are AI-proposed `pending_edge`s, never rendered as fact and gated in Change Flags."""
    v = await resolve_version(version)
    s = _schema(v)
    params = {"sid": subcap, "ver": v.version_id}
    async with _engine().connect() as conn:
        name = (
            await conn.execute(
                text(f"SELECT name FROM {s}.subcap WHERE subcap_id = :sid"), {"sid": subcap}
            )
        ).first()
        if name is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, detail="subcap not found in this version"
            )
        plats = (
            (
                await conn.execute(
                    text(
                        f"SELECT l.l3_id AS id, l.name FROM {s}.subcap_platform sp "
                        f"JOIN {s}.l3_platform l ON l.l3_id = sp.l3_id "
                        "WHERE sp.subcap_id = :sid ORDER BY l.name LIMIT 10"
                    ),
                    {"sid": subcap},
                )
            )
            .mappings()
            .all()
        )
        offs = (
            (
                await conn.execute(
                    text(
                        f"SELECT o.offering_id AS id, o.name FROM {s}.offering_subcap os "
                        f"JOIN {s}.offering o ON o.offering_id = os.offering_id "
                        "WHERE os.subcap_id = :sid ORDER BY o.name LIMIT 8"
                    ),
                    {"sid": subcap},
                )
            )
            .mappings()
            .all()
        )
        sibs = (
            (
                await conn.execute(
                    text(
                        f"SELECT sp2.subcap_id AS id, sc.name, left(sp2.subcap_id, 2) AS pillar, "
                        "count(*) AS shared "
                        f"FROM {s}.subcap_platform sp1 "
                        f"JOIN {s}.subcap_platform sp2 ON sp2.l3_id = sp1.l3_id "
                        f"JOIN {s}.subcap sc ON sc.subcap_id = sp2.subcap_id "
                        "WHERE sp1.subcap_id = :sid AND sp2.subcap_id <> :sid "
                        "GROUP BY sp2.subcap_id, sc.name ORDER BY shared DESC LIMIT 6"
                    ),
                    {"sid": subcap},
                )
            )
            .mappings()
            .all()
        )
        pend = (
            (
                await conn.execute(
                    text(
                        "SELECT from_node::text AS source, to_node::text AS target, "
                        "kind::text AS kind "
                        "FROM control.pending_edge WHERE version_id = :ver "
                        "AND (from_node::text = :sid OR to_node::text = :sid) "
                        "AND status = 'pending' LIMIT 10"
                    ),
                    params,
                )
            )
            .mappings()
            .all()
        )
    nodes: list[KgNode] = [KgNode(id=subcap, kind="subcap", label=str(name[0]), pillar=subcap[:2])]
    edges: list[KgEdge] = []
    for p in plats:
        nodes.append(KgNode(id=p["id"], kind="platform", label=p["name"]))
        edges.append(
            KgEdge(source=subcap, target=p["id"], kind="uses_platform", layer="A_deterministic")
        )
    for o in offs:
        nodes.append(KgNode(id=o["id"], kind="offering", label=o["name"]))
        edges.append(
            KgEdge(source=subcap, target=o["id"], kind="maps_to_offering", layer="A_deterministic")
        )
    for sb in sibs:
        nodes.append(KgNode(id=sb["id"], kind="subcap", label=sb["name"], pillar=sb["pillar"]))
        edges.append(
            KgEdge(source=subcap, target=sb["id"], kind="shares_platform", layer="A_deterministic")
        )
    pending = [
        KgEdge(source=p["source"], target=p["target"], kind=p["kind"], layer="B_proposed")
        for p in pend
    ]
    stats = {
        "platforms": len(plats),
        "offerings": len(offs),
        "siblings": len(sibs),
        "pending": len(pending),
    }
    return KgResp(
        center=subcap, name=str(name[0]), nodes=nodes, edges=edges, stats=stats, pending=pending
    )


class WhatIfRef(BaseModel):
    id: str
    name: str


class WhatIfResp(BaseModel):
    subcap: str
    name: str
    action: str
    stories: int  # delivery affected
    use_cases: int
    offerings: list[WhatIfRef]  # offerings that lose/change coverage
    platforms: list[WhatIfRef]
    siblings: list[WhatIfRef]  # subcaps sharing a platform — potential KG ripples
    blast: int  # total distinct catalogue rows in the blast radius
    summary: str
    reversible: bool = True


@router.get("/{version}/whatif")
async def whatif(
    version: str,
    subcap: str,
    action: str = "toggle",
    _user: dict[str, Any] = Depends(get_current_user),
) -> WhatIfResp:
    """Read-only cascade preview (I1): the deterministic structural blast radius of a change to a
    subcap — the offerings, delivery stories, platforms, use cases and shared-platform siblings it
    touches — computed from the catalogue's link tables. Nothing is written; promote stages a gated
    suggestion. (relation_def cascade rows would extend this; none are defined yet.)"""
    v = await resolve_version(version)
    s = _schema(v)
    p = {"sid": subcap, "ver": v.version_id}
    async with _engine().connect() as conn:
        name = (
            await conn.execute(
                text(f"SELECT name FROM {s}.subcap WHERE subcap_id = :sid"), {"sid": subcap}
            )
        ).first()
        if name is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, detail="subcap not found in this version"
            )
        offs = (
            (
                await conn.execute(
                    text(
                        f"SELECT o.offering_id AS id, o.name FROM {s}.offering_subcap os "
                        f"JOIN {s}.offering o ON o.offering_id = os.offering_id "
                        "WHERE os.subcap_id = :sid ORDER BY o.name"
                    ),
                    {"sid": subcap},
                )
            )
            .mappings()
            .all()
        )
        plats = (
            (
                await conn.execute(
                    text(
                        f"SELECT l.l3_id AS id, l.name FROM {s}.subcap_platform sp "
                        f"JOIN {s}.l3_platform l ON l.l3_id = sp.l3_id "
                        "WHERE sp.subcap_id = :sid ORDER BY l.name"
                    ),
                    {"sid": subcap},
                )
            )
            .mappings()
            .all()
        )
        sibs = (
            (
                await conn.execute(
                    text(
                        f"SELECT DISTINCT sp2.subcap_id AS id, sc.name "
                        f"FROM {s}.subcap_platform sp1 "
                        f"JOIN {s}.subcap_platform sp2 ON sp2.l3_id = sp1.l3_id "
                        f"JOIN {s}.subcap sc ON sc.subcap_id = sp2.subcap_id "
                        "WHERE sp1.subcap_id = :sid AND sp2.subcap_id <> :sid "
                        "ORDER BY sc.name LIMIT 12"
                    ),
                    {"sid": subcap},
                )
            )
            .mappings()
            .all()
        )
        stories = (
            await conn.execute(
                text(
                    "SELECT count(*) FROM control.story_catalogue_link "
                    "WHERE version_id = :ver AND subcap_id = :sid"
                ),
                p,
            )
        ).scalar() or 0
        use_cases = (
            await conn.execute(
                text(f"SELECT count(*) FROM {s}.use_case WHERE subcap_id = :sid"), {"sid": subcap}
            )
        ).scalar() or 0
    blast = len(offs) + len(plats) + len(sibs) + int(stories) + int(use_cases)
    verb = {
        "retire": "Retiring",
        "descriptor": "Editing the maturity descriptor of",
        "platform": "Remapping the platforms of",
        "merge": "Merging",
        "offering": "Re-bundling",
        "relation": "Adding a relation to",
        "toggle": "Toggling",
    }.get(action, "Changing")
    summary = (
        f"{verb} {name[0]} touches {blast} catalogue rows: {len(offs)} offering(s), "
        f"{int(stories):,} delivered stories, {len(plats)} platform link(s), {int(use_cases)} use "
        f"case(s) and {len(sibs)} shared-platform sibling(s). Read-only — promote to stage a "
        f"gated change."
    )
    return WhatIfResp(
        subcap=subcap,
        name=str(name[0]),
        action=action,
        stories=int(stories),
        use_cases=int(use_cases),
        offerings=[WhatIfRef(id=o["id"], name=o["name"]) for o in offs],
        platforms=[WhatIfRef(id=pl["id"], name=pl["name"]) for pl in plats],
        siblings=[WhatIfRef(id=sb["id"], name=sb["name"]) for sb in sibs],
        blast=blast,
        summary=summary,
    )


@router.get("/{version}/value-chain")
async def value_chain(
    version: str,
    pillar: str = "",
    sv: str = "",
    _user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """The value-chain atlas, DERIVED LIVE from the version's own capability clusters (A3) —
    dynamic, deduped, and smart-clustered (services/value_chain). Works for v5 and v7 alike from
    each one's data. ``pillar`` filters; ``sv`` is accepted for the UI lens but the segments are
    catalogue-wide."""
    from app.services.value_chain import derive_value_chain

    s = _schema(await resolve_version(version))
    where = " WHERE cat.pillar_id = :p" if pillar and pillar != "all" else ""
    # Segment at the CATEGORY grain (the natural value-chain stage, ~16) — capabilities (135) are
    # too granular to be a chain. The smart dedupe/cluster then merges near-duplicate categories.
    sql = text(
        "SELECT s.subcap_id, s.name, cat.pillar_id AS pillar, cat.name AS cluster, "
        "cap.name AS category " + _JOINS.format(s=s) + where + " ORDER BY s.subcap_id"
    )
    async with _engine().connect() as conn:
        rows = (await conn.execute(sql, {"p": pillar})).mappings().all()
    out = derive_value_chain([dict(r) for r in rows])
    out["version"] = version
    out["sv"] = sv or "all"
    return out


@router.get("/{version}/summary")
async def summary(
    version: str, _user: dict[str, Any] = Depends(get_current_user)
) -> CatalogueSummary:
    v = await resolve_version(version)
    s = _schema(v)
    # completeness = DATA completeness of the load (filled key fields, computed at provision).
    # decay = subcaps with NO delivered JIRA story (story_catalogue_link is Jira-only by
    # construction — synthetic stories never count). A decayed subcap can still be active; the
    # decay scan flags it for an admin decision, it is never auto-deactivated.
    sql = text(
        "SELECT p.pillar_id, p.name, count(s.subcap_id) AS subcap_count, "
        "coalesce(avg(s.completeness), 0)::float AS completeness, "
        "count(s.subcap_id) FILTER (WHERE NOT EXISTS ("
        "  SELECT 1 FROM control.story_catalogue_link l "
        "  WHERE l.version_id = :vid AND l.subcap_id = s.subcap_id)) AS decay "
        f"FROM {s}.pillar p "
        f"LEFT JOIN {s}.category cat ON cat.pillar_id = p.pillar_id "
        f"LEFT JOIN {s}.capability cap ON cap.category_id = cat.category_id "
        f"LEFT JOIN {s}.subcap s ON s.capability_id = cap.capability_id "
        "GROUP BY p.pillar_id, p.name ORDER BY p.pillar_id"
    )
    async with _engine().connect() as conn:
        rows = (await conn.execute(sql, {"vid": v.version_id})).mappings().all()
        total = (await conn.execute(text(f"SELECT count(*) FROM {s}.subcap"))).scalar()
    pillars = [PillarSummary.model_validate(dict(r)) for r in rows]
    return CatalogueSummary(version_id=v.version_id, total_subcaps=int(total or 0), pillars=pillars)


class HeatmapRow(BaseModel):
    key: str
    label: str
    subtitle: str
    total: int
    cells: list[int]
    pillar: str | None = None


class HeatmapResp(BaseModel):
    lens: str
    axis: list[str]  # the 6 composite-score band labels
    rows: list[HeatmapRow]
    max: int  # global max cell, for intensity scaling


# Mission control's concentration heatmap (Impl §604). Real delivery volume from the carried story
# corpus (control.story_catalogue_link → control.story), grouped by the active LENS, with the cell
# strip bucketing each group's stories across 6 composite-score bands (1.0–5.0). The catalogue lost
# real Jira dates on ingest (created_at = ingest time), so the truthful ordinal axis is delivery
# quality, not quarters — same heatmap shape, honest data.
_LENS_GROUP: dict[str, tuple[str, str, str]] = {
    # lens -> (group-key expr, label expr, extra FROM/JOIN)
    "pillar": ("sc.subcap_id", "sc.name", ""),  # rows = most-delivered subcaps
    "lifecycle": ("sc.lifecycle_state::text", "sc.lifecycle_state::text", ""),
    "maturity": ("coalesce(sc.tier,'untiered')", "coalesce(sc.tier,'untiered')", ""),
    "subvertical": (
        "coalesce(st.story_sv_code,'(unscoped)')",
        "coalesce(st.story_sv_code,'(unscoped)')",
        "",
    ),
    "vendor": (
        "ven.name",
        "ven.name",
        " JOIN {s}.subcap_platform sp ON sp.subcap_id = sc.subcap_id"
        " JOIN {s}.l3_platform l3 ON l3.l3_id = sp.l3_id"
        " JOIN {s}.vendor ven ON ven.vendor_id = l3.vendor_id",
    ),
    "value-chain": (
        "vcc.vcc_id",
        "vcc.vcc_id",
        " JOIN {s}.subcap_vcc vcc ON vcc.subcap_id = sc.subcap_id",
    ),
}
_BAND_AXIS = ["1.0–1.7", "1.7–2.3", "2.3–3.0", "3.0–3.7", "3.7–4.3", "4.3–5.0"]


@router.get("/{version}/heatmap")
async def heatmap(
    version: str,
    lens: str = Query("pillar"),
    pillar: str = Query("all"),
    sv: str = Query("all"),
    limit: int = Query(14, ge=1, le=40),
    _user: dict[str, Any] = Depends(get_current_user),
) -> HeatmapResp:
    """Delivery-concentration heatmap for Mission control, grouped by `lens`, scoped by the active
    pillar/subvertical filters. Counts dedupe per story so a vendor with many platforms isn't
    double-counted."""
    v = await resolve_version(version)
    s = _schema(v)
    if lens not in _LENS_GROUP:
        lens = "pillar"
    key_expr, label_expr, join_tmpl = _LENS_GROUP[lens]
    join = join_tmpl.format(s=s)
    where = ["l.version_id = :ver"]
    params: dict[str, Any] = {"ver": v.version_id, "lim": limit}
    if pillar != "all":
        where.append("left(sc.subcap_id, 2) = :pil")
        params["pil"] = pillar
    if sv != "all":
        where.append("st.story_sv_code = :sv")
        params["sv"] = sv
    band = "least(6, greatest(1, width_bucket(st.composite_score, 1, 5, 6)))"
    cells = ", ".join(
        f"count(DISTINCT st.story_key) FILTER (WHERE {band} = {k}) AS c{k}" for k in range(1, 7)
    )
    # Only the pillar lens (rows = individual subcaps) carries a pillar colour; for the other
    # lenses a group spans pillars, so pillar is NULL and is not a grouping key.
    pillar_sel = "left(sc.subcap_id, 2)" if lens == "pillar" else "NULL"
    group_by = "key, label, pillar" if lens == "pillar" else "key, label"
    sql = text(
        f"SELECT {key_expr} AS key, {label_expr} AS label, "
        f"{pillar_sel} AS pillar, count(DISTINCT st.story_key) AS total, {cells} "
        f"FROM control.story_catalogue_link l "
        f"JOIN control.story st ON st.story_key = l.story_key "
        f"JOIN {s}.subcap sc ON sc.subcap_id = l.subcap_id{join} "
        f"WHERE {' AND '.join(where)} "
        f"GROUP BY {group_by} ORDER BY total DESC LIMIT :lim"
    )
    async with _engine().connect() as conn:
        rows = (await conn.execute(sql, params)).mappings().all()
    out: list[HeatmapRow] = []
    gmax = 0
    for r in rows:
        cs = [int(r[f"c{k}"]) for k in range(1, 7)]
        gmax = max(gmax, *cs)
        sub = f"{int(r['total']):,} stories" if lens != "pillar" else r["key"]
        out.append(
            HeatmapRow(
                key=str(r["key"]),
                label=str(r["label"]),
                subtitle=sub,
                total=int(r["total"]),
                cells=cs,
                pillar=r["pillar"] if lens == "pillar" else None,
            )
        )
    return HeatmapResp(lens=lens, axis=_BAND_AXIS, rows=out, max=gmax)


_PLATFORMS_SQL = (
    "SELECT l.l3_id, l.name, v.name AS vendor, l.category, "
    "count(DISTINCT sp.subcap_id) AS subcap_count, "
    "count(DISTINCT sp.subcap_id) FILTER (WHERE left(sp.subcap_id, 2) = 'P1') AS p1, "
    "count(DISTINCT sp.subcap_id) FILTER (WHERE left(sp.subcap_id, 2) = 'P2') AS p2, "
    "count(DISTINCT sp.subcap_id) FILTER (WHERE left(sp.subcap_id, 2) = 'P3') AS p3, "
    "count(DISTINCT sp.subcap_id) FILTER (WHERE left(sp.subcap_id, 2) = 'P4') AS p4, "
    "coalesce(sum(stc.n), 0)::int AS stories "
    "FROM {s}.l3_platform l "
    "LEFT JOIN {s}.vendor v ON v.vendor_id = l.vendor_id "
    "LEFT JOIN {s}.subcap_platform sp ON sp.l3_id = l.l3_id "
    "LEFT JOIN (SELECT subcap_id, count(*) n FROM control.story_catalogue_link "
    "WHERE version_id = :ver GROUP BY subcap_id) stc ON stc.subcap_id = sp.subcap_id "
    "GROUP BY l.l3_id, l.name, v.name, l.category "
    "ORDER BY subcap_count DESC, l.l3_id"
)


@router.get("/{version}/platforms")
async def list_platforms(
    version: str, _user: dict[str, Any] = Depends(get_current_user)
) -> list[PlatformRow]:
    """L3 platforms with per-pillar subcap coverage + total stories (Platform catalog)."""
    v = await resolve_version(version)
    sql = text(_PLATFORMS_SQL.format(s=_schema(v)))
    async with _engine().connect() as conn:
        rows = (await conn.execute(sql, {"ver": v.version_id})).mappings().all()
    return [PlatformRow.model_validate(dict(r)) for r in rows]


@router.get("/{version}/platforms/{l3_id}")
async def platform_detail(
    version: str, l3_id: str, _user: dict[str, Any] = Depends(get_current_user)
) -> PlatformDetail:
    s = _schema(await resolve_version(version))
    meta_sql = text(
        f"SELECT l.l3_id, l.name, v.name AS vendor, l.category FROM {s}.l3_platform l "
        f"LEFT JOIN {s}.vendor v ON v.vendor_id = l.vendor_id WHERE l.l3_id = :lid"
    )
    subs_sql = text(
        f"SELECT sp.subcap_id AS id, left(sp.subcap_id, 2) AS pillar, s.name "
        f"FROM {s}.subcap_platform sp JOIN {s}.subcap s ON s.subcap_id = sp.subcap_id "
        "WHERE sp.l3_id = :lid ORDER BY sp.subcap_id"
    )
    async with _engine().connect() as conn:
        meta = (await conn.execute(meta_sql, {"lid": l3_id})).mappings().first()
        if meta is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"platform '{l3_id}' not found")
        subs = (await conn.execute(subs_sql, {"lid": l3_id})).mappings().all()
    return PlatformDetail(
        **dict(meta), subcaps=[PlatformSubcap.model_validate(dict(r)) for r in subs]
    )


@router.get("/{version}/vendors")
async def list_vendors(
    version: str, _user: dict[str, Any] = Depends(get_current_user)
) -> list[VendorRow]:
    """Per-vendor deduped subcap coverage by pillar (the Platform catalog heatmap)."""
    s = _schema(await resolve_version(version))
    sql = text(
        "SELECT coalesce(v.name, 'Unattributed') AS vendor, count(DISTINCT l.l3_id) AS plats, "
        "count(DISTINCT sp.subcap_id) AS subcap_count, "
        "count(DISTINCT sp.subcap_id) FILTER (WHERE left(sp.subcap_id, 2) = 'P1') AS p1, "
        "count(DISTINCT sp.subcap_id) FILTER (WHERE left(sp.subcap_id, 2) = 'P2') AS p2, "
        "count(DISTINCT sp.subcap_id) FILTER (WHERE left(sp.subcap_id, 2) = 'P3') AS p3, "
        "count(DISTINCT sp.subcap_id) FILTER (WHERE left(sp.subcap_id, 2) = 'P4') AS p4 "
        f"FROM {s}.l3_platform l LEFT JOIN {s}.vendor v ON v.vendor_id = l.vendor_id "
        f"LEFT JOIN {s}.subcap_platform sp ON sp.l3_id = l.l3_id "
        "GROUP BY coalesce(v.name, 'Unattributed') ORDER BY subcap_count DESC, vendor"
    )
    async with _engine().connect() as conn:
        rows = (await conn.execute(sql)).mappings().all()
    return [VendorRow.model_validate(dict(r)) for r in rows]


@router.get("/{version}/use-cases")
async def list_use_cases(
    version: str,
    pillar: str = Query(""),
    category: str = Query(""),
    archetype: str = Query(""),
    q: str = Query(""),
    page: int = Query(1, ge=1),
    size: int = Query(12, ge=1, le=60),
    _user: dict[str, Any] = Depends(get_current_user),
) -> UseCasePage:
    """Actual use cases, filterable by pillar / area / type / text (Use case explorer)."""
    s = _schema(await resolve_version(version))
    joins = (
        f"FROM {s}.use_case uc "
        f"JOIN {s}.subcap sc ON sc.subcap_id = uc.subcap_id "
        f"JOIN {s}.capability cap ON cap.capability_id = sc.capability_id "
        f"JOIN {s}.category cat ON cat.category_id = cap.category_id"
    )
    where = (
        " WHERE (:pillar = '' OR left(uc.subcap_id, 2) = :pillar) "
        "AND (:category = '' OR cat.category_id = :category) "
        "AND (:archetype = '' OR uc.archetype = :archetype) "
        "AND (:q = '' OR uc.description ILIKE :qlike OR sc.name ILIKE :qlike)"
    )
    facet_where = (
        " WHERE (:pillar = '' OR left(uc.subcap_id, 2) = :pillar) "
        "AND (:category = '' OR cat.category_id = :category) AND uc.archetype IS NOT NULL"
    )
    params = {
        "pillar": pillar,
        "category": category,
        "archetype": archetype,
        "q": q,
        "qlike": f"%{q}%",
    }
    items_sql = text(
        "SELECT uc.use_case_id, uc.archetype, uc.description, uc.subcap_id, "
        "sc.name AS subcap_name, left(uc.subcap_id, 2) AS pillar, cat.name AS category "
        + joins
        + where
        + " ORDER BY uc.use_case_id LIMIT :size OFFSET :off"
    )
    count_sql = text("SELECT count(*) " + joins + where)
    facet_sql = text(
        "SELECT uc.archetype, count(*) AS count "
        + joins
        + facet_where
        + " GROUP BY uc.archetype ORDER BY count DESC, uc.archetype"
    )
    async with _engine().connect() as conn:
        total = (await conn.execute(count_sql, params)).scalar() or 0
        off = (page - 1) * size
        rows = (
            (await conn.execute(items_sql, {**params, "size": size, "off": off})).mappings().all()
        )
        facets = (await conn.execute(facet_sql, params)).mappings().all()
    return UseCasePage(
        total=int(total),
        page=page,
        size=size,
        items=[UseCaseRow.model_validate(dict(r)) for r in rows],
        archetypes=[ArchetypeFacet.model_validate(dict(r)) for r in facets],
    )


@router.get("/{version}/lifecycle")
async def lifecycle(
    version: str, _user: dict[str, Any] = Depends(get_current_user)
) -> LifecycleSummary:
    """Most-delivered subcaps mapped to productized offerings + coverage KPIs (Lifecycle)."""
    v = await resolve_version(version)
    s = _schema(v)
    off_join = (
        "(SELECT os.subcap_id, min(o.offering_id) AS offering_id, min(o.name) AS offering_name "
        f"FROM {s}.offering_subcap os JOIN {s}.offering o ON o.offering_id = os.offering_id "
        "GROUP BY os.subcap_id) off"
    )
    delivered_cte = (
        "(SELECT subcap_id, count(*) AS stories FROM control.story_catalogue_link "
        "WHERE version_id = :ver GROUP BY subcap_id) sc"
    )
    top_sql = text(
        "SELECT sc.subcap_id AS id, s.name, left(sc.subcap_id, 2) AS pillar, "
        "sc.stories::int AS stories, off.offering_id, off.offering_name "
        f"FROM {delivered_cte} JOIN {s}.subcap s ON s.subcap_id = sc.subcap_id "
        f"LEFT JOIN {off_join} ON off.subcap_id = sc.subcap_id "
        "ORDER BY sc.stories DESC, sc.subcap_id LIMIT 8"
    )
    kpi_sql = text(
        "SELECT count(*) AS delivered, "
        "count(*) FILTER (WHERE off.offering_id IS NOT NULL) AS covered "
        f"FROM {delivered_cte} LEFT JOIN {off_join} ON off.subcap_id = sc.subcap_id"
    )
    async with _engine().connect() as conn:
        offerings = (await conn.execute(text(f"SELECT count(*) FROM {s}.offering"))).scalar() or 0
        kpi = (await conn.execute(kpi_sql, {"ver": v.version_id})).mappings().first()
        rows = (await conn.execute(top_sql, {"ver": v.version_id})).mappings().all()
    delivered = int(kpi["delivered"]) if kpi else 0
    covered = int(kpi["covered"]) if kpi else 0
    return LifecycleSummary(
        subcaps_delivered=delivered,
        offerings=int(offerings),
        covered_pct=round(100 * covered / delivered) if delivered else 0,
        gaps=delivered - covered,
        top=[LifecycleSubcap.model_validate(dict(r)) for r in rows],
    )
