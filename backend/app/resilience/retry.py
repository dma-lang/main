"""Retry + exponential backoff + jitter for transient failures (CLAUDE.md safeguard 9).

Transient (429 / 5xx, or a bare network error) retries with bounded exponential backoff + jitter;
4xx (400/401/403/404) fail FAST — a schema/auth error must surface, never be masked by retries.
``sleep`` and ``rand`` are injectable so tests are deterministic and instant (no real waiting).
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable


def status_of(exc: BaseException) -> int | None:
    """Best-effort HTTP status from a provider exception (google-genai / httpx shapes), else None.
    None means 'no status' — treated as a transient network error and retried."""
    for attr in ("status_code", "code", "status"):
        val = getattr(exc, attr, None)
        if isinstance(val, int):
            return val
    resp = getattr(exc, "response", None)
    code = getattr(resp, "status_code", None)
    return code if isinstance(code, int) else None


async def retry_async[T](
    fn: Callable[[], Awaitable[T]],
    *,
    retryable: set[int],
    no_retry: set[int],
    max_attempts: int = 5,
    base: float = 1.0,
    cap: float = 16.0,
    jitter: bool = True,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    rand: Callable[[], float] = random.random,
) -> T:
    """Call ``fn`` with retries on transient failures. Re-raises immediately on a ``no_retry``
    status or once ``max_attempts`` is spent; backoff = ``min(cap, base*2**(n-1))`` * jitter."""
    attempt = 0
    while True:
        attempt += 1
        try:
            return await fn()
        except Exception as exc:  # noqa: BLE001 - classify-then-reraise; nothing is swallowed
            status = status_of(exc)
            transient = status in retryable if status is not None else True
            if status in no_retry or not transient or attempt >= max_attempts:
                raise
            delay = min(cap, base * (2 ** (attempt - 1)))
            if jitter:
                delay *= 0.5 + rand() * 0.5  # full-ish jitter in [0.5, 1.0] of the backoff
            await sleep(delay)
