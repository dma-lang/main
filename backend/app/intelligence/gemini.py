"""The single Gemini wrapper (CLAUDE.md safeguard 8): every model call goes through here.

Hermetic mode returns deterministic, grounded stubs — no Vertex AI, no credentials, no spend. Live
mode (Vertex, models pinned in config/models.yaml, retry/backoff, SAFETY handling) is intentionally
not wired in hermetic-dev and raises, so a stray live call can never silently bill or ungrounded.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.settings import get_settings


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
