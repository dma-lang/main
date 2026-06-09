"""Schedule reader — surfaces ``config/schedules.yaml`` to the API (last/next scan indicators).

The News/Trends/Vendor/Benchmark surfaces must reflect their real cadence ("the FE never implies
real-time"), so next-run times are computed here from the SAME config Cloud Scheduler is
provisioned from. Only the cron forms the config actually uses are supported — minute/hour fixed,
with a day-of-week name, a day-of-month, or wildcards — anything else fails loudly, never guesses.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

_DOW = {"MON": 0, "TUE": 1, "WED": 2, "THU": 3, "FRI": 4, "SAT": 5, "SUN": 6}


def _config_path() -> Path:
    here = Path(__file__).resolve()
    for root in (here.parents[2], here.parents[3]):  # container /app · repo root
        candidate = root / "config" / "schedules.yaml"
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("config/schedules.yaml not found")


@lru_cache
def load_schedules() -> dict[str, dict[str, Any]]:
    with _config_path().open() as fh:
        loaded = yaml.safe_load(fh)
    schedules = loaded.get("schedules", {})
    if not isinstance(schedules, dict):
        raise ValueError("schedules.yaml: 'schedules' must be a mapping")
    return {str(k): dict(v) for k, v in schedules.items()}


def next_run(cron: str, now: datetime | None = None) -> datetime:
    """Next UTC fire time for the restricted cron forms used in schedules.yaml:
    ``M H * * DOW`` (weekly), ``M H D * *`` (monthly), ``M H D M,.. *`` (specific months),
    ``M H * * *`` (daily) and ``M * * * *`` (hourly)."""
    minute_s, hour_s, dom_s, month_s, dow_s = cron.split()
    t = (now or datetime.now(UTC)).astimezone(UTC)
    minute = int(minute_s)

    if hour_s == "*":  # hourly
        candidate = t.replace(minute=minute, second=0, microsecond=0)
        return candidate if candidate > t else candidate + timedelta(hours=1)

    hour = int(hour_s)
    candidate = t.replace(hour=hour, minute=minute, second=0, microsecond=0)

    if dow_s != "*":  # weekly on a named day
        target = _DOW[dow_s.upper()]
        candidate += timedelta(days=(target - candidate.weekday()) % 7)
        return candidate if candidate > t else candidate + timedelta(days=7)

    if dom_s != "*":  # monthly (optionally restricted to listed months), on day-of-month
        months = (
            sorted(int(m) for m in month_s.split(",")) if month_s != "*" else list(range(1, 13))
        )
        candidate = candidate.replace(day=int(dom_s))
        for add_year in (0, 1):
            for m in months:
                option = candidate.replace(year=candidate.year + add_year, month=m)
                if option > t:
                    return option
        raise ValueError(f"could not schedule cron {cron!r}")  # pragma: no cover

    return candidate if candidate > t else candidate + timedelta(days=1)  # daily


def describe(name: str, now: datetime | None = None) -> dict[str, str]:
    """{cron, cadence description, next_run ISO} for one schedule entry, for API surfaces."""
    entry = load_schedules()[name]
    cron = str(entry["cron"])
    return {
        "cron": cron,
        "description": str(entry.get("description", "")),
        "next_run": next_run(cron, now).isoformat(),
    }
