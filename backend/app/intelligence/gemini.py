"""The single Gemini wrapper (CLAUDE.md safeguard 8): every model call goes through here.

Hermetic mode returns deterministic, grounded stubs — no Vertex AI, no credentials, no spend. Live
mode (Vertex, models pinned in config/models.yaml, retry/backoff, SAFETY handling) is intentionally
not wired in hermetic-dev and raises, so a stray live call can never silently bill or ungrounded.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from app.intelligence import cost_meter, model_config
from app.resilience import retry_async
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


# Deterministic archetype buckets for a proposed use case, keyed on delivery-language cues. The
# live enrich model can name any archetype; the hermetic stub picks the closest by term signal so
# the proposal is grounded, never a guess. Ordered — the first matching cue wins.
_UC_ARCHETYPE_CUES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Automation", ("automat", "workflow", "orchestrat", "straight-through", "rpa", "batch")),
    ("Integration", ("integrat", "api", "connector", "sync", "ingest", "feed", "etl", "pipeline")),
    ("Reporting & Analytics", ("report", "dashboard", "analytic", "metric", "insight", "kpi")),
    ("Risk & Compliance", ("risk", "complian", "regulat", "audit", "kyc", "aml", "fraud")),
    ("Onboarding & Servicing", ("onboard", "servic", "account", "customer", "client", "intake")),
    ("Decisioning", ("decision", "approv", "score", "eligib", "underwrit", "assess", "triage")),
)
_UC_DEFAULT_ARCHETYPE = "Delivery Capability"


def _use_case_archetype(terms: list[str], description: str) -> str:
    """Pick a descriptive archetype for a proposed use case from its cluster's top terms + the
    drafted description (deterministic; the first matching delivery-language cue wins)."""
    haystack = " ".join(terms).lower() + " " + (description or "").lower()
    for label, cues in _UC_ARCHETYPE_CUES:
        if any(cue in haystack for cue in cues):
            return label
    return _UC_DEFAULT_ARCHETYPE


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


@dataclass(frozen=True)
class UseCaseInference:
    """An AI-proposed NEW use case, inferred from a cluster of delivered Jira stories that a
    subcap's existing use cases do NOT already cover.

    Always a HYPOTHESIS (a net-new catalogue entity, never a fact); it is gated G1-G8 and surfaced
    as a human-approved change flag, never applied automatically."""

    name: str  # human-readable proposed use-case name (highly descriptive)
    description: str  # 1-2 sentence descriptive summary of the delivered work it names
    archetype: str  # the use-case archetype bucket (e.g. Automation, Reporting, Integration)
    rationale: str  # why these stories form a coherent, currently-unmodelled use case
    claim_label: str
    model: str
    cost_usd: float


_TOKEN_RE = re.compile(r"[a-z0-9]{2,}")
_CLIENT: Any = None


def _client() -> Any:
    """Lazily build + cache the Vertex GenAI client — constructed ONLY for a live call, never at
    import or in hermetic mode, so tests and hermetic runs never touch GCP."""
    global _CLIENT
    if _CLIENT is None:
        from google import genai  # lazy: the SDK is only needed on the live path

        project, region = model_config.vertex_target()
        _CLIENT = genai.Client(vertexai=True, project=project, location=region)
    return _CLIENT


async def _retry[T](fn: Callable[[], Awaitable[T]]) -> T:
    """Run a live call under the models.yaml retry/backoff/jitter policy (safeguard 9)."""
    pol = model_config.retry_policy()
    return await retry_async(
        fn,
        retryable=pol["retryable"],
        no_retry=pol["no_retry"],
        max_attempts=pol["max_attempts"],
        base=pol["base"],
        cap=pol["cap"],
        jitter=pol["jitter"],
    )


def _gen_cost(resp: Any) -> float:
    """Estimate one generation's spend from its token usage (G8 envelope meter, not the invoice)."""
    usage = getattr(resp, "usage_metadata", None)
    total = getattr(usage, "total_token_count", None) or 0
    return round(total / 1000.0 * model_config.token_price()[0], 6)


