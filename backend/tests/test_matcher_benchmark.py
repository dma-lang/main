"""GOLDEN BENCHMARK lock — the trained matcher's held-out guarantees, recomputed from scratch.

Rebuilds the exact training-time features (same seeds, same featurizer, same leakage guard) for
the held-out TEST split of backend/seed/golden_matches.json.gz and re-evaluates the exported
model (config/matcher_model.json). Locks:

* KEEP-RECALL >= 0.98 — of the author-curated GENUINE story<->subcap matches, at least 98% score
  at/above the keep threshold (held-out, project-disjoint split). The trust-critical direction:
  genuine delivery is (almost) never hidden.
* the stored metrics match the recomputation (the config file cannot drift from the seed), and
* the feature contract matches the code (a features change without retraining disables cleanly).

Model-gated (skips without the MiniLM files) — CI without the model still runs everything else."""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any

import pytest

from app.intelligence import local_embeddings, matcher_model
from app.intelligence.match_features import FEATURES, MatchFeaturizer, defs_from_catalogue

_SEED = Path(__file__).resolve().parents[1] / "seed"

needs_model = pytest.mark.skipif(
    not local_embeddings.available(), reason="MiniLM model files absent (run fetch_minilm.py)"
)


def _bench() -> dict[str, Any]:
    out: dict[str, Any] = json.loads(
        gzip.decompress((_SEED / "golden_matches.json.gz").read_bytes())
    )
    return out


def test_model_loads_and_matches_feature_contract() -> None:
    model = matcher_model.load()
    assert model is not None, "config/matcher_model.json missing or invalid"
    assert list(model.features) == FEATURES
    assert 0 < model.threshold < 1 and model.threshold <= model.veto_threshold <= 1
    assert model.metrics["held_out_keep_recall"] >= 0.98


@needs_model
def test_held_out_keep_recall_at_least_98_percent() -> None:
    model = matcher_model.load()
    assert model is not None
    bench = _bench()
    stories = {r["k"]: r for r in json.load(gzip.open(_SEED / "stories.json.gz"))}
    cat = json.load(gzip.open(_SEED / "catalogue_v7.json.gz"))
    exemplars: dict[str, list[dict[str, Any]]] = {}
    for r in bench["rows"]:
        if r["label"] == 1:
            exemplars.setdefault(r["subcap_id"], []).append(stories[r["story_key"]])
    fz = MatchFeaturizer(defs_from_catalogue(cat["subcaps"]), exemplars=exemplars)
    assert fz.available
    test_rows = [r for r in bench["rows"] if r["split"] == "test"]
    keys = sorted({r["story_key"] for r in test_rows})
    vecs = fz.encode_stories([stories[k] for k in keys])
    assert vecs is not None
    vec = dict(zip(keys, vecs, strict=True))
    kept_true = total_true = caught_garbage = total_garbage = 0
    for r in test_rows:
        srow = stories[r["story_key"]]
        f = fz.features(
            srow, r["subcap_id"], vec[r["story_key"]], exclude_project=str(srow.get("pk") or "")
        )
        assert f is not None
        p = model.probability(f)
        if r["label"] == 1:
            total_true += 1
            kept_true += int(p >= model.threshold)
        else:
            total_garbage += 1
            caught_garbage += int(p < model.threshold)
    keep_recall = kept_true / total_true
    garbage_catch = caught_garbage / total_garbage
    assert total_true > 300 and total_garbage > 900  # the held-out split is real, not degenerate
    assert keep_recall >= 0.98, f"held-out keep-recall {keep_recall:.4f} < 0.98"
    # the stored metrics must be the truth of this seed + model (no silent drift)
    assert abs(keep_recall - model.metrics["held_out_keep_recall"]) <= 0.02
    assert abs(garbage_catch - model.metrics["held_out_garbage_catch"]) <= 0.05
