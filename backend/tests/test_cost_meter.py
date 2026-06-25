"""cost_meter: the G8 monthly-envelope math (spend vs the config envelope -> alert/throttle). The DB
sum is monkeypatched so the threshold logic is verified without a database."""

from __future__ import annotations

import asyncio

import pytest

from app.intelligence import cost_meter


def _patch_spend(monkeypatch: pytest.MonkeyPatch, value: float) -> None:
    async def _fake() -> float:
        return value

    monkeypatch.setattr(cost_meter, "spend_this_month", _fake)


def test_status_alerts_below_throttle(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_spend(monkeypatch, 7000.0)  # 7000 / 8000 = 87.5%
    s = asyncio.run(cost_meter.status())
    assert s["envelope"] == 8000.0
    assert round(s["pct"], 1) == 87.5
    assert s["alert"] is True and s["throttle"] is False


def test_over_throttle_past_90pct(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_spend(monkeypatch, 7300.0)  # 91.25%
    assert asyncio.run(cost_meter.over_throttle()) is True


def test_over_throttle_false_when_cheap(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_spend(monkeypatch, 12.5)
    assert asyncio.run(cost_meter.over_throttle()) is False
