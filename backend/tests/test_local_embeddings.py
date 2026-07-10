"""Local MiniLM embeddings (intelligence/local_embeddings) — semantic, deterministic, fail-safe.

Model-gated like the DB tests: when the pinned ONNX files are absent (scripts/fetch_minilm.py not
run) the semantic tests skip and the FALLBACK test still proves nothing hard-fails."""

from __future__ import annotations

import pytest

from app.intelligence import local_embeddings

needs_model = pytest.mark.skipif(
    not local_embeddings.available(), reason="MiniLM model files absent (run fetch_minilm.py)"
)


@needs_model
def test_encode_shapes_and_padding() -> None:
    out = local_embeddings.encode(["one", "two"], pad_to=768)
    assert out is not None and len(out) == 2 and len(out[0]) == 768
    raw = local_embeddings.encode(["one"])
    assert raw is not None and len(raw[0]) == 384  # MiniLM native width


@needs_model
def test_zero_padding_preserves_cosine() -> None:
    a, b = local_embeddings.encode(["customer onboarding flow", "client intake process"]) or []
    ap, bp = (
        local_embeddings.encode(["customer onboarding flow", "client intake process"], pad_to=768)
        or []
    )
    assert abs(local_embeddings.cosine(a, b) - local_embeddings.cosine(ap, bp)) < 1e-6


@needs_model
def test_real_semantics_not_token_overlap() -> None:
    """The reason MiniLM replaces the token-hash stub: zero-token-overlap paraphrases score HIGH,
    unrelated text scores LOW — the hash stub scores both ~0."""
    vecs = local_embeddings.encode(
        [
            "KYC identity checks",
            "know your customer verification",
            "quarterly covenant compliance reporting automation",
        ]
    )
    assert vecs is not None
    kyc_pair = local_embeddings.cosine(vecs[0], vecs[1])
    unrelated = local_embeddings.cosine(vecs[0], vecs[2])
    assert kyc_pair > 0.4  # paraphrase recognised despite zero shared tokens
    assert kyc_pair > unrelated + 0.15  # ...and clearly above an unrelated capability


@needs_model
def test_deterministic() -> None:
    a = local_embeddings.encode(["Configure covenant compliance record"])
    b = local_embeddings.encode(["Configure covenant compliance record"])
    assert a == b


def test_absent_model_degrades_not_crashes(monkeypatch: pytest.MonkeyPatch) -> None:
    """With no model files, available() is False, encode() is None, and the Gemini hermetic embed
    falls back to the token-hash stub — same 768-d contract, nothing raises."""
    monkeypatch.setenv("MINILM_DIR", "/nonexistent/minilm")
    monkeypatch.setattr(local_embeddings, "_session", None)
    monkeypatch.setattr(local_embeddings, "_tokenizer", None)
    monkeypatch.setattr(local_embeddings, "_load_failed", False)
    assert local_embeddings.available() is False
    assert local_embeddings.encode(["x"]) is None
    from app.intelligence.gemini import _hermetic_embed

    vec = _hermetic_embed(["covenant compliance"], 768)
    assert len(vec) == 1 and len(vec[0]) == 768
    assert any(v > 0 for v in vec[0])  # token-hash fallback produced a real vector
