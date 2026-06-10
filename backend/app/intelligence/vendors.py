"""Vendor scouting intelligence — the F2 ingest + typing stages (spec §F2).

Live shape (weekly Batch, through the single Gemini facade): grounded fetch over vendor newsrooms
and release notes (public sources, D6) -> per-development TYPING on the pinned flash-lite model
into the eight vendor_event_type classes, with the expected impact note, claim label, specificity
and the topic terms retrieval maps the catalogue with. Hermetic mode replays this module's
recorded fixture (real-shaped developments + recorded typings, VCR style) so the identical
map -> gate -> persist pipeline runs deterministically with zero spend.

Honesty rails recorded in the fixture: vendor newsroom material is T5 and press coverage T4 (the
tier renders, never hides); independent trade coverage lifts to T3 (the only tier the consultant
loop accepts); one development is UNTYPABLE (event_type None -> review, never mis-typed silently);
one names a vendor absent from the catalogue's vendor dimension (-> registry flag, still
ingested).
"""

from __future__ import annotations

from dataclasses import dataclass

from app.intelligence.gemini import Gemini
from app.settings import get_settings


@dataclass(frozen=True)
class RawVendorEvent:
    """One fetched vendor development, before typing."""

    vendor: str  # vendor display name (matched against cat_<v>.vendor by name)
    source: str
    source_type: str  # control.source_type enum value
    tier: str  # T5 vendor newsroom · T4 press · T3 independent trade coverage
    url: str
    published: str  # ISO date
    headline: str


@dataclass(frozen=True)
class VendorTyping:
    """The typing the flash-lite model produces: which of the eight event classes (None = the
    model could not type it -> routed to review, never guessed), what it means, and the
    meaning-probe terms for catalogue mapping."""

    event_type: str | None
    impact_note: str
    claim_label: str
    specificity: float
    topics: str
    model: str


