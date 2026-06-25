"""Model / retry / cost config loader (``config/models.yaml``). One place reads the pins so the live
Gemini wrapper, the embeddings job and the cost meter agree on models, region, retry policy and the
spend envelope (CLAUDE.md safeguard 8: models pinned by version, never ``-latest``). Mirrors
``gates._config_path`` — walk up to ``<repo-root>/config`` — and re-reads each call so a pin or
threshold change applies without a code deploy.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def _config_path() -> Path:
    here = Path(__file__).resolve()
    for root in here.parents:
        candidate = root / "config" / "models.yaml"
        if candidate.exists():
            return candidate
    raise FileNotFoundError("config/models.yaml not found")


def load_models_config() -> dict[str, Any]:
    with _config_path().open() as fh:
        loaded = yaml.safe_load(fh)
    if not isinstance(loaded, dict):
        raise ValueError("models.yaml: top level must be a mapping")
    return loaded


def vertex_target() -> tuple[str, str]:
    """(project, region) for the Vertex client."""
    cfg = load_models_config()
    project = str(cfg.get("project") or "")
    if not project:
        raise ValueError("models.yaml: 'project' is required for live Vertex")
    return project, str(cfg.get("region") or "us-central1")


def model_for(tier: str) -> str:
    """The pinned model id for a task tier (classify/enrich/match/ground/synthesize/adversarial)."""
    tiers = load_models_config().get("tiers") or {}
    pinned = tiers.get(tier)
    if not pinned:
        raise ValueError(f"models.yaml: no model pinned for tier '{tier}'")
    return str(pinned)


def embedding_model() -> tuple[str, int]:
    """(embedding model id, dimensions) — the single shared vector space."""
    emb = load_models_config().get("embedding") or {}
    return str(emb.get("model") or "gemini-embedding-001"), int(emb.get("dimensions") or 768)


def retry_policy() -> dict[str, Any]:
    """Retry/backoff policy for live calls (status sets + bounds), straight from models.yaml."""
    retry = load_models_config().get("retry") or {}
    return {
        "retryable": {int(s) for s in retry.get("retryable_status", [429, 500, 502, 503, 504])},
        "no_retry": {int(s) for s in retry.get("no_retry_status", [400, 401, 403, 404])},
        "max_attempts": int(retry.get("max_attempts", 5)),
        "base": float(retry.get("backoff_initial_seconds", 1)),
        "cap": float(retry.get("backoff_max_seconds", 16)),
        "jitter": bool(retry.get("jitter", True)),
    }


def cost_envelope() -> tuple[float, float, float]:
    """(monthly_envelope_usd, alert_at_pct, throttle_at_pct) — the G8 budget envelope."""
    cost = load_models_config().get("cost") or {}
    return (
        float(cost.get("monthly_envelope_usd", 8000)),
        float(cost.get("alert_at_pct", 80)),
        float(cost.get("throttle_at_pct", 90)),
    )


def max_output_tokens() -> int:
    return int((load_models_config().get("cost") or {}).get("max_output_tokens_default", 2048))


def token_price() -> tuple[float, float]:
    """(generation, embedding) USD-per-1k-token ESTIMATES for the in-app G8 envelope meter. These
    drive throttling, not billing — the authoritative spend is the GCP invoice."""
    cost = load_models_config().get("cost") or {}
    return (
        float(cost.get("est_usd_per_1k_tokens", 0.0005)),
        float(cost.get("est_embed_usd_per_1k_tokens", 0.0001)),
    )
