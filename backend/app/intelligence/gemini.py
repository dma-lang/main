"""The single Gemini wrapper (CLAUDE.md safeguard 8): every model call goes through here.

Hermetic mode returns deterministic, grounded stubs — no Vertex AI, no credentials, no spend. Live
mode (Vertex, models pinned in config/models.yaml, retry/backoff, SAFETY handling) is intentionally
not wired in hermetic-dev and raises, so a stray live call can never silently bill or ungrounded.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from app.settings import get_settings

if TYPE_CHECKING:  # type hints only — news/benchmarks/vendors modules import Gemini at runtime
    from app.intelligence.benchmarks import AdversaryVerdict, RawBenchmark
    from app.intelligence.news import NewsEnrichment, RawNewsItem
    from app.intelligence.vendors import RawVendorEvent, VendorTyping


@dataclass(frozen=True)
class GroundedAnswer:
    text: str
    claim_label: str
    model: str
    cost_usd: float


class Gemini:
    """Model-router facade. Only ``ground`` (grounded chat) is implemented for the hermetic slice;
    classify / enrich / match / synthesize / adversarial extend this against the pinned models."""

    def __init__(self) -> None:
        self._settings = get_settings()

    async def ground(self, question: str, evidence: list[dict[str, Any]]) -> GroundedAnswer:
        """Answer ``question`` using ONLY ``evidence`` (retrieved rows), never model memory."""
        if self._settings.is_hermetic:
            return self._hermetic_ground(question, evidence)
        raise NotImplementedError("live Vertex AI is not wired in hermetic-dev")

    async def fetch_news(self) -> list[RawNewsItem]:
        """Stage-1 news fetch: the weekly grounded-search Batch call (Google Search grounding;
        public sources only, D6). Hermetic mode never reaches this — intelligence/news.py
        replays its recorded fixture — so a stray call can never silently spend."""
        if self._settings.is_hermetic:
            raise RuntimeError("hermetic news fetch is the recorded fixture (intelligence.news)")
        raise NotImplementedError("live Vertex AI is not wired in hermetic-dev")

    async def classify_news(self, item: RawNewsItem) -> NewsEnrichment:
        """Stage-2 enrich/classify one fetched item — expected catalogue impact, claim label,
        specificity, topic terms — on the pinned classify model (config/models.yaml). Hermetic
        mode replays the recorded enrichment in intelligence/news.py instead."""
        if self._settings.is_hermetic:
            raise RuntimeError("hermetic enrichment is recorded in intelligence.news")
        raise NotImplementedError("live Vertex AI is not wired in hermetic-dev")

    async def fetch_benchmarks(self) -> list[RawBenchmark]:
        """D4 ingest: the monthly grounded Batch fetch of curated public benchmark datasets (T2).
        Hermetic mode never reaches this — intelligence/benchmarks.py replays its recorded
        fixture — so a stray call can never silently spend."""
        if self._settings.is_hermetic:
            raise RuntimeError(
                "hermetic benchmark fetch is the recorded fixture (intelligence.benchmarks)"
            )
        raise NotImplementedError("live Vertex AI is not wired in hermetic-dev")

    async def adversary_review(self, raw: RawBenchmark) -> AdversaryVerdict:
        """D4 adversarial review on the pinned synthesis/adversarial model: argues the opposite,
        surfaces missing evidence and overreach; the verdict chip is BENCHMARK / INDICATIVE /
        EXPLORATORY. Hermetic mode replays the recorded verdict in intelligence/benchmarks.py.
        A live 429/timeout yields NO verdict — the read model renders "pending", never a guess."""
        if self._settings.is_hermetic:
            raise RuntimeError("hermetic verdicts are recorded in intelligence.benchmarks")
        raise NotImplementedError("live Vertex AI is not wired in hermetic-dev")

    async def fetch_vendor_events(self) -> list[RawVendorEvent]:
        """F2 ingest: the weekly grounded Batch fetch over vendor newsrooms / release notes.
        Hermetic mode never reaches this — intelligence/vendors.py replays its recorded
        fixture — so a stray call can never silently spend."""
        if self._settings.is_hermetic:
            raise RuntimeError(
                "hermetic vendor fetch is the recorded fixture (intelligence.vendors)"
            )
        raise NotImplementedError("live Vertex AI is not wired in hermetic-dev")

    async def classify_vendor_event(self, raw: RawVendorEvent) -> VendorTyping:
        """F2 typing on the pinned flash-lite model: one of the eight vendor_event_type classes
        (or None when untypable -> review, never a guess), the impact note, claim label and the
        topic terms. Hermetic mode replays the recorded typing in intelligence/vendors.py."""
        if self._settings.is_hermetic:
            raise RuntimeError("hermetic typings are recorded in intelligence.vendors")
        raise NotImplementedError("live Vertex AI is not wired in hermetic-dev")

    @staticmethod
    def _hermetic_ground(question: str, evidence: list[dict[str, Any]]) -> GroundedAnswer:
        top = evidence[:3]
        lead = top[0]["name"] if top else "the catalogue"
        related = "; ".join(f"{e['name']} ({e['subcap_id']})" for e in top)
        text = (
            f"Grounded in {len(evidence)} capabilities from the active catalogue, the closest "
            f"match is {lead}. Related capabilities: {related}. Every claim below is "
            f"citation-backed — open the reasoning chain to see the retrieval and gate checks."
        )
        return GroundedAnswer(text=text, claim_label="FACT", model="hermetic-stub", cost_usd=0.0)
