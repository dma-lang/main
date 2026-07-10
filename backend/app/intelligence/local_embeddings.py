"""Local MiniLM sentence embeddings (ONNX) — the DETERMINISTIC dense half, zero cloud, zero spend.

The hermetic embedder used to be a token-hash bag-of-words: cosine reflected shared tokens only, so
every "semantic" path (dense retrieval, relatedness rescue, use-case matching, KG similarity) was
lexical-in-disguise under tests and degraded live. This module runs sentence-transformers/
all-MiniLM-L6-v2 (fp32 ONNX export, mean-pooled, L2-normalised) fully locally through onnxruntime:
real semantic vectors — "KYC" finally lands near "know your customer" — while staying deterministic
(pinned weights + pinned thread count), offline and free, which is exactly the hermetic contract.

The model files (~90MB) are NOT committed; ``scripts/fetch_minilm.py`` installs them (pinned
revision + SHA-256) into ``backend/models/minilm/`` for dev and the Docker build. When the files
are absent everything degrades exactly as before (token-hash stub) — ``available()`` is the guard,
so no environment hard-fails on a missing model.

MiniLM vectors are 384-d; the shared store/contract is ``vector(768)`` (gemini-embedding-001).
``encode(..., pad_to=768)`` zero-pads — cosine is invariant under zero-padding, so the padded
vectors are drop-in for every existing cosine/HNSW consumer with no schema migration.
"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_BACKEND = Path(__file__).resolve().parents[2]  # app/intelligence/local_embeddings.py -> backend
_DEFAULT_DIR = _BACKEND / "models" / "minilm"

_MAX_TOKENS = 256  # MiniLM's trained context; longer docs are truncated (summary-first docs fit)
_BATCH = 32
_THREADS = 4  # pinned so runs are reproducible on a machine (ORT is deterministic per thread count)

_lock = threading.Lock()
_session: Any | None = None
_tokenizer: Any | None = None
_load_failed = False


def model_dir() -> Path:
    """Model location; ``MINILM_DIR`` overrides for tests/containers."""
    return Path(os.environ.get("MINILM_DIR") or _DEFAULT_DIR)


def available() -> bool:
    """True when the pinned model files exist locally (and the runtime imports)."""
    if _load_failed:
        return False
    d = model_dir()
    return (d / "model.onnx").is_file() and (d / "tokenizer.json").is_file()


def _load() -> tuple[Any, Any] | None:
    """Lazy, cached, thread-safe session+tokenizer; returns None (and remembers) on any failure so
    a broken model file degrades to the token-hash stub instead of crashing the caller."""
    global _session, _tokenizer, _load_failed
    if _session is not None and _tokenizer is not None:
        return _session, _tokenizer
    if _load_failed or not available():
        return None
    with _lock:
        if _session is not None and _tokenizer is not None:
            return _session, _tokenizer
        try:
            import onnxruntime as ort  # noqa: PLC0415 - heavy import deferred until first use
            from tokenizers import Tokenizer  # noqa: PLC0415

            opts = ort.SessionOptions()
            opts.intra_op_num_threads = _THREADS
            opts.inter_op_num_threads = 1
            sess = ort.InferenceSession(
                str(model_dir() / "model.onnx"), opts, providers=["CPUExecutionProvider"]
            )
            tok = Tokenizer.from_file(str(model_dir() / "tokenizer.json"))
            tok.enable_truncation(max_length=_MAX_TOKENS)
            _session, _tokenizer = sess, tok
            return _session, _tokenizer
        except Exception as exc:  # noqa: BLE001 - degrade to the stub, never crash matching
            _load_failed = True
            logger.warning("local MiniLM unavailable (%s); dense half degrades to token-hash", exc)
            return None


def encode(texts: list[str], *, pad_to: int | None = None) -> list[list[float]] | None:
    """Mean-pooled, L2-normalised MiniLM sentence vectors (384-d), optionally zero-padded to
    ``pad_to`` dims for the shared vector(768) contract. Returns None when the model is absent —
    callers fall back to the token-hash stub."""
    loaded = _load()
    if loaded is None:
        return None
    import numpy as np  # noqa: PLC0415

    sess, tok = loaded
    out: list[list[float]] = []
    for start in range(0, len(texts), _BATCH):
        batch = [t or "" for t in texts[start : start + _BATCH]]
        encs = tok.encode_batch(batch)
        width = max(1, max(len(e.ids) for e in encs))
        ids = np.zeros((len(batch), width), dtype=np.int64)
        mask = np.zeros((len(batch), width), dtype=np.int64)
        for i, e in enumerate(encs):
            n = len(e.ids)
            ids[i, :n] = e.ids
            mask[i, :n] = e.attention_mask
        feeds = {"input_ids": ids, "attention_mask": mask}
        if any(i.name == "token_type_ids" for i in sess.get_inputs()):
            feeds["token_type_ids"] = np.zeros_like(ids)
        hidden = sess.run(None, feeds)[0]  # (batch, tokens, 384) last_hidden_state
        m = mask[:, :, None].astype(np.float32)
        pooled = (hidden * m).sum(axis=1) / np.clip(m.sum(axis=1), 1e-9, None)
        norms = np.linalg.norm(pooled, axis=1, keepdims=True)
        pooled = pooled / np.clip(norms, 1e-12, None)
        if pad_to is not None and pad_to > pooled.shape[1]:
            pooled = np.pad(pooled, ((0, 0), (0, pad_to - pooled.shape[1])))
        out.extend(pooled.astype(float).tolist())
    return out


def cosine(a: list[float], b: list[float]) -> float:
    """Cosine of two encode() vectors (already L2-normalised — a plain dot; zero-padding safe)."""
    return float(sum(x * y for x, y in zip(a, b, strict=False)))
