"""SOW corpus access (C1) — hermetic recorded fixture behind the same interface a live ingest uses.

In hermetic mode `fetch_sows()` replays this module's recorded fixture: a small, pre-redacted set
of statements of work whose `account_key` values are REAL project keys from the canonical Jira
corpus (BAYPORT, NAVEBANK, FSB, MF, BCFSC, FP2 — top delivery accounts), so client entity
resolution (FR-19) joins real delivery. Scope clauses are phrased against capabilities that exist
in the v7 catalogue, so matching runs the REAL retrieval path — nothing is hand-mapped. The live
path (Drive/SharePoint pull + DLP redaction BEFORE any model sees a byte) slots behind the same
contract in Stage 4; a stray live call raises rather than silently spending.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.settings import get_settings


@dataclass(frozen=True)
class RawScopeItem:
    ordinal: int
    clause: str


@dataclass(frozen=True)
class RawSow:
    account_key: str  # = control.story.project_key (entity-resolution key)
    account_name: str
    title: str
    sv_code: str
    signed_date: str  # ISO date
    items: tuple[RawScopeItem, ...]


def _items(*clauses: str) -> tuple[RawScopeItem, ...]:
    return tuple(RawScopeItem(i + 1, c) for i, c in enumerate(clauses))


_FIXTURE: tuple[RawSow, ...] = (
    RawSow(
        account_key="BAYPORT",
        account_name="BAYPORT",
        title="Member 360 & Service Modernization SOW",
        sv_code="CU",
        signed_date="2025-11-14",
        items=_items(
            "Implement identity resolution and a unified customer profile "
            "across service channels.",
            "Deploy case intake and classification with automated routing "
            "for member service requests.",
            "Stand up real-time API development and integration patterns " "for core connectivity.",
            "Establish a member segmentation strategy with actionable embedded analytics.",
            "Quarterly governance cadence and steering committee for delivery oversight.",
        ),
    ),
    RawSow(
        account_key="NAVEBANK",
        account_name="NAVEBANK",
        title="Digital Lending Acceleration SOW",
        sv_code="CL",
        signed_date="2026-01-22",
        items=_items(
            "Configure commercial loan servicing workflows with stage and "
            "milestone configuration.",
            "Automate loan document generation and collateral tracking "
            "across the origination chain.",
            "Implement credit decisioning support with policy-aligned " "eligibility transparency.",
            "Deliver operational risk framework alignment for the lending value chain.",
        ),
    ),
    RawSow(
        account_key="FSB",
        account_name="FSB",
        title="Service Console Replatform SOW",
        sv_code="BK",
        signed_date="2025-09-03",
        items=_items(
            "Migrate assisted service to a unified agent console with knowledge surfacing.",
            "Introduce self-service flows for routine account maintenance and payments.",
            "Voice of customer capture with closed-loop feedback into service operations.",
        ),
    ),
    RawSow(
        account_key="MF",
        account_name="MF",
        title="Data & AI Enablement Phase 1 SOW",
        sv_code="WM",
        signed_date="2026-02-10",
        items=_items(
            "Establish prompt management and engineering practices for "
            "generative AI assistants.",
            "Deploy GenAI model risk management controls aligned to " "supervisory expectations.",
            "Build embedded analytics with actionable insights for advisor workflows.",
            "Implement batch and bulk integration patterns for the data platform.",
        ),
    ),
    RawSow(
        account_key="BCFSC",
        account_name="BCFSC",
        title="Process Automation Wave 2 SOW",
        sv_code="CU",
        signed_date="2025-12-05",
        items=_items(
            "Automate exception handling and back-office operations for account servicing.",
            "Workflow orchestration for onboarding with automated KYC document collection.",
            "Robotic process automation retirement and migration to platform-native flows.",
        ),
    ),
    RawSow(
        account_key="FP2",
        account_name="FP2",
        title="Platform Foundation & Integration SOW",
        sv_code="IC",
        signed_date="2026-03-18",
        items=_items(
            "Real-time API development for policy administration system connectivity.",
            "Event-driven integration architecture with streaming data pipelines.",
            "Digital strategy document refresh and capability roadmap alignment.",
            "Establish data governance framework with stewardship and quality controls.",
        ),
    ),
)


def fetch_sows() -> tuple[RawSow, ...]:
    """The SOW corpus for ingestion. Hermetic replays the recorded fixture; live raises until the
    Drive/DLP pull is wired in Stage 4 (a stray call must never silently read client documents)."""
    settings = get_settings()
    if settings.llm_mode == "hermetic":
        return _FIXTURE
    raise NotImplementedError(
        "live SOW ingestion (Drive pull + DLP redaction) is Stage 4; "
        "run with LLM_MODE=hermetic for the recorded corpus"
    )
