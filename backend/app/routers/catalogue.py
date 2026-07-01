"""Catalogue read surfaces (version-scoped, F9 conventions) over the cat_<version> data plane.

Lights up Capability workbench (tree + detail) and Mission control (pillar summary) on real data.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app import db
from app.deps import get_current_user
from app.services import sv_aliases as _sv_aliases
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
    epic_key: str | None = None
    summary: str | None = None
    confidence_level: str | None = None
    composite_score: float | None = None
    ac_score: float | None = None
    sd_score: float | None = None
    story_score: float | None = None
    delivery_score: float | None = None
    story_sv_code: str | None = None
    tier: str | None = None
    cap_name: str | None = None
    category_name: str | None = None
    reusability_layer: str | None = None
    population: str | None = None
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
    # set when any list was filled from the reference catalogue (v7) because this version had none
    # of its own — surfaced honestly in the UI as "enriched from <version>".
    inherited_from: str | None = None


class ConnectionSibling(BaseModel):
    id: str
    name: str
    pillar: str
    shared_platforms: int
    relation: str = "cluster"  # "cluster" (same L1 capability) | "semantic" (embedding-near)
    score: float = 0.0  # semantic: cosine; cluster: 0


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


class PlatformUseCase(BaseModel):
    """A use-case archetype delivered on a platform's subcaps, with its delivered-story count."""

    archetype: str
    stories: int


class PlatformDetail(BaseModel):
    l3_id: str
    name: str
    vendor: str | None = None
    category: str | None = None
    subcaps: list[PlatformSubcap]
    use_cases: list[PlatformUseCase] = []


class VendorRow(BaseModel):
    vendor: str
    plats: int
    subcap_count: int
    p1: int
    p2: int
    p3: int
    p4: int
    stories: int = 0  # distinct delivered Jira stories across the vendor's subcaps (this version)


class VendorCellSubcap(BaseModel):
    """A subcap on a vendor's platforms in one pillar — the heatmap-cell drilldown facet."""

    id: str
    name: str
    pillar: str
    stories: int


class UseCaseRow(BaseModel):
    use_case_id: str
    archetype: str | None = None  # the raw archetype CODE (leaderboard / filter key)
    name: str | None = None  # readable title (humanized archetype)
    description: str | None = None
    subcap_id: str
    subcap_name: str
    pillar: str
    category: str  # the L1 capability (category.name) the use case belongs to
    category_id: str  # the L1 capability id (P1C1 …) the capability toggle filters on
    cluster: str | None = None  # the L2 capability ("cluster") the owning subcap sits in
    maturity: str | None = None  # the use case's OWN maturity (e.g. M3+), not the subcap tier
    is_new: bool = False  # flagged new in this catalogue version
    n_stories: int = 0  # Jira stories MATCHED to this use case (real per-use-case delivery)
    subcap_stories: int = 0  # the owning subcap's total delivery (for the "X of N" context)


class ArchetypeFacet(BaseModel):
    archetype: str
    count: int  # distinct use cases of this archetype (in scope)
    n_stories: int = 0  # DISTINCT stories matched to this archetype's use cases (no double-count)


class CategoryFacet(BaseModel):
    category_id: str  # L1 capability id (P1C1 …)
    category: str  # L1 capability name
    pillar: str
    use_cases: int  # distinct use cases in this L1 (in scope)
    n_stories: int = 0  # DISTINCT stories matched to this L1's use cases


class UseCasePage(BaseModel):
    total: int
    page: int
    size: int
    items: list[UseCaseRow]
    archetypes: list[ArchetypeFacet]
    categories: list[CategoryFacet] = []  # L1-capability grouping (matched-story totals)


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

# Record completeness = filled CORE FIELDS / 5, computed LIVE from the subcap's own columns at read
# time. (It was read from a stored column that an older provision left at 0 — so mission control
# showed a permanent 0% until a re-provision. Computing it live makes it correct for every version
# immediately, and it never depends on stale data. A subcap always has a name, so it is never 0%.)
_FILL_SCORE = (
    "(((s.name IS NOT NULL AND s.name <> '')::int "
    "+ (s.description IS NOT NULL AND s.description <> '')::int "
    "+ (s.tier IS NOT NULL AND s.tier <> '')::int "
    "+ (s.solution_type IS NOT NULL AND s.solution_type <> '')::int "
    "+ (s.zennify_status IS NOT NULL AND s.zennify_status <> '')::int)::float / 5)"
)


def _norm_sv(sv: str) -> str:
    """Canonicalise a read-time subvertical scope through the alias map (config/subvertical_aliases
    .yaml) so a legacy ``PEN`` deep-link resolves to ``RIA`` — the code the data was actually
    migrated to at ingest/provision (stories.py, provision.py). Without this a ``?sv=PEN`` filter
    matches ZERO rows even though the delivery is all under RIA. ``all`` / empty / an
    ``unscoped:<client>`` scope pass through untouched (the suffix is a Jira project_key, not an SV
    code)."""
    if not sv or sv == "all" or sv.startswith("unscoped:"):
        return sv
    from app.services.sv_aliases import normalize_sv_code

    return normalize_sv_code(sv) or sv


async def _sv_membership(
    conn: AsyncConnection, s: str, version_id: str, sv: str
) -> tuple[str, dict[str, Any]]:
    """An EXISTS clause (+ bind params) selecting the subcaps in subvertical ``sv``, appended as
    ``... AND <clause>`` against a subcap aliased ``s``. Membership is the subcap's place in that
    subvertical's VALUE CHAIN (cat_<v>.subcap_vcc) — the FULL set, every tier (T1 + T2). When the
    version ships no VC mapping of its own it INHERITS the reference version's subcap_vcc (so the
    count still spans all tiers, not just delivered ones); only a true greenfield with no reference
    falls back to actual DELIVERY. Returns ('', {}) for the all-subvertical case."""
    if not sv or sv == "all":
        return "", {}
    if sv.startswith("unscoped:"):
        # an AI-detected unscoped subvertical = a client (Jira project_key) delivering outside the
        # nine modelled SVs; membership = the subcaps that client's unscoped stories delivered to.
        client = sv.split(":", 1)[1]
        return (
            " AND EXISTS (SELECT 1 FROM control.story_catalogue_link l "
            "JOIN control.story st ON st.story_key = l.story_key "
            "WHERE l.version_id = :vid AND l.subcap_id = s.subcap_id "
            f"AND st.project_key = :uclient AND (st.story_sv_code IS NULL "
            f"OR st.story_sv_code NOT IN ({_MODELLED_SV_SQL})))",
            {"uclient": client, "vid": version_id},
        )
    has_vcc = (await conn.execute(text(f"SELECT count(*) FROM {s}.subcap_vcc"))).scalar() or 0
    vc_s = s
    if not has_vcc:
        vc_s = await _enrichment_schema(conn, s, "subcap_vcc")  # inherit the reference's full chain
    if has_vcc or vc_s != s:
        # the subcap must exist in THIS version (s.subcap_id) AND be in the (own/inherited) chain
        return (
            f" AND EXISTS (SELECT 1 FROM {vc_s}.subcap_vcc vc "
            "WHERE vc.subcap_id = s.subcap_id AND vc.subvertical = :sv)",
            {"sv": sv},
        )
    return (
        " AND EXISTS (SELECT 1 FROM control.story_catalogue_link l "
        "JOIN control.story st ON st.story_key = l.story_key "
        "WHERE l.version_id = :vid AND l.subcap_id = s.subcap_id AND st.story_sv_code = :sv)",
        {"sv": sv, "vid": version_id},
    )


async def _enrichment_schema(conn: AsyncConnection, s: str, table: str) -> str:
    """The schema a lens's enrichment join should read — the version's OWN, or the reference
    version's (v7) when the version carries no enrichment of its own (the named ``table`` is empty).
    So the value-chain / vendor heatmap lenses INHERIT and render automatically on a base-only
    version, instead of an empty 'run carry-forward' state (no button, no re-provision)."""
    own = (await conn.execute(text(f"SELECT count(*) FROM {s}.{table}"))).scalar() or 0
    if own:
        return s
    from app.services import enrichment_seed

    ref_ver = enrichment_seed.reference_version()
    if not ref_ver:
        return s
    try:
        ref_v = await resolve_version(ref_ver)
    except Exception:  # noqa: BLE001 - reference not provisioned -> no inheritance
        return s
    ref_s = _schema(ref_v)
    if ref_s == s:
        return s
    ref_has = (await conn.execute(text(f"SELECT count(*) FROM {ref_s}.{table}"))).scalar() or 0
    return ref_s if ref_has else s


@router.get("/{version}/subcaps")
async def list_subcaps(
    version: str,
    sv: str = Query("all"),
    _user: dict[str, Any] = Depends(get_current_user),
) -> list[SubcapNode]:
    """The capability tree. ``sv`` scopes it to the subcaps that participate in that subvertical's
    value chain (cat_<v>.subcap_vcc) — so the workbench tree count matches mission control instead
    of always showing all 851. A version without a VC mapping scopes by delivery (story_sv_code)
    instead, so the tree never collapses to zero."""
    sv = _norm_sv(sv)
    v = await resolve_version(version)
    s = _schema(v)
    async with _engine().connect() as conn:
        sv_filter, sv_params = await _sv_membership(conn, s, v.version_id, sv)
        sql = text(
            "SELECT s.subcap_id AS id, s.name, cat.pillar_id AS pillar, cat.category_id AS cat_id, "
            "cat.name AS cat_name, cap.name AS cluster, s.lifecycle_state AS life, "
            "false AS is_new "
            + _JOINS.format(s=s)
            + (" WHERE 1=1" + sv_filter if sv_filter else "")
            + " ORDER BY s.subcap_id"
        )
        rows = (await conn.execute(sql, sv_params)).mappings().all()
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
        + _FILL_SCORE
        + " AS completeness, "
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
        d = dict(row)
        # Stat tiles must agree with the deep-dive tabs: when this version has no enrichment of
        # its own, the counts reflect the reference (v7) fallback the enrichment endpoint uses.
        if not d["n_use_cases"] or not d["n_platforms"]:
            from app.services import enrichment_seed

            ref_id = await _map_to_reference(conn, s, v.version_id, subcap_id)
            c = enrichment_seed.counts_for(ref_id)
            d["n_use_cases"] = d["n_use_cases"] or c["use_cases"]
            d["n_platforms"] = d["n_platforms"] or c["platforms"]
    return SubcapDetail.model_validate(d)


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
        "st.delivery_score::float AS delivery_score, st.epic_key, st.cap_name, "
        "st.category_name, st.reusability_layer, st.population, "
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