_FIXTURE: tuple[tuple[RawVendorEvent, VendorTyping], ...] = (
    (
        RawVendorEvent(
            vendor="Salesforce",
            source="Salesforce newsroom",
            source_type="vendor",
            tier="T5",
            url="https://www.salesforce.com/news/",
            published="2026-05-27",
            headline="Agentforce 3 ships autonomous service agents with audited action trails",
        ),
        VendorTyping(
            event_type="product_launch",
            impact_note="agentic self-service capability jumps a maturity band for FSC shops",
            claim_label="HYPOTHESIS",
            specificity=0.7,
            topics="self-service deflection virtual agent assistant",
            model="hermetic-stub",
        ),
    ),
    (
        RawVendorEvent(
            vendor="nCino",
            source="nCino release notes",
            source_type="vendor",
            tier="T5",
            url="https://www.ncino.com/",
            published="2026-05-19",
            headline="Legacy commercial origination UI sunset scheduled for FY27",
        ),
        VendorTyping(
            event_type="deprecation",
            impact_note="commercial origination implementations must plan the forced migration",
            claim_label="FACT",
            specificity=0.85,
            topics="commercial loan origination underwriting workflow",
            model="hermetic-stub",
        ),
    ),
    (
        RawVendorEvent(
            vendor="nCino",
            source="American Banker",
            source_type="trade_press",
            tier="T3",
            url="https://www.americanbanker.com/",
            published="2026-05-21",
            headline="Banks weigh nCino origination sunset: migration windows tighten for FY27",
        ),
        VendorTyping(
            event_type="deprecation",
            impact_note="independent coverage corroborates the origination sunset timeline",
            claim_label="INFERENCE",
            specificity=0.8,
            topics="commercial loan origination underwriting workflow",
            model="hermetic-stub",
        ),
    ),
    (
        RawVendorEvent(
            vendor="Salesforce / MuleSoft",
            source="press wire",
            source_type="trade_press",
            tier="T4",
            url="https://www.prnewswire.com/",
            published="2026-05-12",
            headline="Native FSC connector with Salesforce Data Cloud announced",
        ),
        VendorTyping(
            event_type="partnership",
            impact_note="integration archetype simplifies the data-unification pattern",
            claim_label="INFERENCE",
            specificity=0.65,
            topics="customer data platform integration unification profile",
            model="hermetic-stub",
        ),
    ),
    (
        RawVendorEvent(
            vendor="Twilio",
            source="Twilio blog",
            source_type="vendor",
            tier="T5",
            url="https://www.twilio.com/blog",
            published="2026-05-06",
            headline="Conversations API tier restructured; volume pricing bands change in Q3",
        ),
        VendorTyping(
            event_type="pricing_change",
            impact_note="conversational-channel run-rate assumptions need re-basing",
            claim_label="INFERENCE",
            specificity=0.6,
            topics="conversational messaging channel orchestration",
            model="hermetic-stub",
        ),
    ),
    (
        RawVendorEvent(
            vendor="Okta Inc.",
            source="Reuters",
            source_type="trade_press",
            tier="T4",
            url="https://www.reuters.com/",
            published="2026-05-15",
            headline="Okta discloses support-system breach affecting enterprise tenants",
        ),
        VendorTyping(
            event_type="security_incident",
            impact_note="identity-dependent subcaps inherit a vendor-risk review item",
            claim_label="FACT",
            specificity=0.8,
            topics="identity access management authentication security",
            model="hermetic-stub",
        ),
    ),
    (
        RawVendorEvent(
            vendor="Okta Inc.",
            source="American Banker",
            source_type="trade_press",
            tier="T3",
            url="https://www.americanbanker.com/",
            published="2026-05-17",
            headline="Regional banks rotate credentials and re-baseline IAM after Okta breach",
        ),
        VendorTyping(
            event_type="security_incident",
            impact_note="independent coverage: IAM control reviews are propagating across banks",
            claim_label="INFERENCE",
            specificity=0.75,
            topics="identity access management authentication security",
            model="hermetic-stub",
        ),
    ),
    (
        RawVendorEvent(
            vendor="Databricks",
            source="Databricks customer stories",
            source_type="vendor",
            tier="T5",
            url="https://www.databricks.com/customers",
            published="2026-04-28",
            headline="Tier-1 bank consolidates feature stores on lakehouse, cuts model latency",
        ),
        VendorTyping(
            event_type="case_study",
            impact_note="reference architecture for the ML feature-management pattern",
            claim_label="HYPOTHESIS",
            specificity=0.55,
            topics="machine learning feature store model deployment",
            model="hermetic-stub",
        ),
    ),
    (
        RawVendorEvent(
            vendor="ServiceNow",
            source="Financial Times",
            source_type="trade_press",
            tier="T4",
            url="https://www.ft.com/",
            published="2026-05-23",
            headline="ServiceNow faces EU data-residency inquiry over financial-services cloud",
        ),
        VendorTyping(
            event_type="regulatory_action",
            impact_note="EU-hosted service-management workloads may need residency review",
            claim_label="INFERENCE",
            specificity=0.7,
            topics="workflow service management operations platform",
            model="hermetic-stub",
        ),
    ),
    (
        RawVendorEvent(
            vendor="Microsoft",
            source="Bloomberg",
            source_type="trade_press",
            tier="T4",
            url="https://www.bloomberg.com/",
            published="2026-05-09",
            headline="Azure financial-services lead departs to head rival cloud FSI unit",
        ),
        VendorTyping(
            event_type="executive_move",
            impact_note="roadmap continuity signal for Azure FSI commitments",
            claim_label="HYPOTHESIS",
            specificity=0.4,
            topics="cloud platform infrastructure hosting",
            model="hermetic-stub",
        ),
    ),
    # Unknown vendor (absent from the catalogue's vendor dimension): still ingested + a registry
    # flag is raised so an admin adds or maps the vendor — never silently dropped.
    (
        RawVendorEvent(
            vendor="Anthropic",
            source="Anthropic news",
            source_type="vendor",
            tier="T5",
            url="https://www.anthropic.com/news",
            published="2026-05-30",
            headline="Claude for Financial Services adds audited tool-use for banking workflows",
        ),
        VendorTyping(
            event_type="product_launch",
            impact_note="agentic tool-use with audit trails touches AI-governance subcaps",
            claim_label="HYPOTHESIS",
            specificity=0.6,
            topics="AI governance model risk management responsible AI",
            model="hermetic-stub",
        ),
    ),
    # Untypable: the model could not place it in the eight classes -> review, never mis-typed.
    (
        RawVendorEvent(
            vendor="Snowflake Inc.",
            source="Snowflake blog",
            source_type="vendor",
            tier="T5",
            url="https://www.snowflake.com/blog/",
            published="2026-05-25",
            headline="A letter from our founders on the next decade of data collaboration",
        ),
        VendorTyping(
            event_type=None,
            impact_note="reflective founder letter — no classifiable development",
            claim_label="HYPOTHESIS",
            specificity=0.2,
            topics="data collaboration sharing platform",
            model="hermetic-stub",
        ),
    ),
)

_RECORDED: dict[str, VendorTyping] = {raw.headline: typing for raw, typing in _FIXTURE}


async def fetch_events() -> list[RawVendorEvent]:
    """Ingest stage. Hermetic: the recorded fixture; live: the weekly grounded Batch fetch over
    vendor newsrooms/release notes through the one Gemini wrapper (raises until Stage 4)."""
    if get_settings().is_hermetic:
        return [raw for raw, _ in _FIXTURE]
    return await Gemini().fetch_vendor_events()


async def classify_event(raw: RawVendorEvent) -> VendorTyping:
    """Typing stage. Hermetic: the recorded typing for the fixture development (closed world —
    an unknown headline is a wiring bug, not a fallback); live: the pinned flash-lite model."""
    if get_settings().is_hermetic:
        try:
            return _RECORDED[raw.headline]
        except KeyError:
            raise LookupError(f"no recorded typing for {raw.headline!r}") from None
    return await Gemini().classify_vendor_event(raw)