def _truncated(resp: Any) -> bool:
    """True when the response stopped on MAX_TOKENS (so we double the budget and retry once)."""
    cands = getattr(resp, "candidates", None) or []
    if not cands:
        return False
    return str(getattr(cands[0], "finish_reason", "")).upper().endswith("MAX_TOKENS")


def _hermetic_embed(texts: list[str], dim: int) -> list[list[float]]:
    """Deterministic stand-in for gemini-embedding-001: an L2-normalised token-hash vector, so
    cosine reflects real text overlap. Lets the embeddings job, dense retrieval and semantic KG run
    end-to-end with no spend; the live model swaps in transparently (same 768-d contract)."""
    out: list[list[float]] = []
    for t in texts:
        vec = [0.0] * dim
        for tok in _TOKEN_RE.findall((t or "").lower()):
            h = int.from_bytes(hashlib.blake2b(tok.encode(), digest_size=8).digest(), "big")
            vec[h % dim] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        out.append([v / norm for v in vec])
    return out


class Gemini:
    """Model-router facade. Only ``ground`` (grounded chat) is implemented for the hermetic slice;
    classify / enrich / match / synthesize / adversarial extend this against the pinned models."""

    def __init__(self) -> None:
        self._settings = get_settings()

    async def ground(self, question: str, evidence: list[dict[str, Any]]) -> GroundedAnswer:
        """Answer ``question`` using ONLY ``evidence`` (retrieved rows), never model memory. Live:
        the pinned ``ground`` model; degrades to the deterministic stub when the budget envelope is
        spent (G8) so chat never hard-fails."""
        if self._settings.is_hermetic or await cost_meter.over_throttle():
            return self._hermetic_ground(question, evidence)
        return await self._ground_live(question, evidence)

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
        meter. Hermetic mode (and a spent budget envelope) returns a deterministic, capability-
        grounded provisional name (no Vertex, no spend) so the gated proposal stays functional."""
        if self._settings.is_hermetic or await cost_meter.over_throttle():
            return self._hermetic_infer_subvertical(fingerprint)
        return await self._infer_subvertical_live(fingerprint)

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

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed ``texts`` into the shared vector(768) space (gemini-embedding-001). Hermetic — and
        a spent budget envelope — use the deterministic token-hash stub (no spend); the embeddings
        job records the live batch cost."""
        model, dim = model_config.embedding_model()
        if self._settings.is_hermetic or await cost_meter.over_throttle():
            return _hermetic_embed(texts, dim)
        return await self._embed_live(texts, model, dim)

    async def _embed_live(self, texts: list[str], model: str, dim: int) -> list[list[float]]:
        from google.genai import types

        cfg = types.EmbedContentConfig(output_dimensionality=dim)
        resp = await _retry(
            lambda: _client().aio.models.embed_content(model=model, contents=texts, config=cfg)
        )
        return [[float(x) for x in e.values] for e in (getattr(resp, "embeddings", None) or [])]

    async def _ground_live(self, question: str, evidence: list[dict[str, Any]]) -> GroundedAnswer:
        model = model_config.model_for("ground")
        ev = "\n".join(
            f"- {e.get('name')} ({e.get('subcap_id')}): {e.get('description', '')}"
            for e in evidence[:8]
        )
        system = (
            "You are a capability-catalogue assistant. Answer ONLY from the provided evidence. If "
            "the evidence does not support an answer, say so plainly. Never use outside knowledge."
        )
        user = f"Question: {question}\n\nEvidence:\n{ev}"
        text_out, cost = await self._generate(model, system, user)
        if not text_out:  # SAFETY block / empty -> safe, non-fabricated answer
            return GroundedAnswer(
                text="No grounded answer is available from the catalogue for this question.",
                claim_label="HYPOTHESIS",
                model=model,
                cost_usd=cost,
            )
        return GroundedAnswer(text=text_out, claim_label="FACT", model=model, cost_usd=cost)

    async def _infer_subvertical_live(self, fingerprint: dict[str, Any]) -> SubverticalInference:
        model = model_config.model_for("enrich")
        clients = list(fingerprint.get("clients", []))
        caps = "; ".join(
            f"{c['name']} ({c['n']})" for c in fingerprint.get("top_capabilities", [])[:6]
        )
        samples = " | ".join(fingerprint.get("sample_summaries", [])[:5])
        system = (
            "You name a NEW financial-services subvertical from a cluster of delivered work. "
            'Return ONLY JSON {"name": "<short industry label>", "rationale": "<1-2 sentences>"}. '
            "Ground the name in the capabilities and sample work; invent nothing."
        )
        user = (
            f"Capabilities: {caps}\nPillars: {', '.join(fingerprint.get('pillars', []))}\n"
            f"Sample work: {samples}\nStory count: {fingerprint.get('story_count', 0)}"
        )
        text_out, cost = await self._generate(model, system, user, as_json=True)
        try:
            data = json.loads(text_out)
            name = str(data["name"]).strip()
            rationale = str(data.get("rationale", "")).strip()
        except (json.JSONDecodeError, KeyError, TypeError):
            return self._hermetic_infer_subvertical(fingerprint)  # bad parse -> never crash
        return SubverticalInference(
            code=_provisional_sv_code(name, clients),
            name=name or "Cross-pillar delivery",
            rationale=rationale,
            claim_label="HYPOTHESIS",
            model=model,
            cost_usd=cost,
        )

    async def infer_use_case_name(self, fingerprint: dict[str, Any]) -> UseCaseInference:
        """Name + describe a candidate NEW use case from a cluster of delivered Jira stories that a
        subcap's EXISTING use cases do not already cover.

        ``fingerprint`` carries only stored, grounded facts: ``subcap_id``, ``subcap_name``,
        ``pillar``, ``story_count``, ``top_terms`` (the cluster's discriminating tokens),
        ``sample_summaries`` (representative story text) and ``overlap_score`` (its cosine to the
        nearest existing use case, below the merge bar by construction). Live mode drafts a highly
        descriptive name + 1-2 sentence description on the pinned *enrich* model (models.yaml)
        with retry/backoff, MAX_TOKENS->chunk and SAFETY->review, its spend
        governed by the G8 budget gate + the cost meter. Hermetic mode (and a spent budget envelope)
        return a deterministic, delivery-grounded proposal (no Vertex, no spend) so the gated
        proposal stays functional in any LLM_MODE."""
        if self._settings.is_hermetic or await cost_meter.over_throttle():
            return self._hermetic_infer_use_case(fingerprint)
        return await self._infer_use_case_live(fingerprint)

    @staticmethod
    def _hermetic_infer_use_case(fingerprint: dict[str, Any]) -> UseCaseInference:
        """Deterministic stand-in for the enrich model: derive a descriptive use-case name +
        archetype + 1-2 sentence description from the cluster's top terms + its subcap. Names the
        delivered work honestly (the live model upgrades the prose); always a HYPOTHESIS."""
        terms = [str(t) for t in fingerprint.get("top_terms", []) if str(t).strip()]
        subcap_name = str(fingerprint.get("subcap_name") or "").strip()
        subcap_id = str(fingerprint.get("subcap_id") or "").strip()
        pillar = str(fingerprint.get("pillar") or "").strip()
        story_count = int(fingerprint.get("story_count", 0))
        samples = [str(s) for s in fingerprint.get("sample_summaries", []) if str(s).strip()]
        overlap = float(fingerprint.get("overlap_score", 0.0))

        # A descriptive name: the two leading discriminating terms of the cluster, title-cased, tied
        # to the subcap they were delivered under (so it never collides with a sibling use case).
        lead = [t.title() for t in terms[:2]] or ["Emerging"]
        theme = " ".join(dict.fromkeys(lead))  # dedupe while preserving order
        base = subcap_name or subcap_id or "delivery"
        name = f"{theme} for {base}" if base else theme
        term_txt = ", ".join(terms[:6]) or "recurring delivery themes"
        sample_txt = samples[0][:160] if samples else "recurring delivered stories"
        description = (
            f"Delivered work under {base} concentrating on {term_txt}, not yet captured by an "
            f"existing use case. Representative story: {sample_txt}."
        )
        archetype = _use_case_archetype(terms, description)
        overlap_txt = (
            f"its closest existing use case is only {overlap:.0%} similar (below the merge bar), "
            "so this is an uncovered use case, not a duplicate"
            if overlap
            else "no existing use case of the subcap covers it"
        )
        rationale = (
            f"{story_count} delivered Jira stories under {base}"
            + (f" (pillar {pillar})" if pillar else "")
            + f" cluster on {term_txt}; {overlap_txt}. Provisional delivery-derived name — a "
            "reviewer (or the live model) refines it to the canonical use-case label."
        )
        return UseCaseInference(
            name=name,
            description=description,
            archetype=archetype,
            rationale=rationale,
            claim_label="HYPOTHESIS",
            model="hermetic-stub",
            cost_usd=0.0,
        )

    async def _infer_use_case_live(self, fingerprint: dict[str, Any]) -> UseCaseInference:
        model = model_config.model_for("enrich")
        terms = [str(t) for t in fingerprint.get("top_terms", []) if str(t).strip()]
        subcap_name = str(fingerprint.get("subcap_name") or "").strip()
        samples = " | ".join(str(s) for s in fingerprint.get("sample_summaries", [])[:5])
        system = (
            "You name a NEW, highly-descriptive use case from a cluster of delivered work under "
            "one capability. Return ONLY JSON "
            '{"name": "<short descriptive title>", "description": "<1-2 sentences>", '
            '"archetype": "<one of: Automation, Integration, Reporting & Analytics, '
            'Risk & Compliance, Onboarding & Servicing, Decisioning, Delivery Capability>"}. '
            "Ground the name and description in the terms and sample work; invent nothing."
        )
        user = (
            f"Capability: {subcap_name}\nTop terms: {', '.join(terms[:8])}\n"
            f"Sample work: {samples}\nStory count: {fingerprint.get('story_count', 0)}"
        )
        text_out, cost = await self._generate(model, system, user, as_json=True)
        try:
            data = json.loads(text_out)
            name = str(data["name"]).strip()
            description = str(data.get("description", "")).strip()
            archetype = str(data.get("archetype", "")).strip()
        except (json.JSONDecodeError, KeyError, TypeError):
            return self._hermetic_infer_use_case(fingerprint)  # bad parse -> never crash
        return UseCaseInference(
            name=name or f"Emerging use case for {subcap_name or 'the subcap'}",
            description=description or f"Delivered work under {subcap_name} not yet catalogued.",
            archetype=archetype or _use_case_archetype(terms, description),
            rationale=description or "Named by the live enrich model from the delivered cluster.",
            claim_label="HYPOTHESIS",
            model=model,
            cost_usd=cost,
        )

    async def _generate(
        self, model: str, system: str, user: str, *, as_json: bool = False
    ) -> tuple[str, float]:
        """One grounded generation under retry; doubles the token budget once on MAX_TOKENS (the
        ``on_max_tokens: double_and_retry`` policy). Returns (text, estimated_cost); empty text on a
        SAFETY block so callers degrade to a safe, non-fabricated response."""
        from google.genai import types

        max_tok = model_config.max_output_tokens()

        def _cfg(mt: int) -> Any:
            kwargs: dict[str, Any] = {
                "system_instruction": system,
                "max_output_tokens": mt,
                "temperature": 0.2,
            }
            if as_json:
                kwargs["response_mime_type"] = "application/json"
            return types.GenerateContentConfig(**kwargs)

        async def _call(mt: int) -> Any:
            return await _client().aio.models.generate_content(
                model=model, contents=user, config=_cfg(mt)
            )

        resp = await _retry(lambda: _call(max_tok))
        text_out = str(getattr(resp, "text", "") or "").strip()
        if not text_out and _truncated(resp):
            resp = await _retry(lambda: _call(max_tok * 2))
            text_out = str(getattr(resp, "text", "") or "").strip()
        return text_out, _gen_cost(resp)
