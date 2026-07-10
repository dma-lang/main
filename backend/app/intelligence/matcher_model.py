"""Runtime for the trained story<->subcap matcher — plain coefficients, no ML runtime.

scripts/train_matcher.py fits a standardized logistic regression on the golden benchmark and
exports it to ``config/matcher_model.json`` as pure numbers (feature names, folded coefficients,
intercept, decision threshold, held-out metrics). This module evaluates it: a dot product and a
sigmoid — deterministic, auditable, diffable in config review like every other gate threshold,
and zero new runtime dependencies (scikit-learn stays a dev-only training dependency).

Fail-safe by construction: a missing/invalid file, or a feature contract that no longer matches
``match_features.FEATURES``, loads as None and callers keep the deterministic lexical rules.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.intelligence.match_features import FEATURES

logger = logging.getLogger(__name__)


def _config_path() -> Path | None:
    here = Path(__file__).resolve()
    for parent in here.parents:
        cand = parent / "config" / "matcher_model.json"
        if cand.is_file():
            return cand
    return None


@dataclass(frozen=True)
class MatcherModel:
    """The exported linear matcher: P(genuine match) over match_features.FEATURES."""

    features: tuple[str, ...]
    coef: tuple[float, ...]
    intercept: float
    threshold: float  # KEEP operating point: p >= threshold means "genuine, keep it"
    veto_threshold: float  # NEAR-CERTAIN point (train precision >= 0.9): safe to veto a demotion
    metrics: dict[str, float]

    def probability(self, feats: dict[str, float]) -> float:
        z = self.intercept + sum(
            c * feats.get(name, 0.0) for name, c in zip(self.features, self.coef, strict=True)
        )
        return 1.0 / (1.0 + math.exp(-max(-60.0, min(60.0, z))))

    def keeps(self, feats: dict[str, float]) -> bool:
        return self.probability(feats) >= self.threshold


@lru_cache(maxsize=1)
def load() -> MatcherModel | None:
    """The trained matcher, or None when absent/invalid/contract-drifted (callers degrade to the
    lexical rules — matching never crashes on a model problem)."""
    path = _config_path()
    if path is None:
        return None
    try:
        raw = json.loads(path.read_text())
        features = tuple(str(f) for f in raw["features"])
        if list(features) != FEATURES:
            logger.warning(
                "matcher_model.json feature contract %s != code %s — model disabled, retrain",
                list(features),
                FEATURES,
            )
            return None
        coef = tuple(float(c) for c in raw["coef"])
        if len(coef) != len(features):
            raise ValueError("coef length != features length")
        return MatcherModel(
            features=features,
            coef=coef,
            intercept=float(raw["intercept"]),
            threshold=float(raw["threshold"]),
            # absent in older exports -> effectively never veto (fail-safe for the cleanup)
            veto_threshold=float(raw.get("veto_threshold", 0.99)),
            metrics={k: float(v) for k, v in (raw.get("metrics") or {}).items()},
        )
    except Exception as exc:  # noqa: BLE001 - a bad model file must never break matching
        logger.warning("matcher_model.json unusable (%s) — lexical rules only", exc)
        return None