async def _map_to_reference(
    conn: AsyncConnection, schema: str, version_id: str, subcap_id: str
) -> str:
    """Map a subcap to its counterpart in the reference catalogue (v7) for enrichment fallback,
    through the ONE canonical rule every enrichment path shares (services/subcap_xref): exact id ->
    crosswalk -> L2-capability name + near description -> L2-capability name. Returns the reference
    subcap id (the same id when the version already uses v7 ids), so the read-time fallback matches
    what provisioning bakes — stat tiles and tabs never disagree."""
    from app.intelligence import gates
    from app.services import enrichment_seed
    from app.services.subcap_xref import resolve

    ref_ver, ref_index = enrichment_seed.reference_subcap_index()
    if not ref_ver or version_id == ref_ver or subcap_id in ref_index.ids:
        return subcap_id  # this IS the reference, or already a reference id
    meta = (
        await conn.execute(
            text(
                f"SELECT cap.name AS l2, s.description AS descr FROM {schema}.subcap s "
                f"JOIN {schema}.capability cap ON cap.capability_id = s.capability_id "
                "WHERE s.subcap_id = :sid"
            ),
            {"sid": subcap_id},
        )
    ).first()
    cw = (
        await conn.execute(
            text(
                "SELECT to_subcap FROM control.version_crosswalk "
                "WHERE from_version = :v AND to_version = :r AND from_subcap = :sid "
                "AND to_subcap IS NOT NULL LIMIT 1"
            ),
            {"v": version_id, "r": ref_ver, "sid": subcap_id},
        )
    ).first()
    crosswalk = {subcap_id: str(cw[0])} if cw else {}
    l2 = meta[0] if meta else None
    descr = meta[1] if meta else None
    lexical = resolve(subcap_id, l2, descr, ref_index, crosswalk)
    if lexical:
        return lexical
    # RULE 5 (semantic, deep-learning): the lexical rules found no capability match — a drifted
    # legacy version whose ids AND L1/L2 names differ from the reference. Resolve to the reference
    # subcap nearest in the shared embedding space (pgvector HNSW) above the configured floor, so a
    # renamed legacy version still inherits enrichment by MEANING. Additive + graceful: with no
    # embeddings on either side there is no row, so the subcap stays self-referential (unchanged).
    sub_min, _ = gates.xref_semantic_config()
    ref_schema = f"cat_{ref_ver}"
    if _SCHEMA_RE.match(ref_schema):
        near = (
            await conn.execute(
                text(
                    f"SELECT r.subcap_id, 1 - (r.embedding <=> q.embedding) AS cos "
                    f"FROM {ref_schema}.subcap r, "
                    f"(SELECT embedding FROM {schema}.subcap WHERE subcap_id = :sid) q "
                    "WHERE q.embedding IS NOT NULL AND r.embedding IS NOT NULL "
                    "ORDER BY r.embedding <=> q.embedding ASC LIMIT 1"
                ),
                {"sid": subcap_id},
            )
        ).first()
        if near is not None and float(near[1]) >= sub_min:
            return str(near[0])
    return subcap_id


@router.get("/{version}/subcaps/{subcap_id}/enrichment")
async def subcap_enrichment(
    version: str, subcap_id: str, _user: dict[str, Any] = Depends(get_current_user)
) -> SubcapEnrichment:
    """Personas, L3 platforms, use cases and M1-M5 maturity for a subcap (Overview/Use/Maturity).

    If this version carries none of its OWN enrichment for the subcap (e.g. a base-only uploaded
    catalogue), each empty facet is filled from the reference catalogue (v7) mapped BY SUBCAP ID
    (then the diff/crosswalk) and tagged ``inherited_from`` — so the deep dive is never empty and
    the source is honest. The version's own enrichment always wins where it exists."""
    from app.services import enrichment_seed

    v = await resolve_version(version)
    s = _schema(v)
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
        personas = [dict(r) for r in (await conn.execute(q_personas, p)).mappings().all()]
        platforms = [dict(r) for r in (await conn.execute(q_platforms, p)).mappings().all()]
        use_cases = [dict(r) for r in (await conn.execute(q_uc, p)).mappings().all()]
        maturity = [dict(r) for r in (await conn.execute(q_mat, p)).mappings().all()]
        offerings = [dict(r) for r in (await conn.execute(q_off, p)).mappings().all()]
        # fall back to the reference catalogue ONLY for the facets this version lacks
        inherited_from: str | None = None
        if not (personas and platforms and use_cases and maturity and offerings):
            ref_id = await _map_to_reference(conn, s, v.version_id, subcap_id)
            seed = enrichment_seed.enrichment_for(ref_id)
            ref_ver = enrichment_seed.reference_version()
            if not personas and seed["personas"]:
                personas, inherited_from = seed["personas"], ref_ver
            if not platforms and seed["platforms"]:
                platforms, inherited_from = seed["platforms"], ref_ver
            if not use_cases and seed["use_cases"]:
                use_cases, inherited_from = seed["use_cases"], ref_ver
            if not maturity and seed["maturity"]:
                maturity, inherited_from = seed["maturity"], ref_ver
            if not offerings and seed["offerings"]:
                offerings, inherited_from = seed["offerings"], ref_ver
    return SubcapEnrichment(
        personas=[Persona.model_validate(r) for r in personas],
        platforms=[Platform.model_validate(r) for r in platforms],
        use_cases=[UseCase.model_validate(r) for r in use_cases],
        maturity=[Maturity.model_validate(r) for r in maturity],
        offerings=[OfferingRef.model_validate(r) for r in offerings],
        inherited_from=inherited_from,
    )


