"""Gemini live path with a MONKEYPATCHED Vertex client — no network, no spend. Proves the wrapper
builds the prompt, parses the response, records cost, and degrades safely. LLM_MODE is forced live
on the instance; the genai client and cost_meter.over_throttle are stubbed."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from app.intelligence import cost_meter, gemini
from app.intelligence.gemini import Gemini


class _Models:
    def __init__(self, text: str) -> None:
        self._text = text

    async def generate_content(self, model: str, contents: Any, config: Any) -> Any:
        return SimpleNamespace(
            text=self._text,
            usage_metadata=SimpleNamespace(total_token_count=120),
            candidates=[],
        )

    async def embed_content(self, model: str, contents: Any, config: Any) -> Any:
        return SimpleNamespace(embeddings=[SimpleNamespace(values=[0.01] * 768) for _ in contents])


def _wire(monkeypatch: pytest.MonkeyPatch, text: str = "A grounded answer.") -> Gemini:
    client = SimpleNamespace(aio=SimpleNamespace(models=_Models(text)))
    monkeypatch.setattr(gemini, "_client", lambda: client)

    async def _no_throttle() -> bool:
        return False

    monkeypatch.setattr(cost_meter, "over_throttle", _no_throttle)
    g = Gemini()
    monkeypatch.setattr(g, "_settings", SimpleNamespace(is_hermetic=False))
    return g


def test_ground_live_parses_and_costs(monkeypatch: pytest.MonkeyPatch) -> None:
    g = _wire(monkeypatch, "Onboarding maps to P2C1.1.1.")
    ev = [{"name": "Onboarding", "subcap_id": "P2C1.1.1", "description": "x"}]
    ans = asyncio.run(g.ground("what is onboarding", ev))
    assert ans.text == "Onboarding maps to P2C1.1.1." and ans.claim_label == "FACT"
    assert ans.model != "hermetic-stub" and ans.cost_usd > 0


def test_ground_live_empty_is_safe_refusal(monkeypatch: pytest.MonkeyPatch) -> None:
    g = _wire(monkeypatch, "")  # SAFETY block / empty completion
    ans = asyncio.run(g.ground("q", [{"name": "X", "subcap_id": "P1C1.1.1", "description": "y"}]))
    assert "No grounded answer" in ans.text and ans.claim_label == "HYPOTHESIS"


def test_infer_subvertical_live_parses_json(monkeypatch: pytest.MonkeyPatch) -> None:
    g = _wire(monkeypatch, '{"name": "Agricultural Finance", "rationale": "Ag lending cluster."}')
    inf = asyncio.run(
        g.infer_subvertical_name(
            {
                "clients": ["AGCO"],
                "top_capabilities": [{"name": "Lending", "n": 5}],
                "pillars": ["P3"],
                "sample_summaries": ["loan origination"],
                "story_count": 42,
            }
        )
    )
    assert inf.name == "Agricultural Finance" and inf.code and inf.claim_label == "HYPOTHESIS"
    assert inf.model != "hermetic-stub"


def test_infer_subvertical_live_bad_json_degrades(monkeypatch: pytest.MonkeyPatch) -> None:
    g = _wire(monkeypatch, "not json at all")
    inf = asyncio.run(
        g.infer_subvertical_name(
            {
                "clients": ["X"],
                "top_capabilities": [{"name": "Data", "n": 3}],
                "pillars": ["P4"],
                "sample_summaries": [],
                "story_count": 10,
            }
        )
    )
    assert inf.model == "hermetic-stub"  # bad parse -> deterministic fallback, never crashes


def test_embed_live_returns_vectors(monkeypatch: pytest.MonkeyPatch) -> None:
    g = _wire(monkeypatch)
    vecs = asyncio.run(g.embed(["alpha", "beta"]))
    assert len(vecs) == 2 and len(vecs[0]) == 768
