"""Config-driven subvertical-code aliases (config/subvertical_aliases.yaml).

One canonical alias map (e.g. legacy ``PEN`` -> ``RIA``) applied wherever an SV code enters or
scopes the system — story ingest, carry-forward, the subcap tier suffix, the value-chain mapping,
and the read-time sv filters — so one canonical code flows end-to-end. DETERMINISTIC config
(not an AI conclusion): same trust level as config/value_chain.yaml, so no gate is required. An
unknown code passes through unchanged (never silently dropped).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

# A tier is "<level>-<SV>" (e.g. T2-PEN); the level is kept, only the SV suffix is canonicalised.
_TIER_RE = re.compile(r"^(T\d+)-([A-Za-z]{2,})$")

_aliases_cache: dict[str, str] | None = None


def _config_path() -> Path | None:
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "config" / "subvertical_aliases.yaml"
        if candidate.exists():
            return candidate
    return None


def _load() -> dict[str, str]:
    path = _config_path()
    if path is None:
        return {}
    with path.open() as fh:
        cfg: dict[str, Any] = yaml.safe_load(fh) or {}
    raw = cfg.get("aliases") or {}
    # case-insensitive, canonical UPPERCASE on both sides
    return {str(k).strip().upper(): str(v).strip().upper() for k, v in raw.items()}


def _aliases() -> dict[str, str]:
    global _aliases_cache
    if _aliases_cache is None:
        _aliases_cache = _load()
    return _aliases_cache


def reload_aliases() -> None:
    """Drop the cache so a config edit applies (used by tests / an admin reload)."""
    global _aliases_cache
    _aliases_cache = None


def normalize_sv_code(code: str | None) -> str | None:
    """Canonicalise an SV code via the alias map (e.g. PEN -> RIA). Unknown/empty pass through; a
    real code is returned UPPERCASE so it matches the nine modelled codes."""
    if not code:
        return code
    up = code.strip().upper()
    return _aliases().get(up, up)


def normalize_tier(tier: str | None) -> str | None:
    """Canonicalise a tier's SV suffix, e.g. 'T2-PEN' -> 'T2-RIA'. Tiers without an SV suffix
    ('T1', 'T2', None) pass through unchanged."""
    if not tier:
        return tier
    m = _TIER_RE.match(tier.strip())
    if not m:
        return tier
    return f"{m.group(1)}-{normalize_sv_code(m.group(2))}"