@router.get("/{version}/subcaps/{subcap_id}/connections")
async def subcap_connections(
    version: str, subcap_id: str, _user: dict[str, Any] = Depends(get_current_user)
) -> SubcapConnections:
    """KG Layer-A siblings (same capability, ranked by shared L3 platforms) + recent gated
    news signals on this subcap (each with its trust envelope + reasoning backlink)."""
    v = await resolve_version(version)
    s = _schema(v)
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
        # CLUSTER siblings = same-capability subcaps ranked by shared platforms; inherit the
        # reference's platform links when this version has none of its own.
        ench_s = await _enrichment_schema(conn, s, "subcap_platform")
        cluster_sql = text(
            "SELECT s2.subcap_id AS id, s2.name, left(s2.subcap_id, 2) AS pillar, "
            f"(SELECT count(DISTINCT sp2.l3_id) FROM {ench_s}.subcap_platform sp2 "
            f"WHERE sp2.subcap_id = s2.subcap_id AND sp2.l3_id IN "
            f"(SELECT l3_id FROM {ench_s}.subcap_platform WHERE subcap_id = :sid)) "
            "AS shared_platforms "
            f"FROM {s}.subcap s2 WHERE s2.capability_id = "
            f"(SELECT capability_id FROM {s}.subcap WHERE subcap_id = :sid) "
            "AND s2.subcap_id <> :sid ORDER BY shared_platforms DESC, s2.subcap_id LIMIT 6"
        )
        # SEMANTIC siblings = nearest by MEANING in the embedding space, CROSS-capability — so a
        # platform-sparse / singleton-cluster subcap is never an island (deep integration). Degrades
        # to cluster-only when the version has no embeddings (q.embedding NULL -> no rows).
        semantic_sql = text(
            "SELECT s2.subcap_id AS id, s2.name, left(s2.subcap_id, 2) AS pillar, "
            "1 - (s2.embedding <=> q.embedding) AS score "
            f"FROM {s}.subcap s2, (SELECT embedding FROM {s}.subcap WHERE subcap_id = :sid) q "
            "WHERE q.embedding IS NOT NULL AND s2.embedding IS NOT NULL AND s2.subcap_id <> :sid "
            f"AND s2.capability_id <> "
            f"(SELECT capability_id FROM {s}.subcap WHERE subcap_id = :sid) "
            "ORDER BY s2.embedding <=> q.embedding ASC LIMIT 6"
        )
        cluster = (await conn.execute(cluster_sql, {"sid": subcap_id})).mappings().all()
        semantic = (await conn.execute(semantic_sql, {"sid": subcap_id})).mappings().all()
        sigs = (
            (await conn.execute(sig_sql, {"ver": v.version_id, "sid": subcap_id})).mappings().all()
        )
    seen = {str(r["id"]) for r in cluster}
    siblings = [
        ConnectionSibling(
            id=str(r["id"]),
            name=str(r["name"]),
            pillar=str(r["pillar"]),
            shared_platforms=int(r["shared_platforms"]),
            relation="cluster",
        )
        for r in cluster
    ]
    for r in semantic:
        if str(r["id"]) in seen:
            continue
        siblings.append(
            ConnectionSibling(
                id=str(r["id"]),
                name=str(r["name"]),
                pillar=str(r["pillar"]),
                shared_platforms=0,
                relation="semantic",
                score=round(float(r["score"]), 3),
            )
        )
    return SubcapConnections(
        siblings=siblings,
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
    kind: str  # uses_platform | maps_to_offering | shares_platform | semantically_similar
    layer: str  # A_deterministic | B_proposed
    score: float | None = None  # Layer-B proposal confidence (pending_edge.weight); None for A


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
        # Layer A is the link-table projection; inherit the reference's link tables when this
        # version has none of its own, so the graph is never empty for a base-only version.
        ench_s = await _enrichment_schema(conn, s, "subcap_platform")
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
                        f"SELECT l.l3_id AS id, l.name FROM {ench_s}.subcap_platform sp "
                        f"JOIN {ench_s}.l3_platform l ON l.l3_id = sp.l3_id "
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
                        f"SELECT o.offering_id AS id, o.name FROM {ench_s}.offering_subcap os "
                        f"JOIN {ench_s}.offering o ON o.offering_id = os.offering_id "
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
                        f"FROM {ench_s}.subcap_platform sp1 "
                        f"JOIN {ench_s}.subcap_platform sp2 ON sp2.l3_id = sp1.l3_id "
                        f"JOIN {ench_s}.subcap sc ON sc.subcap_id = sp2.subcap_id "
                        "WHERE sp1.subcap_id = :sid AND sp2.subcap_id <> :sid "
                        "GROUP BY sp2.subcap_id, sc.name ORDER BY shared DESC LIMIT 6"
                    ),
                    {"sid": subcap},
                )
            )
            .mappings()
            .all()
        )
        # Layer-B pending edges: resolve the kg_node uuids back to their subcap ref_ids (the ids the
        # graph renders), so a proposed edge connects the centre to a real rendered node.
        pend = (
            (
                await conn.execute(
                    text(
                        "SELECT fn.ref_id AS source, fn.label AS source_label, "
                        "tn.ref_id AS target, tn.label AS target_label, pe.kind::text AS kind, "
                        "pe.weight AS score "
                        "FROM control.pending_edge pe "
                        "JOIN control.kg_node fn ON fn.node_id = pe.from_node "
                        "JOIN control.kg_node tn ON tn.node_id = pe.to_node "
                        "WHERE pe.version_id = :ver "
                        "AND (fn.ref_id = :sid OR tn.ref_id = :sid) "
                        "AND pe.status = 'pending' LIMIT 10"
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
    pending: list[KgEdge] = []
    existing_ids = {n.id for n in nodes}
    for p in pend:
        pending.append(
            KgEdge(
                source=p["source"],
                target=p["target"],
                kind=p["kind"],
                layer="B_proposed",
                score=float(p["score"]) if p["score"] is not None else None,
            )
        )
        # add the proposed neighbour subcap node(s) so the dashed edge connects to a drawn node
        for ref, label in ((p["source"], p["source_label"]), (p["target"], p["target_label"])):
            if ref != subcap and ref not in existing_ids:
                nodes.append(KgNode(id=ref, kind="subcap", label=str(label), pillar=ref[:2]))
                existing_ids.add(ref)
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
    """The value-chain atlas (A3). A PINNED subvertical (``sv``) renders its REAL ordered stage
    chain from the catalogue's per-SV mapping (cat_<v>.value_chain_cluster + subcap_vcc; a version
    with no mapping of its own INHERITS the reference version's). 'All SV' CONSOLIDATES the whole
    catalogue into high-level value-chain stages (capability-cluster derivation) — clean and MECE,
    with no subvertical tag — because the nine subverticals' granular stages don't merge cleanly.
    ``pillar`` filters membership."""
    from app.services import enrichment_seed
    from app.services.value_chain import (
        INDIRECT_STAGE,
        clean_stage_name,
        derive_value_chain,
        descriptive_stage_name,
        load_rollup_config,
        stage_concept,
    )

    sv = _norm_sv(sv)
    v = await resolve_version(version)
    s = _schema(v)
    p_active = bool(pillar and pillar != "all")
    sv_active = bool(sv and sv != "all")
    async with _engine().connect() as conn:
        has_vcc = (await conn.execute(text(f"SELECT count(*) FROM {s}.subcap_vcc"))).scalar() or 0
        # A version with no VC mapping of its OWN (e.g. v5 provisioned before the cascade) INHERITS
        # the reference version's (v7) chains — the same catalogue truth, scoped to this version's
        # subcaps — rather than deriving ad-hoc L1 clusters. Only a true greenfield (no reference
        # mapping at all) falls through to the live derivation.
        vc_schema, inherited = s, False
        if not has_vcc:
            ref_ver = enrichment_seed.reference_version()
            if ref_ver and ref_ver != v.version_id:
                try:
                    ref_v = await resolve_version(ref_ver)
                except Exception:  # noqa: BLE001 - reference not provisioned -> derive fallback
                    ref_v = None
                if ref_v is not None:
                    ref_s = _schema(ref_v)
                    ref_has = (
                        await conn.execute(text(f"SELECT count(*) FROM {ref_s}.subcap_vcc"))
                    ).scalar() or 0
                    if ref_has:
                        vc_schema, has_vcc, inherited = ref_s, ref_has, True
        # delivery-ranked subverticals for the picker (from the own/inherited VC mapping)
        subverticals = (
            [
                str(r[0])
                for r in await conn.execute(
                    text(
                        f"SELECT vcc.sv AS subvertical FROM "
                        f"(SELECT DISTINCT subvertical AS sv FROM {vc_schema}.subcap_vcc) vcc "
                        "LEFT JOIN (SELECT st.story_sv_code AS sv, "
                        "count(DISTINCT st.story_key) AS n FROM control.story_catalogue_link l "
                        "JOIN control.story st ON st.story_key = l.story_key "
                        "WHERE l.version_id = :vid GROUP BY st.story_sv_code) d ON d.sv = vcc.sv "
                        "ORDER BY coalesce(d.n, 0) DESC, vcc.sv"
                    ),
                    {"vid": v.version_id},
                )
            ]
            if has_vcc
            else []
        )
        if has_vcc:
            # Real per-subvertical stages. A PINNED subvertical shows its own ordered chain. 'All
            # SV' CONSOLIDATES the nine overlapping chains into the most-delivered subvertical's
            # canonical chain (so P1C1.1.1 reads MARKET -> BACK OFFICE OPS, COMPLIANCE & PLATFORM,
            # its RB stages), folding any subcap NOT in that chain in under its own stage — every
            # subcap covered, none duplicated, NO subvertical tag. subcap_vcc + value_chain_cluster
            # come from vc_schema (own or inherited); the subcap NAME + existence filter come from
            # THIS version. clean_stage_name strips "(SV-Specific…)" noise + folds "Indirect: …".
            scoped = [sv] if sv_active else subverticals
            where = ["vc.subvertical = ANY(:svs)"]
            params: dict[str, Any] = {"svs": scoped}
            if p_active:
                where.append("left(vc.subcap_id, 2) = :p")
                params["p"] = pillar
            sql = text(
                "SELECT vc.subvertical AS sv, v.vcc_id AS code, v.name, vc.stage_ord AS ord, "
                "vc.subcap_id, sc.name AS subcap_name, left(vc.subcap_id, 2) AS pillar "
                f"FROM {vc_schema}.subcap_vcc vc "
                f"JOIN {vc_schema}.value_chain_cluster v ON v.vcc_id = vc.vcc_id "
                f"JOIN {s}.subcap sc ON sc.subcap_id = vc.subcap_id "
                f"WHERE {' AND '.join(where)}"
            )
            rows = (await conn.execute(sql, params)).mappings().all()

            def _group(subset: Any) -> dict[str, dict[str, Any]]:
                out_segs: dict[str, dict[str, Any]] = {}
                for r in subset:
                    nm = clean_stage_name(str(r["name"]))
                    g = out_segs.setdefault(
                        nm,
                        {"code": str(r["code"]), "name": nm, "ord": 9999, "subcaps": {}},
                    )
                    if str(r["code"]) < g["code"]:
                        g["code"] = str(r["code"])
                    if r["ord"] is not None and r["ord"] < g["ord"]:
                        g["ord"] = r["ord"]
                    g["subcaps"][str(r["subcap_id"])] = {
                        "id": str(r["subcap_id"]),
                        "name": str(r["subcap_name"]),
                        "pillar": r["pillar"],
                    }
                return out_segs

            vc_cfg = load_rollup_config()
            corder = {c: i for i, c in enumerate(vc_cfg.get("concept_order", []))}
            # stage_concept scans ~320 keywords per call; with ~13k subcap_vcc rows but only ~230
            # DISTINCT stage names, memoise (clean + concept) per distinct raw name — ~60x fewer.
            _stage_cache: dict[str, tuple[str, str]] = {}

            def _stage_key(raw: str) -> tuple[str, str]:
                hit = _stage_cache.get(raw)
                if hit is None:
                    cn = clean_stage_name(raw)
                    hit = (cn, stage_concept(cn, vc_cfg))
                    _stage_cache[raw] = hit
                return hit

            if sv_active:
                # present the SV's OWN process flow logically: order stages by their concept's place
                # in the lifecycle (config concept_order), then the workbook order within a concept
                # (the raw workbook stage_order is not a front-to-back flow).
                def _flow(x: dict[str, Any]) -> tuple[Any, ...]:
                    if x["name"] == INDIRECT_STAGE:
                        return (2, 999, x["ord"], x["name"])
                    k = _stage_key(x["name"])[1]
                    if k.startswith("c:"):
                        return (0, corder.get(k[2:], 999), x["ord"], x["name"])
                    return (1, 999, x["ord"], x["name"])

                ordered = sorted(_group(rows).values(), key=_flow)
                sv_out, resolved = sv, sv
            else:
                # consolidate ALL subverticals into a MECE lifecycle chain: group every stage by
                # semantic CONCEPT so it is collectively exhaustive (every concept present is one
                # stage) and mutually exclusive (one clean, titled stage per concept, ordered by the
                # config concept_order). A subcap counts once per concept it maps to across
                # subverticals; a stage matching no concept keeps its own most-common real name.
                labels = vc_cfg.get("concept_labels", {})
                groups: dict[str, dict[str, Any]] = {}
                name_freq: dict[str, Counter[str]] = {}
                for r in rows:
                    cn, key = _stage_key(str(r["name"]))
                    g = groups.setdefault(key, {"code": str(r["code"]), "subcaps": {}})
                    if str(r["code"]) < g["code"]:
                        g["code"] = str(r["code"])
                    g["subcaps"][str(r["subcap_id"])] = {
                        "id": str(r["subcap_id"]),
                        "name": str(r["subcap_name"]),
                        "pillar": r["pillar"],
                    }
                    name_freq.setdefault(key, Counter())[cn] += 1
                # display: a clean canonical label for a matched concept (c:…), else its most-common
                # real name (so genuinely-distinct unmatched stages stay verbatim)
                for key, g in groups.items():
                    items = name_freq[key].items()
                    common = sorted(items, key=lambda kv: (-kv[1], len(kv[0]), kv[0]))[0][0]
                    g["name"] = labels.get(key[2:], common) if key.startswith("c:") else common

                def _order_key(kv: tuple[str, dict[str, Any]]) -> tuple[Any, ...]:
                    key, g = kv
                    if g["name"] == INDIRECT_STAGE:
                        return (2, 0, g["name"])  # "Indirect linkages" always last
                    if key.startswith("c:"):
                        return (0, corder.get(key[2:], 999), g["name"])
                    return (1, 0, g["name"])  # a verbatim stage, after the canonical concepts

                ordered = [g for _, g in sorted(groups.items(), key=_order_key)]
                sv_out, resolved = "all", ""
            clusters: list[dict[str, Any]] = []
            for pos, g in enumerate(ordered, 1):
                subs = sorted(g["subcaps"].values(), key=lambda y: y["id"])
                pset = {x["pillar"] for x in subs}
                clusters.append(
                    {
                        "code": g["code"],
                        "name": descriptive_stage_name(g["name"], vc_cfg),
                        "position": pos,
                        "pillar": next(iter(pset)) if len(pset) == 1 else None,
                        "count": len(subs),
                        "subcaps": subs,
                        "merged_from": [],
                    }
                )
            # Per-stage + canonical-rollup DELIVERY aggregation (A3). Story/project counts + the
            # delivery-confidence split are the REAL Jira corpus (story_catalogue_link is Jira-only)
            # for THIS version.
            from app.services.value_chain import build_rollup

            all_subs = sorted({x["id"] for c in clusters for x in c["subcaps"]})
            story_by_subcap: dict[str, set[str]] = {}
            project_by_subcap: dict[str, set[str]] = {}
            story_conf: dict[str, str] = {}  # story_key -> HIGH/MEDIUM/LOW
            if all_subs:
                link_sql = text(
                    "SELECT l.subcap_id, l.story_key, st.project_key, st.confidence_level "
                    "FROM control.story_catalogue_link l "
                    "JOIN control.story st ON st.story_key = l.story_key "
                    "WHERE l.version_id = :vid AND l.subcap_id = ANY(:subs)"
                )
                link_rows = (
                    (await conn.execute(link_sql, {"vid": v.version_id, "subs": all_subs}))
                    .mappings()
                    .all()
                )
                for r in link_rows:
                    sid = str(r["subcap_id"])
                    sk = str(r["story_key"])
                    story_by_subcap.setdefault(sid, set()).add(sk)
                    if r["project_key"]:
                        project_by_subcap.setdefault(sid, set()).add(str(r["project_key"]))
                    if r["confidence_level"] is not None:
                        story_conf[sk] = str(r["confidence_level"])
            # enrich each stage with delivery stories + a P1-P4 pillar tally + top-8 by story count
            for c in clusters:
                pill = {"P1": 0, "P2": 0, "P3": 0, "P4": 0}
                s_union: set[str] = set()
                for x in c["subcaps"]:
                    s_union |= story_by_subcap.get(x["id"], set())
                    pk = str(x.get("pillar") or "")[:2]
                    if pk in pill:
                        pill[pk] += 1
                c["stories"] = len(s_union)
                c["pillars"] = pill
                c["top"] = sorted(
                    (
                        {
                            "id": x["id"],
                            "name": x["name"],
                            "n": len(story_by_subcap.get(x["id"], set())),
                            "pillar": x.get("pillar"),
                        }
                        for x in c["subcaps"]
                    ),
                    key=lambda t: (-int(t["n"]), str(t["id"])),
                )[:8]
            rollup = build_rollup(clusters, story_by_subcap, project_by_subcap, story_conf)
            total = len({x["id"] for c in clusters for x in c["subcaps"]})
            return {
                "version": version,
                "sv": sv_out,
                "resolved_sv": resolved,
                "sv_requested": sv or "all",
                "subverticals": subverticals,
                "source": (
                    "catalogue_vc_mapping_inherited" if inherited else "catalogue_vc_mapping"
                ),
                "inherited_from": vc_schema.removeprefix("cat_") if inherited else None,
                "chains": (
                    [{"sv": sv_out, "clusters": clusters, "total_subcaps": total}]
                    if clusters
                    else []
                ),
                "clusters": clusters,
                "raw_clusters": len(clusters),
                "deduped": 0,
                "total_subcaps": total,
                "rollup": rollup,
            }
        # TRUE greenfield (no mapping anywhere, no reference to inherit): derive from clusters.
        where_sql = " WHERE cat.pillar_id = :p" if p_active else ""
        derive_rows = (
            (
                await conn.execute(
                    text(
                        "SELECT s.subcap_id, s.name, cat.pillar_id AS pillar, cat.name AS cluster, "
                        "cap.name AS category "
                        + _JOINS.format(s=s)
                        + where_sql
                        + " ORDER BY s.subcap_id"
                    ),
                    {"p": pillar},
                )
            )
            .mappings()
            .all()
        )
    out = derive_value_chain([dict(r) for r in derive_rows])
    derived = out.get("clusters", [])
    return {
        "version": version,
        "sv": "all",
        "resolved_sv": "",
        "sv_requested": sv or "all",
        "subverticals": subverticals,
        "source": "derived_from_clusters",
        "inherited_from": None,
        "chains": (
            [{"sv": "all", "clusters": derived, "total_subcaps": int(out.get("total_subcaps", 0))}]
            if derived
            else []
        ),
        "clusters": derived,
        "raw_clusters": len(derived),
        "deduped": int(out.get("deduped", 0)),
        "total_subcaps": int(out.get("total_subcaps", 0)),
    }


@router.get("/{version}/summary")
async def summary(
    version: str,
    sv: str = Query("all"),
    _user: dict[str, Any] = Depends(get_current_user),
) -> CatalogueSummary:
    sv = _norm_sv(sv)
    v = await resolve_version(version)
    s = _schema(v)
    # COMPLETENESS = (total - decayed) / total. decay = subcaps with NO mapped story at all — Jira
    # OR the per-version synthetic corpus (story_subcap_carry, status confirmed/review). So coverage
    # means "has any delivery evidence" and approaches 100%; the concentration heatmaps stay real-
    # Jira-only (story_catalogue_link). A decayed subcap can stay active; it is flagged HIGH for an
    # admin to mark inactive or keep, never auto-deactivated.
    # `sv` scopes EVERYTHING to the subcaps that participate in that subvertical's value chain
    # (cat_<v>.subcap_vcc, from the catalogue's own per-SV mapping) — so the mission-control tiles
    # genuinely change when the subvertical toggle changes. A version without a VC mapping scopes
    # by delivery (story_sv_code) instead, so the tiles never collapse to zero (_sv_membership).
    async with _engine().connect() as conn:
        sv_filter, sv_params = await _sv_membership(conn, s, v.version_id, sv)
        sql = text(
            "SELECT p.pillar_id, p.name, count(s.subcap_id) AS subcap_count, "
            "coalesce(count(s.subcap_id) FILTER (WHERE EXISTS ("
            "  SELECT 1 FROM control.story_subcap_carry c "
            "  WHERE c.target_version = :vid AND c.carried_to_subcap = s.subcap_id "
            "  AND c.status IN ('confirmed', 'review')))::float "
            "/ nullif(count(s.subcap_id), 0), 0) AS completeness, "
            "count(s.subcap_id) FILTER (WHERE NOT EXISTS ("
            "  SELECT 1 FROM control.story_subcap_carry c "
            "  WHERE c.target_version = :vid AND c.carried_to_subcap = s.subcap_id "
            "  AND c.status IN ('confirmed', 'review'))) AS decay "
            f"FROM {s}.pillar p "
            f"LEFT JOIN {s}.category cat ON cat.pillar_id = p.pillar_id "
            f"LEFT JOIN {s}.capability cap ON cap.category_id = cat.category_id "
            f"LEFT JOIN {s}.subcap s ON s.capability_id = cap.capability_id{sv_filter} "
            "GROUP BY p.pillar_id, p.name ORDER BY p.pillar_id"
        )
        rows = (await conn.execute(sql, {"vid": v.version_id, **sv_params})).mappings().all()
    pillars = [PillarSummary.model_validate(dict(r)) for r in rows]
    # total = the filtered pillar counts (so it ALWAYS reconciles with the tiles, and a version
    # without a VC mapping reports its delivery-scoped count rather than a subcap_vcc zero).
    total = sum(p.subcap_count for p in pillars)
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
# read-time strip of a trailing "(SV-Specific: …)"/"(Ag)"-style explanation from a stored stage
# label, so the value-chain lens merges variants and shows clean names (the canonical writer is
# services/value_chain.clean_stage_name, applied at provision).
_VC_CLEAN = r"regexp_replace(vcl.name, '\s*\([^()]*\)\s*$', '')"
# Fold a legacy SV suffix in the tier at READ time (config alias map) so the Tier-coverage lens
# shows e.g. T2-RIA — not a stale T2-PEN — even on a version (v5) provisioned before the fold; two
# raw tiers then merge into one row under GROUP BY. Same intent as _VC_CLEAN for stage names.
_MATURITY_TIER = _sv_aliases.legacy_suffix_fold_sql("coalesce(sc.tier,'untiered')")
_LENS_GROUP: dict[str, tuple[str, str, str]] = {
    # lens -> (group-key expr, label expr, extra FROM/JOIN)
    "pillar": ("sc.subcap_id", "sc.name", ""),  # rows = most-delivered subcaps
    "maturity": (_MATURITY_TIER, _MATURITY_TIER, ""),
    "subvertical": (
        # MODELLED subverticals only (restricted in _heatmap_scope); labelled code · name in the
        # builder. No "(unscoped)" row — the NULL-sv / outside-the-nine delivery is the detector's.
        "st.story_sv_code",
        "st.story_sv_code",
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
        # REAL stage names (same labels as the atlas) — the VCC code is only an id. The chain is
        # PER-SUBVERTICAL, so scope to the active one (or, when 'all', the most-covered) rather than
        # fanning Jira delivery across every subvertical's chain at once. Strip the trailing
        # "(SV-Specific: …)"-style explanation at read time so the lens shows the clean, merged
        # stage name even on catalogues provisioned before the provision-time clean.
        _VC_CLEAN,
        _VC_CLEAN,
        " JOIN {s}.subcap_vcc vcc ON vcc.subcap_id = sc.subcap_id"
        " AND vcc.subvertical = coalesce(nullif(:vc_sv, 'all'),"
        " (SELECT st.story_sv_code FROM control.story_catalogue_link l2"
        " JOIN control.story st ON st.story_key = l2.story_key"
        " WHERE l2.version_id = :ver AND st.story_sv_code IN"
        " (SELECT DISTINCT subvertical FROM {s}.subcap_vcc)"
        " GROUP BY st.story_sv_code ORDER BY count(DISTINCT st.story_key) DESC,"
        " st.story_sv_code LIMIT 1))"
        " JOIN {s}.value_chain_cluster vcl ON vcl.vcc_id = vcc.vcc_id",
    ),
}
_BAND_AXIS = ["1.0–1.7", "1.7–2.3", "2.3–3.0", "3.0–3.7", "3.7–4.3", "4.3–5.0"]

# The nine MODELLED subverticals -> display names (the subvertical lens labels each ``code · name``,
# prototype parity). Unscoped delivery (story_sv_code NULL / outside these) is NOT a lens row — that
# is the detector's job (gated candidate subverticals in Notifications), never a "(unscoped)" row.
_SV_NAMES = {
    "RB": "Retail Banking",
    "CU": "Credit Unions",
    "CL": "Commercial Lending",
    "CIB": "Corporate & Investment Banking",
    "FC": "Farm Credit / Ag Lending",
    "AM": "Asset & Wealth Management",
    "RIA": "RIA / Broker-Dealer",
    "IC": "Insurance Carriers",
    "IB": "Insurance Brokerages",
}


def _sv_label(code: str) -> str:
    name = _SV_NAMES.get(code)
    return f"{code} · {name}" if name else code


async def _heatmap_scope(
    conn: AsyncConnection, s: str, lens: str, pillar: str, sv: str, version_id: str
) -> tuple[str, str, str, list[str], dict[str, Any]]:
    """Shared scope for the concentration heatmap AND its drill: ``(key_expr, label_expr, join,
    where, params)`` for the active lens + pillar/sv filters. The heatmap GROUPs by ``key``; the
    drill adds ``key_expr = :key`` and groups by subcap — both off the SAME join, so the drilldown
    reconciles with the cell it was opened from."""
    key_expr, label_expr, join_tmpl = _LENS_GROUP[lens]
    # value-chain + vendor read enrichment (subcap_vcc / subcap_platform); a version without its own
    # inherits the reference's so the lens renders automatically, never empty.
    lens_table = {"value-chain": "subcap_vcc", "vendor": "subcap_platform"}
    ench_s = await _enrichment_schema(conn, s, lens_table[lens]) if lens in lens_table else s
    join = join_tmpl.format(s=ench_s)
    where = ["l.version_id = :ver"]
    params: dict[str, Any] = {"ver": version_id}
    if pillar != "all":
        where.append("left(sc.subcap_id, 2) = :pil")
        params["pil"] = pillar
    if lens == "value-chain":
        # the value-chain lens scopes by the CHAIN's subvertical (in the join), not the story sv
        if sv.startswith("unscoped:"):
            # an unscoped client has NO chain of its own -> show ALL stages, count only its stories
            params["vc_sv"] = "all"
            where.append(
                "st.project_key = :uclient AND (st.story_sv_code IS NULL "
                f"OR st.story_sv_code NOT IN ({_MODELLED_SV_SQL}))"
            )
            params["uclient"] = sv.split(":", 1)[1]
        else:
            params["vc_sv"] = sv
    elif sv.startswith("unscoped:"):
        # an AI-detected unscoped subvertical: scope to that client's stories outside the nine
        where.append(
            "st.project_key = :uclient AND (st.story_sv_code IS NULL "
            f"OR st.story_sv_code NOT IN ({_MODELLED_SV_SQL}))"
        )
        params["uclient"] = sv.split(":", 1)[1]
    elif sv != "all":
        where.append("st.story_sv_code = :sv")
        params["sv"] = sv
    if lens == "subvertical" and not sv.startswith("unscoped:"):
        # the subvertical lens shows ONLY the nine modelled SVs (no NULL/unscoped "(unscoped)" row);
        # unscoped delivery is surfaced as gated candidate subverticals by the detector instead.
        where.append(f"st.story_sv_code IN ({_MODELLED_SV_SQL})")
    return key_expr, label_expr, join, where, params


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
    sv = _norm_sv(sv)
    v = await resolve_version(version)
    s = _schema(v)
    if lens not in _LENS_GROUP:
        lens = "pillar"
    async with _engine().connect() as conn:
        key_expr, label_expr, join, where, params = await _heatmap_scope(
            conn, s, lens, pillar, sv, v.version_id
        )
        params["lim"] = limit
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
                label=_sv_label(str(r["key"])) if lens == "subvertical" else str(r["label"]),
                subtitle=sub,
                total=int(r["total"]),
                cells=cs,
                pillar=r["pillar"] if lens == "pillar" else None,
            )
        )
    return HeatmapResp(lens=lens, axis=_BAND_AXIS, rows=out, max=gmax)


class HeatmapDrillSubcap(BaseModel):
    id: str
    name: str
    pillar: str
    stories: int


class HeatmapDrillResp(BaseModel):
    lens: str
    key: str
    subcaps: list[HeatmapDrillSubcap]
    total_subcaps: int
    total_stories: int


@router.get("/{version}/heatmap/drill")
async def heatmap_drill(
    version: str,
    lens: str = Query("pillar"),
    key: str = Query(...),
    pillar: str = Query("all"),
    sv: str = Query("all"),
    limit: int = Query(50, ge=1, le=200),
    _user: dict[str, Any] = Depends(get_current_user),
) -> HeatmapDrillResp:
    """The subcaps behind ONE heatmap lens-group row — Mission control's drill drawer. Same scope +
    join as the heatmap, plus ``key_expr = :key``, grouped by subcap and delivery-ranked, so the
    drilldown reconciles with the row it was opened from. The pillar lens needs no drill (its rows
    ARE subcaps -> peek), so it returns empty."""
    sv = _norm_sv(sv)
    v = await resolve_version(version)
    s = _schema(v)
    if lens not in _LENS_GROUP or lens == "pillar":
        return HeatmapDrillResp(lens=lens, key=key, subcaps=[], total_subcaps=0, total_stories=0)
    async with _engine().connect() as conn:
        key_expr, _label, join, where, params = await _heatmap_scope(
            conn, s, lens, pillar, sv, v.version_id
        )
        where.append(f"{key_expr} = :key")
        params["key"] = key
        params["lim"] = limit
        sql = text(
            "SELECT sc.subcap_id AS id, sc.name, left(sc.subcap_id, 2) AS pillar, "
            "count(DISTINCT st.story_key) AS stories "
            "FROM control.story_catalogue_link l "
            "JOIN control.story st ON st.story_key = l.story_key "
            f"JOIN {s}.subcap sc ON sc.subcap_id = l.subcap_id{join} "
            f"WHERE {' AND '.join(where)} "
            "GROUP BY sc.subcap_id, sc.name ORDER BY stories DESC, sc.subcap_id LIMIT :lim"
        )
        rows = (await conn.execute(sql, params)).mappings().all()
    subs = [
        HeatmapDrillSubcap(
            id=str(r["id"]), name=str(r["name"]), pillar=str(r["pillar"]), stories=int(r["stories"])
        )
        for r in rows
    ]
    return HeatmapDrillResp(
        lens=lens,
        key=key,
        subcaps=subs,
        total_subcaps=len(subs),
        total_stories=sum(x.stories for x in subs),
    )


# the nine modelled subverticals — anything else (or NULL) is unscoped delivery
_MODELLED_SV_SQL = "'RB','CU','CL','CIB','FC','AM','RIA','IC','IB'"


class UnscopedCandidate(BaseModel):
    flag_id: str
    chain_id: str | None = None
    client: str  # the Jira project_key driving this unscoped delivery
    code: str | None = None  # provisional subvertical code
    name: str  # proposed (provisional) subvertical name
    severity: str
    status: str
    stories: int
    cells: list[int]  # 6 composite-score bands — the ORANGE heatmap row
    pillars: list[str] = []
    top_capabilities: list[dict[str, Any]] = []
    overlap_sv: str | None = None
    overlap: float = 0.0
    distinct: bool | None = None  # deep cross-check: genuinely distinct from the nine modelled SVs?
    distinct_closest_sv: str | None = None  # the modelled SV its footprint is closest to
    distinct_similarity: float | None = None  # Jaccard over delivered subcaps vs that closest SV
    claim_label: str | None = None
    source_tier: str | None = None
    ers: float | None = None
    samples: list[str] = []


class UnscopedSubverticalsResp(BaseModel):
    version: str
    axis: list[str]  # the 6 composite-score band labels (same axis as the heatmap)
    candidates: list[UnscopedCandidate]
    max: int  # global max cell, for intensity scaling


@router.get("/{version}/unscoped-subverticals")
async def unscoped_subverticals(
    version: str,
    status_filter: str = Query("open", alias="status"),
    _user: dict[str, Any] = Depends(get_current_user),
) -> UnscopedSubverticalsResp:
    """Mission-control drilldown: the AI-identified candidate subverticals we have NOT scoped — the
    gated proposals from services/subverticals (clients delivering outside the nine). Each carries
    its own 6-band cell strip (rendered ORANGE on the heatmap), volume-stratified, with the client
    names, capability profile, overlap check and trust envelope for the drilldown."""
    v = await resolve_version(version)
    async with _engine().connect() as conn:
        where = "WHERE kind = 'unscoped_subvertical'"
        params: dict[str, Any] = {}
        if status_filter:
            where += " AND status = :st"
            params["st"] = status_filter
        flags = (
            (
                await conn.execute(
                    text(
                        "SELECT flag_id, chain_id, severity, status, target_ref, detail "
                        f"FROM control.change_flag {where} ORDER BY "
                        "CASE severity WHEN 'BLOCKING' THEN 0 WHEN 'HIGH' THEN 1 "
                        "WHEN 'MED' THEN 2 ELSE 3 END, (detail->>'stories')::int DESC NULLS LAST"
                    ),
                    params,
                )
            )
            .mappings()
            .all()
        )
        # gated proposals when a scan has run; else compute the candidates READ-ONLY so the panel
        # is functional out of the box (the explicit/scheduled scan turns them into gated proposals
        # with approve/reject in Notifications).
        srcs: list[dict[str, Any]] = []
        if flags:
            srcs = [
                {
                    **(f["detail"] or {}),
                    "flag_id": str(f["flag_id"]),
                    "chain_id": str(f["chain_id"]) if f["chain_id"] else None,
                    "status": str(f["status"]),
                    "severity": str(f["severity"]),
                    "client": str(f["target_ref"]),
                }
                for f in flags
            ]
        else:
            from app.services import subverticals
            from app.services.change_flags import _severity

            srcs = [
                {
                    **c,
                    "flag_id": "",
                    "chain_id": None,
                    "status": "detected",
                    "severity": _severity(int(c["stories"])),
                }
                for c in await subverticals.candidates_for(version)
            ]
        clients = [str(s["client"]) for s in srcs]
        cells_by_client: dict[str, list[int]] = {}
        if clients:
            band = "least(6, greatest(1, width_bucket(composite_score, 1, 5, 6)))"
            cell_cols = ", ".join(
                f"count(*) FILTER (WHERE band = {k}) AS c{k}" for k in range(1, 7)
            )
            crows = (
                (
                    await conn.execute(
                        text(
                            f"SELECT client, {cell_cols} FROM (SELECT project_key AS client, "
                            f"{band} AS band FROM control.story WHERE NOT is_synthetic "
                            "AND project_key = ANY(:clients) AND (story_sv_code IS NULL "
                            f"OR story_sv_code NOT IN ({_MODELLED_SV_SQL}))) q GROUP BY client"
                        ),
                        {"clients": clients},
                    )
                )
                .mappings()
                .all()
            )
            cells_by_client = {
                str(r["client"]): [int(r[f"c{k}"]) for k in range(1, 7)] for r in crows
            }
    candidates: list[UnscopedCandidate] = []
    gmax = 0
    for sc in srcs:
        client = str(sc["client"])
        cells = cells_by_client.get(client, [0, 0, 0, 0, 0, 0])
        gmax = max(gmax, *cells)
        candidates.append(
            UnscopedCandidate(
                flag_id=str(sc.get("flag_id") or ""),
                chain_id=sc.get("chain_id"),
                client=client,
                code=sc.get("code"),
                name=str(sc.get("name") or client),
                severity=str(sc.get("severity") or "LOW"),
                status=str(sc.get("status") or "detected"),
                stories=int(sc.get("stories", sum(cells))),
                cells=cells,
                pillars=list(sc.get("pillars", [])),
                top_capabilities=list(sc.get("top_capabilities", [])),
                overlap_sv=sc.get("overlap_sv"),
                overlap=float(sc.get("overlap", 0.0)),
                distinct=sc.get("distinct"),
                distinct_closest_sv=sc.get("distinct_closest_sv"),
                distinct_similarity=sc.get("distinct_similarity"),
                claim_label=sc.get("claim_label"),
                source_tier=sc.get("source_tier"),
                ers=sc.get("ers"),
                samples=list(sc.get("samples", [])),
            )
        )
    return UnscopedSubverticalsResp(
        version=v.version_id, axis=_BAND_AXIS, candidates=candidates, max=gmax
    )


_PLATFORMS_SQL = (
    "SELECT l.l3_id, l.name, v.name AS vendor, l.category, "
    "count(DISTINCT sp.subcap_id) AS subcap_count, "
    "count(DISTINCT sp.subcap_id) FILTER (WHERE left(sp.subcap_id, 2) = 'P1') AS p1, "
    "count(DISTINCT sp.subcap_id) FILTER (WHERE left(sp.subcap_id, 2) = 'P2') AS p2, "
    "count(DISTINCT sp.subcap_id) FILTER (WHERE left(sp.subcap_id, 2) = 'P3') AS p3, "
    "count(DISTINCT sp.subcap_id) FILTER (WHERE left(sp.subcap_id, 2) = 'P4') AS p4, "
    # DISTINCT delivered stories on the platform's subcaps (a story on two of them counts once)
    "count(DISTINCT scl.story_key)::int AS stories "
    "FROM {s}.l3_platform l "
    "LEFT JOIN {s}.vendor v ON v.vendor_id = l.vendor_id "
    "LEFT JOIN {s}.subcap_platform sp ON sp.l3_id = l.l3_id "
    "LEFT JOIN control.story_catalogue_link scl "
    "  ON scl.subcap_id = sp.subcap_id AND scl.version_id = :ver "
    "GROUP BY l.l3_id, l.name, v.name, l.category "
    "ORDER BY subcap_count DESC, l.l3_id"
)


@router.get("/{version}/platforms")
async def list_platforms(
    version: str, _user: dict[str, Any] = Depends(get_current_user)
) -> list[PlatformRow]:
    """L3 platforms with per-pillar subcap coverage + total stories (Platform catalog). A version
    with no platform enrichment of its own INHERITS the reference's (v7), so the page is never
    empty; story counts stay this version's own delivery."""
    v = await resolve_version(version)
    s = _schema(v)
    async with _engine().connect() as conn:
        ench_s = await _enrichment_schema(conn, s, "l3_platform")
        sql = text(_PLATFORMS_SQL.format(s=ench_s))
        rows = (await conn.execute(sql, {"ver": v.version_id})).mappings().all()
    return [PlatformRow.model_validate(dict(r)) for r in rows]


@router.get("/{version}/platforms/{l3_id}")
async def platform_detail(
    version: str, l3_id: str, _user: dict[str, Any] = Depends(get_current_user)
) -> PlatformDetail:
    v = await resolve_version(version)
    s = _schema(v)
    async with _engine().connect() as conn:
        ench_s = await _enrichment_schema(conn, s, "l3_platform")  # inherit reference when empty
        uc_s = await _enrichment_schema(conn, s, "use_case")
        meta_sql = text(
            f"SELECT l.l3_id, l.name, v.name AS vendor, l.category FROM {ench_s}.l3_platform l "
            f"LEFT JOIN {ench_s}.vendor v ON v.vendor_id = l.vendor_id WHERE l.l3_id = :lid"
        )
        subs_sql = text(
            f"SELECT sp.subcap_id AS id, left(sp.subcap_id, 2) AS pillar, s.name "
            f"FROM {ench_s}.subcap_platform sp "
            f"JOIN {ench_s}.subcap s ON s.subcap_id = sp.subcap_id "
            "WHERE sp.l3_id = :lid ORDER BY sp.subcap_id"
        )
        # top use-case archetypes on this platform's subcaps, ranked by this version's delivery
        uc_sql = text(
            "SELECT uc.archetype, count(DISTINCT scl.story_key)::int AS stories "
            f"FROM {ench_s}.subcap_platform sp "
            f"JOIN {uc_s}.use_case uc ON uc.subcap_id = sp.subcap_id "
            "LEFT JOIN control.story_catalogue_link scl "
            "  ON scl.subcap_id = sp.subcap_id AND scl.version_id = :ver "
            "WHERE sp.l3_id = :lid AND uc.archetype IS NOT NULL "
            "GROUP BY uc.archetype ORDER BY stories DESC, uc.archetype LIMIT 5"
        )
        meta = (await conn.execute(meta_sql, {"lid": l3_id})).mappings().first()
        if meta is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"platform '{l3_id}' not found")
        subs = (await conn.execute(subs_sql, {"lid": l3_id})).mappings().all()
        ucs = (await conn.execute(uc_sql, {"lid": l3_id, "ver": v.version_id})).mappings().all()
    return PlatformDetail(
        **dict(meta),
        subcaps=[PlatformSubcap.model_validate(dict(r)) for r in subs],
        use_cases=[PlatformUseCase.model_validate(dict(r)) for r in ucs],
    )


@router.get("/{version}/vendors")
async def list_vendors(
    version: str, _user: dict[str, Any] = Depends(get_current_user)
) -> list[VendorRow]:
    """Per-vendor deduped subcap coverage by pillar (the Platform catalog heatmap). Inherits the
    reference's platform enrichment when this version has none of its own."""
    v = await resolve_version(version)
    s = _schema(v)
    async with _engine().connect() as conn:
        ench_s = await _enrichment_schema(conn, s, "l3_platform")
        sql = text(
            # dvs = distinct (vendor, subcap) pairs (dedupe a subcap across a vendor's platforms);
            # vstory then counts this version's DISTINCT delivered stories over that deduped set (a
            # story on two of the vendor's subcaps counts once).
            "WITH dvs AS ("
            "  SELECT DISTINCT coalesce(v.name, 'Unattributed') AS vendor, sp.subcap_id "
            f"  FROM {ench_s}.l3_platform l "
            f"  LEFT JOIN {ench_s}.vendor v ON v.vendor_id = l.vendor_id "
            f"  JOIN {ench_s}.subcap_platform sp ON sp.l3_id = l.l3_id"
            "), vstory AS ("
            "  SELECT dvs.vendor, count(DISTINCT scl.story_key)::int AS stories FROM dvs "
            "  LEFT JOIN control.story_catalogue_link scl "
            "    ON scl.subcap_id = dvs.subcap_id AND scl.version_id = :ver "
            "  GROUP BY dvs.vendor"
            ") "
            "SELECT coalesce(v.name, 'Unattributed') AS vendor, count(DISTINCT l.l3_id) AS plats, "
            "count(DISTINCT sp.subcap_id) AS subcap_count, "
            "count(DISTINCT sp.subcap_id) FILTER (WHERE left(sp.subcap_id, 2) = 'P1') AS p1, "
            "count(DISTINCT sp.subcap_id) FILTER (WHERE left(sp.subcap_id, 2) = 'P2') AS p2, "
            "count(DISTINCT sp.subcap_id) FILTER (WHERE left(sp.subcap_id, 2) = 'P3') AS p3, "
            "count(DISTINCT sp.subcap_id) FILTER (WHERE left(sp.subcap_id, 2) = 'P4') AS p4, "
            "coalesce(vs.stories, 0) AS stories "
            f"FROM {ench_s}.l3_platform l LEFT JOIN {ench_s}.vendor v ON v.vendor_id = l.vendor_id "
            f"LEFT JOIN {ench_s}.subcap_platform sp ON sp.l3_id = l.l3_id "
            "LEFT JOIN vstory vs ON vs.vendor = coalesce(v.name, 'Unattributed') "
            "GROUP BY coalesce(v.name, 'Unattributed'), vs.stories "
            "ORDER BY subcap_count DESC, vendor"
        )
        rows = (await conn.execute(sql, {"ver": v.version_id})).mappings().all()
    return [VendorRow.model_validate(dict(r)) for r in rows]


@router.get("/{version}/vendors/{vendor}/cell")
async def vendor_cell(
    version: str,
    vendor: str,
    pillar: str = Query(...),
    _user: dict[str, Any] = Depends(get_current_user),
) -> list[VendorCellSubcap]:
    """Heatmap-cell drilldown: a vendor's platform subcaps in one pillar, delivery-ranked."""
    v = await resolve_version(version)
    s = _schema(v)
    async with _engine().connect() as conn:
        ench_s = await _enrichment_schema(conn, s, "l3_platform")
        sql = text(
            "SELECT DISTINCT sp.subcap_id AS id, sc.name, left(sp.subcap_id, 2) AS pillar, "
            "coalesce(stc.n, 0)::int AS stories "
            f"FROM {ench_s}.subcap_platform sp "
            f"JOIN {ench_s}.l3_platform l ON l.l3_id = sp.l3_id "
            f"LEFT JOIN {ench_s}.vendor v ON v.vendor_id = l.vendor_id "
            f"JOIN {ench_s}.subcap sc ON sc.subcap_id = sp.subcap_id "
            "LEFT JOIN (SELECT subcap_id, count(*) n FROM control.story_catalogue_link "
            "  WHERE version_id = :ver GROUP BY subcap_id) stc ON stc.subcap_id = sp.subcap_id "
            "WHERE coalesce(v.name, 'Unattributed') = :vendor AND left(sp.subcap_id, 2) = :pillar "
            "ORDER BY stories DESC, id LIMIT 12"
        )
        rows = (
            (await conn.execute(sql, {"ver": v.version_id, "vendor": vendor, "pillar": pillar}))
            .mappings()
            .all()
        )
    return [VendorCellSubcap.model_validate(dict(r)) for r in rows]


@router.get("/{version}/use-cases")
async def list_use_cases(
    version: str,
    pillar: str = Query(""),
    category: str = Query(""),
    archetype: str = Query(""),
    q: str = Query(""),
    sort: str = Query("delivery"),
    page: int = Query(1, ge=1),
    size: int = Query(12, ge=1, le=60),
    _user: dict[str, Any] = Depends(get_current_user),
) -> UseCasePage:
    """Actual use cases, ranked by the Jira stories MATCHED to them (Use case explorer), filterable
    by pillar / capability area (L1) / type / text. Inherits the reference's use cases when this
    version has none of its own; per-use-case delivery is the story->use-case match (not the subcap
    total), so two use cases of the same subcap no longer show the same number."""
    v = await resolve_version(version)
    s = _schema(v)
    async with _engine().connect() as conn:
        ench_s = await _enrichment_schema(conn, s, "use_case")
        return await _use_cases_page(
            conn, ench_s, pillar, category, archetype, q, v.version_id, sort, page, size
        )


# story->use-case MATCHED delivery (real per-use-case count) + the owning subcap's total for context
_UC_MATCH_JOIN = (
    "LEFT JOIN (SELECT use_case_id, count(DISTINCT story_key) n "
    "FROM control.story_use_case_link WHERE version_id = :ver GROUP BY use_case_id) ucm "
    "ON ucm.use_case_id = uc.use_case_id "
    "LEFT JOIN (SELECT subcap_id, count(*) n FROM control.story_catalogue_link "
    "WHERE version_id = :ver GROUP BY subcap_id) stc ON stc.subcap_id = uc.subcap_id"
)


async def _use_cases_page(
    conn: AsyncConnection,
    ench_s: str,
    pillar: str,
    category: str,
    archetype: str,
    q: str,
    ver: str,
    sort: str,
    page: int,
    size: int,
) -> UseCasePage:
    base = (
        f"FROM {ench_s}.use_case uc "
        f"JOIN {ench_s}.subcap sc ON sc.subcap_id = uc.subcap_id "
        f"JOIN {ench_s}.capability cap ON cap.capability_id = sc.capability_id "
        f"JOIN {ench_s}.category cat ON cat.category_id = cap.category_id "
    )
    text_q = (
        "(:q = '' OR uc.description ILIKE :qlike OR uc.name ILIKE :qlike OR sc.name ILIKE :qlike)"
    )
    where = (
        " WHERE (:pillar = '' OR left(uc.subcap_id, 2) = :pillar) "
        "AND (:category = '' OR cat.category_id = :category) "
        "AND (:archetype = '' OR uc.archetype = :archetype) AND " + text_q
    )
    # the archetype leaderboard joins the match links DIRECTLY so it counts DISTINCT matched stories
    # per archetype (scope = pillar + category); the L1-category facet drops the category filter so
    # it can drive the capability-toggle / section headers across the whole pillar.
    arch_where = (
        " WHERE (:pillar = '' OR left(uc.subcap_id, 2) = :pillar) "
        "AND (:category = '' OR cat.category_id = :category) AND uc.archetype IS NOT NULL"
    )
    cat_where = (
        " WHERE (:pillar = '' OR left(uc.subcap_id, 2) = :pillar) "
        "AND (:archetype = '' OR uc.archetype = :archetype) AND " + text_q
    )
    match_links = (
        "LEFT JOIN control.story_use_case_link sucl "
        "ON sucl.use_case_id = uc.use_case_id AND sucl.version_id = :ver "
    )
    params = {
        "pillar": pillar,
        "category": category,
        "archetype": archetype,
        "q": q,
        "qlike": f"%{q}%",
        "ver": ver,
    }
    order = "sc.name, uc.use_case_id" if sort == "alpha" else "n_stories DESC, uc.use_case_id"
    items_sql = text(
        "SELECT uc.use_case_id, uc.archetype, uc.name, uc.description, uc.subcap_id, "
        "sc.name AS subcap_name, left(uc.subcap_id, 2) AS pillar, cat.name AS category, "
        "cat.category_id, cap.name AS cluster, uc.maturity, uc.is_new, "
        "coalesce(ucm.n, 0)::int AS n_stories, coalesce(stc.n, 0)::int AS subcap_stories "
        + base
        + _UC_MATCH_JOIN
        + where
        + f" ORDER BY {order} LIMIT :size OFFSET :off"
    )
    count_sql = text("SELECT count(*) " + base + where)
    arch_sql = text(
        "SELECT uc.archetype, count(DISTINCT uc.use_case_id) AS count, "
        "count(DISTINCT sucl.story_key)::int AS n_stories "
        + base
        + match_links
        + arch_where
        + " GROUP BY uc.archetype ORDER BY n_stories DESC, count DESC, uc.archetype"
    )
    cat_sql = text(
        "SELECT cat.category_id, cat.name AS category, left(uc.subcap_id, 2) AS pillar, "
        "count(DISTINCT uc.use_case_id) AS use_cases, "
        "count(DISTINCT sucl.story_key)::int AS n_stories "
        + base
        + match_links
        + cat_where
        + " GROUP BY cat.category_id, cat.name, left(uc.subcap_id, 2) "
        + "ORDER BY n_stories DESC, cat.category_id"
    )
    total = (await conn.execute(count_sql, params)).scalar() or 0
    off = (page - 1) * size
    rows = (await conn.execute(items_sql, {**params, "size": size, "off": off})).mappings().all()
    arch = (await conn.execute(arch_sql, params)).mappings().all()
    cats = (await conn.execute(cat_sql, params)).mappings().all()
    return UseCasePage(
        total=int(total),
        page=page,
        size=size,
        items=[UseCaseRow.model_validate(dict(r)) for r in rows],
        archetypes=[ArchetypeFacet.model_validate(dict(r)) for r in arch],
        categories=[CategoryFacet.model_validate(dict(r)) for r in cats],
    )


@router.get("/{version}/use-cases/{use_case_id}/stories")
async def use_case_stories(
    version: str,
    use_case_id: str,
    page: int = Query(1, ge=1),
    size: int = Query(12, ge=1, le=100),
    _user: dict[str, Any] = Depends(get_current_user),
) -> StoryPage:
    """The Jira stories MATCHED to this use case (story->use-case), highest composite first — the
    drawer's delivering stories for the use case ITSELF, not the whole owning subcap."""
    v = await resolve_version(version)
    where = (
        "FROM control.story_use_case_link l "
        "JOIN control.story st ON st.story_key = l.story_key "
        "WHERE l.version_id = :ver AND l.use_case_id = :uid"
    )
    rows_sql = text(
        "SELECT st.story_key, st.project_key, st.summary, st.confidence_level::text, "
        "st.composite_score::float AS composite_score, st.ac_score::float AS ac_score, "
        "st.sd_score::float AS sd_score, st.story_score::float AS story_score, "
        "st.delivery_score::float AS delivery_score, st.epic_key, st.cap_name, "
        "st.category_name, st.reusability_layer, st.population, "
        "st.story_sv_code, st.tier, st.is_synthetic "
        + where
        + " ORDER BY st.composite_score DESC NULLS LAST, st.story_key LIMIT :size OFFSET :off"
    )
    params = {"ver": v.version_id, "uid": use_case_id}
    async with _engine().connect() as conn:
        total = (await conn.execute(text("SELECT count(*) " + where), params)).scalar() or 0
        rows = (
            (await conn.execute(rows_sql, {**params, "size": size, "off": (page - 1) * size}))
            .mappings()
            .all()
        )
    return StoryPage(
        total=int(total),
        page=page,
        size=size,
        items=[StoryRow.model_validate(dict(r)) for r in rows],
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


class OfferingRow(BaseModel):
    id: str
    name: str
    family: str
    summary: str
    platforms: list[str]
    n_subcaps: int
    stories: int
    pillars: dict[str, int]


class OfferingMatch(BaseModel):
    id: str
    name: str
    pillar: str
    stories: int
    score: float
    capability: str


class OfferingDetail(BaseModel):
    id: str
    name: str
    family: str
    summary: str
    platforms: list[str]
    outcomes: list[str]
    capabilities: list[str]
    n_subcaps: int
    stories: int
    pillars: dict[str, int]
    subcaps: list[OfferingMatch]


def _offering_capability(rationale: str | None) -> str:
    """The matching capability recorded by the semantic matcher (``… · capability: <cap>``)."""
    if rationale and "capability:" in rationale:
        return rationale.split("capability:", 1)[1].strip()
    return ""


@router.get("/{version}/offerings")
async def list_offerings(
    version: str, _user: dict[str, Any] = Depends(get_current_user)
) -> list[OfferingRow]:
    """The productized offerings matched into this catalogue by the semantic matcher — each with its
    matched-subcap count, delivered-story coverage and pillar spread. Offering metadata (family /
    summary / platforms) comes from the bundled GTM seed; matches + delivery from the version."""
    from app.services.offerings_match import load_offerings

    v = await resolve_version(version)
    s = _schema(v)
    seed = {o["id"]: o for o in load_offerings()}
    tally = ", ".join(
        f"count(DISTINCT os.subcap_id) FILTER (WHERE left(os.subcap_id, 2) = 'P{p}') AS p{p}"
        for p in range(1, 5)
    )
    sql = text(
        # stories = DISTINCT delivered stories on the offering's subcaps (a story on two of them is
        # counted once); n_subcaps + the pillar tally dedupe the story-join multiplication.
        "SELECT os.offering_id AS id, o.name, count(DISTINCT os.subcap_id) AS n_subcaps, "
        f"count(DISTINCT scl.story_key)::int AS stories, {tally} "
        f"FROM {s}.offering_subcap os JOIN {s}.offering o ON o.offering_id = os.offering_id "
        "LEFT JOIN control.story_catalogue_link scl "
        "  ON scl.subcap_id = os.subcap_id AND scl.version_id = :ver "
        "GROUP BY os.offering_id, o.name ORDER BY n_subcaps DESC, o.name"
    )
    async with _engine().connect() as conn:
        rows = (await conn.execute(sql, {"ver": v.version_id})).mappings().all()
    out: list[OfferingRow] = []
    for r in rows:
        sd = seed.get(str(r["id"]), {})
        out.append(
            OfferingRow(
                id=str(r["id"]),
                name=str(r["name"]),
                family=str(sd.get("family", "")),
                summary=str(sd.get("summary", "")),
                platforms=list(sd.get("platforms", [])),
                n_subcaps=int(r["n_subcaps"]),
                stories=int(r["stories"]),
                pillars={f"P{p}": int(r[f"p{p}"]) for p in range(1, 5)},
            )
        )
    return out


@router.get("/{version}/offerings/{offering_id}")
async def offering_detail(
    version: str, offering_id: str, _user: dict[str, Any] = Depends(get_current_user)
) -> OfferingDetail:
    """One offering's full drilldown: its GTM capabilities / outcomes / platforms (seed) + the
    subcaps the matcher mapped to it BY MEANING — each with its score, the matching capability (the
    trust basis) and delivered-story count, pillar-tallied. Powers the offering drawer everywhere an
    offering chip appears."""
    from app.services.offerings_match import load_offerings

    v = await resolve_version(version)
    s = _schema(v)
    seed = next((o for o in load_offerings() if o["id"] == offering_id), {})
    sql = text(
        "SELECT os.subcap_id AS id, sc.name, left(os.subcap_id, 2) AS pillar, "
        "coalesce(d.stories, 0)::int AS stories, coalesce(os.maturity_lift::float, 0) AS score, "
        "os.mapping_rationale AS rat "
        f"FROM {s}.offering_subcap os JOIN {s}.subcap sc ON sc.subcap_id = os.subcap_id "
        "LEFT JOIN (SELECT subcap_id, count(*) AS stories FROM control.story_catalogue_link "
        "WHERE version_id = :ver GROUP BY subcap_id) d ON d.subcap_id = os.subcap_id "
        "WHERE os.offering_id = :oid ORDER BY os.maturity_lift::float DESC NULLS LAST, os.subcap_id"
    )
    async with _engine().connect() as conn:
        name = (
            await conn.execute(
                text(f"SELECT name FROM {s}.offering WHERE offering_id = :oid"),
                {"oid": offering_id},
            )
        ).scalar()
        if name is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, detail=f"offering '{offering_id}' not found"
            )
        rows = (await conn.execute(sql, {"ver": v.version_id, "oid": offering_id})).mappings().all()
        # DISTINCT stories across the offering's subcaps (a story on two of them counts once) — the
        # per-subcap `stories` below stay each subcap's own count.
        distinct_stories = (
            await conn.execute(
                text(
                    "SELECT count(DISTINCT scl.story_key) "
                    f"FROM {s}.offering_subcap os "
                    "JOIN control.story_catalogue_link scl "
                    "  ON scl.subcap_id = os.subcap_id AND scl.version_id = :ver "
                    "WHERE os.offering_id = :oid"
                ),
                {"ver": v.version_id, "oid": offering_id},
            )
        ).scalar() or 0
    subs = [
        OfferingMatch(
            id=str(r["id"]),
            name=str(r["name"]),
            pillar=str(r["pillar"]),
            stories=int(r["stories"]),
            score=round(float(r["score"]), 3),
            capability=_offering_capability(r["rat"]),
        )
        for r in rows
    ]
    pillars = {f"P{p}": 0 for p in range(1, 5)}
    for sub in subs:
        pillars[sub.pillar] = pillars.get(sub.pillar, 0) + 1
    return OfferingDetail(
        id=offering_id,
        name=str(name),
        family=str(seed.get("family", "")),
        summary=str(seed.get("summary", "")),
        platforms=list(seed.get("platforms", [])),
        outcomes=list(seed.get("outcomes", [])),
        capabilities=list(seed.get("capabilities", [])),
        n_subcaps=len(subs),
        stories=int(distinct_stories),
        pillars=pillars,
        subcaps=subs,
    )
