"""The single Gemini wrapper (CLAUDE.md safeguard 8): every model call goes through here.

Hermetic mode returns deterministic, grounded stubs — no Vertex AI, no credentials, no spend. Live
mode (Vertex, models pinned in config/models.yaml, retry/backoff, SAFETY handling) is intentionally
not wired in hermetic-dev and raises, so a stray live call can never silently bill or ungrounded.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from app.settings import get_settings

# the nine modelled subverticals — a provisional code for a NEW one must never collide with these
_MODELLED_SV = {"RB", "CU", "CL", "CIB", "FC", "AM", "RIA", "IC", "IB"}


def _provisional_sv_code(name: str, clients: list[str]) -> str:
    """Short, uppercase, collision-free provisional code for a proposed subvertical (initials of
    the name, falling back to the client key), suffixed if it would clash with a modelled SV."""
    base = "".join(w[0] for w in re.findall(r"[A-Za-z]+", name))[:4].upper()
    if not base:
        base = (clients[0] if clients else "NV")[:4].upper()
    code, i = base, 1
    while code in _MODELLED_SV:
        code, i = f"{base}{i}", i + 1
    return code


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


@dataclass(frozen=True)
class SubverticalInference:
    """An AI-proposed NEW subvertical, inferred from a cluster of unscoped Jira delivery.

    Always a HYPOTHESIS (a net-new entity, never a fact); it is gated G1-G8 and surfaced as a
    human-approved change flag, never applied automatically."""

    code: str  # provisional subvertical code (collision-checked against the 9 modelled SVs)
    name: str  # human-readable proposed subvertical name
    rationale: str  # why these stories form a coherent, distinct, currently-unmodelled subvertical
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

    async def infer_subvertical_name(self, fingerprint: dict[str, Any]) -> SubverticalInference:
        """Name a candidate NEW subvertical from a cluster of unscoped Jira stories.

        ``fingerprint`` carries only stored, grounded facts: ``clients`` (project keys),
        ``story_count``, ``pillars``, ``top_capabilities`` ([{name, n}, …]),
        ``sample_summaries``, and the overlap check vs the 9 modelled subverticals
        (``overlap_sv``/``overlap``). Live mode names + refines the industry classification on the
        pinned *enrich* model (config/models.yaml: gemini-3.5-flash GA) with retry/backoff,
        MAX_TOKENS->chunk and SAFETY->review, its spend governed by the G8 budget gate + the cost
        meter. Hermetic mode returns a deterministic, capability-grounded provisional name (no
        Vertex, no spend) so the gated proposal is fully functional before live wiring lands."""
        if self._settings.is_hermetic:
            return self._hermetic_infer_subvertical(fingerprint)
        raise NotImplementedError("live Vertex AI is not wired in hermetic-dev")

    @staticmethod
    def _hermetic_infer_subvertical(fingerprint: dict[str, Any]) -> SubverticalInference:
        """Deterministic stand-in for the enrich model: derive a provisional subvertical from the
        cluster's dominant capabilities + clients. Names the capability profile honestly (the
        industry label is what the live model upgrades it to); always a HYPOTHESIS."""
        caps = [c["name"] for c in fingerprint.get("top_capabilities", []) if c.get("name")]
        clients = fingerprint.get("clients", [])
        pillars = fingerprint.get("pillars", [])
        story_count = int(fingerprint.get("story_count", 0))
        overlap_sv = fingerprint.get("overlap_sv")
        overlap = float(fingerprint.get("overlap", 0.0))

        def _short(name: str) -> str:
            # lead theme of a capability label: drop the generic "Sub-Vertical " prefix + trailing
            # "& …"/"/ …" detail so the name reads as a theme, not the catalogue's bucket label
            n = re.sub(r"(?i)^sub-?vertical\s+", "", name.strip())
            return re.split(r"\s*[&/]\s*", n)[0] if n else n

        lead = [_short(c) for c in caps[:2]] or ["Cross-pillar delivery"]
        name = " & ".join(dict.fromkeys(lead))  # dedupe while preserving order
        code = _provisional_sv_code(name, clients)
        client_txt = ", ".join(clients) if clients else "an unrecognised client"
        top4 = fingerprint.get("top_capabilities", [])[:4]
        cap_txt = "; ".join(f"{c['name']} ({c['n']})" for c in top4)
        overlap_txt = (
            f"the client is only {overlap:.0%} classified as its closest modelled subvertical "
            f"({overlap_sv}), below the merge threshold, so this is a distinct, unmodelled segment"
            if overlap_sv
            else "the client delivers nothing under any of the nine modelled subverticals"
        )
        rationale = (
            f"{story_count} unscoped Jira stories from {client_txt} concentrate in {cap_txt}, "
            f"spanning pillars {', '.join(pillars)}. {overlap_txt}. Provisional capability-derived "
            f"name — a reviewer (or the live model) refines it to the industry label."
        )
        return SubverticalInference(
            code=code,
            name=name,
            rationale=rationale,
            claim_label="HYPOTHESIS",
            model="hermetic-stub",
            cost_usd=0.0,
        )

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
