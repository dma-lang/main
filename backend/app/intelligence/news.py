"""News scouting intelligence — stages 1-2 of the D1 pipeline (spec §17.5).

Live shape (weekly Batch, through the single Gemini facade): grounded fetch (Google Search
grounding; public sources only, D6) -> structured extract/classify on the pinned classify model
(expected catalogue impact, claim label, specificity, and the TOPIC terms retrieval probes the
catalogue with — mapping is by meaning, not by the headline's literal keywords). Hermetic mode
replays this module's recorded fixture (real public items + their recorded enrichments, VCR
style), so the identical downstream map -> gate -> persist pipeline runs deterministically with
zero spend. The service layer (services/evidence.py) never reads fixture annotations directly —
it consumes the same two contracts live mode produces.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.intelligence.gemini import Gemini
from app.settings import get_settings


@dataclass(frozen=True)
class RawNewsItem:
    """Stage-1 fetch output: one public-source item, before any model enrichment."""

    source: str
    source_type: str  # control.source_type enum value
    tier: str  # T1 (regulator) .. T5
    url: str
    published: str  # ISO date
    headline: str


@dataclass(frozen=True)
class NewsEnrichment:
    """Stage-2 classify output: what the item MEANS for the catalogue. ``claim_label`` is the
    pre-grounding label — the pipeline downgrades it one notch when catalogue grounding is weak
    (G5: never assert more than the evidence supports). ``topics`` are the meaning-probe terms
    the retrieval layer maps with."""

    impact: str  # control.catalogue_impact enum value
    impact_note: str
    claim_label: str  # FACT | INFERENCE | HYPOTHESIS
    specificity: float
    topics: str
    model: str


# The recorded fixture: real public-source items + the enrichment the classify model would
# produce. Two entries exist to prove the robustness rails end-to-end: the American Banker item
# grounds WEAKLY (every catalogue match lands between the relevance floor and the strong-
# grounding bar -> label downgraded, scores scaled down) and the Reuters sports-media item is
# OFF-CATALOGUE (no match above the floor -> G5 fail -> queued to Change Flags, never mapped).
_FIXTURE: tuple[tuple[RawNewsItem, NewsEnrichment], ...] = (
    (
        RawNewsItem(
            source="OCC newsroom",
            source_type="regulator",
            tier="T1",
            url="https://www.occ.gov/news-issuances",
            published="2026-05-18",
            headline=(
                "OCC issues 2026 guidance on real-time credit decisioning and model governance"
            ),
        ),
        NewsEnrichment(
            impact="descriptor_revision",
            impact_note="M3 real-time decisioning descriptor reads as out of date",
            claim_label="FACT",
            specificity=0.9,
            topics="real-time credit decisioning model governance risk",
            model="hermetic-stub",
        ),
    ),
    (
        RawNewsItem(
            source="Celent",
            source_type="analyst",
            tier="T2",
            url="https://www.celent.com/insights",
            published="2026-04-22",
            headline="Celent: agentic service deflection now a board-level KPI at top-50 banks",
        ),
        NewsEnrichment(
            impact="new_use_case",
            impact_note="agentic-deflection archetype for self-service subcaps",
            claim_label="INFERENCE",
            specificity=0.75,
            topics="self-service deflection virtual agent assistant",
            model="hermetic-stub",
        ),
    ),
    (
        RawNewsItem(
            source="FinCEN",
            source_type="regulator",
            tier="T1",
            url="https://www.fincen.gov/news",
            published="2026-04-09",
            headline="FinCEN finalizes beneficial-ownership data-sharing rule, effective 2027",
        ),
        NewsEnrichment(
            impact="net_new_subcap",
            impact_note="beneficial-ownership surveillance not yet in the catalogue",
            claim_label="FACT",
            specificity=0.85,
            topics="beneficial ownership due diligence compliance monitoring KYC",
            model="hermetic-stub",
        ),
    ),
    (
        RawNewsItem(
            source="TechCrunch",
            source_type="trade_press",
            tier="T3",
            url="https://techcrunch.com/category/fintech/",
            published="2026-03-12",
            headline="Fintechs pilot stablecoin rails for cross-border SMB payments",
        ),
        NewsEnrichment(
            impact="watchlist",
            impact_note="monitored as an emerging trend, no catalogue edit warranted",
            claim_label="HYPOTHESIS",
            specificity=0.5,
            topics="cross-border payments rails settlement",
            model="hermetic-stub",
        ),
    ),
    (
        RawNewsItem(
            source="Federal Reserve",
            source_type="regulator",
            tier="T1",
            url="https://www.federalreserve.gov/newsevents.htm",
            published="2026-05-29",
            headline="Fed publishes supervisory expectations for generative-AI model risk",
        ),
        NewsEnrichment(
            impact="descriptor_revision",
            impact_note="model-risk descriptors predate generative-AI supervisory language",
            claim_label="FACT",
            specificity=0.8,
            topics="AI governance model risk management responsible AI",
            model="hermetic-stub",
        ),
    ),
    (
        RawNewsItem(
            source="Forrester",
            source_type="analyst",
            tier="T2",
            url="https://www.forrester.com/research",
            published="2026-03-30",
            headline=(
                "Forrester: standalone marketing automation suites absorbed into CDP platforms"
            ),
        ),
        NewsEnrichment(
            impact="retire_candidate",
            impact_note="standalone campaign tooling reading as superseded by CDP-led suites",
            claim_label="INFERENCE",
            specificity=0.7,
            topics="marketing automation platform campaign journeys",
            model="hermetic-stub",
        ),
    ),
    (
        RawNewsItem(
            source="American Banker",
            source_type="trade_press",
            tier="T3",
            url="https://www.americanbanker.com/",
            published="2026-05-11",
            headline="Banks rethink branch staffing models as lobby traffic keeps falling",
        ),
        NewsEnrichment(
            impact="watchlist",
            impact_note=(
                "diffuse workforce/channel signal — no single subcap clearly implicated yet"
            ),
            claim_label="INFERENCE",
            specificity=0.45,
            topics="branch staffing workforce operations efficiency",
            model="hermetic-stub",
        ),
    ),
    (
        RawNewsItem(
            source="Reuters",
            source_type="trade_press",
            tier="T3",
            url="https://www.reuters.com/",
            published="2026-05-25",
            headline="Streaming platforms escalate bidding war for live sports media rights",
        ),
        NewsEnrichment(
            impact="watchlist",
            impact_note="media-sector story with no financial-services capability implication",
            claim_label="HYPOTHESIS",
            specificity=0.35,
            topics="streaming sports media rights entertainment",
            model="hermetic-stub",
        ),
    ),
)

_RECORDED: dict[str, NewsEnrichment] = {raw.headline: enr for raw, enr in _FIXTURE}


async def fetch_items() -> list[RawNewsItem]:
    """Stage 1. Hermetic: the recorded fixture; live: the weekly grounded-search Batch fetch
    through the one Gemini wrapper (raises until Stage 4 wires Vertex — never silent spend)."""
    if get_settings().is_hermetic:
        return [raw for raw, _ in _FIXTURE]
    return await Gemini().fetch_news()


async def enrich(raw: RawNewsItem) -> NewsEnrichment:
    """Stage 2. Hermetic: the recorded enrichment for the fixture item (closed world — an
    unknown headline is a wiring bug, not a fallback); live: the pinned classify model."""
    if get_settings().is_hermetic:
        try:
            return _RECORDED[raw.headline]
        except KeyError:
            raise LookupError(f"no recorded enrichment for {raw.headline!r}") from None
    return await Gemini().classify_news(raw)
