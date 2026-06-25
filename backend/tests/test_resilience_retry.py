"""resilience.retry: transient (429/5xx) retries with bounded backoff; 4xx fail fast. Pure, instant
(sleep is injected as a no-op), no network."""

from __future__ import annotations

import asyncio

import pytest

from app.resilience.retry import retry_async, status_of

_RETRYABLE = {429, 500, 502, 503, 504}
_NO_RETRY = {400, 401, 403, 404}


class _Err(Exception):
    def __init__(self, code: int | None) -> None:
        self.status_code = code


async def _noop_sleep(_: float) -> None:
    return None


def test_status_of_reads_status_else_none() -> None:
    assert status_of(_Err(429)) == 429
    assert status_of(Exception("network blip")) is None  # no status -> treated as transient


def test_retries_transient_then_succeeds() -> None:
    n = {"calls": 0}

    async def fn() -> str:
        n["calls"] += 1
        if n["calls"] < 3:
            raise _Err(503)
        return "ok"

    out = asyncio.run(
        retry_async(fn, retryable=_RETRYABLE, no_retry=_NO_RETRY, jitter=False, sleep=_noop_sleep)
    )
    assert out == "ok" and n["calls"] == 3


def test_no_retry_on_4xx_fails_fast() -> None:
    n = {"calls": 0}

    async def fn() -> str:
        n["calls"] += 1
        raise _Err(400)

    with pytest.raises(_Err):
        asyncio.run(
            retry_async(
                fn, retryable=_RETRYABLE, no_retry=_NO_RETRY, jitter=False, sleep=_noop_sleep
            )
        )
    assert n["calls"] == 1  # 400 is fatal — no retries


def test_gives_up_after_max_attempts() -> None:
    n = {"calls": 0}

    async def fn() -> str:
        n["calls"] += 1
        raise _Err(503)

    with pytest.raises(_Err):
        asyncio.run(
            retry_async(
                fn,
                retryable=_RETRYABLE,
                no_retry=_NO_RETRY,
                max_attempts=3,
                jitter=False,
                sleep=_noop_sleep,
            )
        )
    assert n["calls"] == 3
