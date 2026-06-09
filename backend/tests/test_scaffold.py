"""Scaffold-level tests.

These tie `config/*.yaml` to CI so a malformed schedule/model/gate file fails the build,
and assert the app reports a valid SemVer. Real foundation tests (F1–F15) land from Stage 1.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from app import APP_VERSION

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG = REPO_ROOT / "config"
SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:[-+].+)?$")


def _load(name: str) -> dict[str, Any]:
    with (CONFIG / name).open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    assert isinstance(data, dict)
    return data


def test_app_version_is_semver() -> None:
    assert SEMVER.match(APP_VERSION), APP_VERSION


def test_models_config_pins_every_tier() -> None:
    cfg = _load("models.yaml")
    tiers = cfg["tiers"]
    for tier in ("classify", "enrich", "match", "ground", "synthesize", "adversarial"):
        assert tiers[tier], tier
    # Embedding dimension must match cat_<v>.subcap.embedding vector(768).
    assert cfg["embedding"]["dimensions"] == 768
    assert cfg["region"] == "us-central1"


def test_schedules_have_cron_and_job() -> None:
    cfg = _load("schedules.yaml")
    for name, spec in cfg["schedules"].items():
        assert spec.get("cron"), name
        assert spec.get("job"), name


def test_all_eight_gates_present() -> None:
    cfg = _load("gates.yaml")
    gate_ids = {key.split("_", 1)[0] for key in cfg["gates"]}
    assert gate_ids == {f"G{i}" for i in range(1, 9)}, gate_ids
