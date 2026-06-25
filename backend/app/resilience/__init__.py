"""Self-healing primitives (CLAUDE.md safeguard 9), reused — not re-coded — by every live call.

This slice ships the retry/backoff/jitter primitive the live Gemini wrapper composes; idempotency,
circuit-breaker and DLQ helpers land alongside the pipelines that need them.
"""

from app.resilience.retry import retry_async, status_of

__all__ = ["retry_async", "status_of"]
