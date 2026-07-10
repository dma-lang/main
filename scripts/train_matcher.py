#!/usr/bin/env python3
"""Train the story<->subcap matcher on the golden benchmark and export it as plain coefficients.

Trains a standardized logistic regression over the shared feature contract
(app/intelligence/match_features.FEATURES) using the author-curated golden benchmark
(backend/seed/golden_matches.json.gz, project-disjoint train/test split), reports held-out
metrics, and exports the model to config/matcher_model.json as PURE NUMBERS — feature names,
standardization mean/scale, coefficients, intercept, decision threshold and the measured metrics.
The runtime (app/intelligence/matcher_model.py) is then a dot product + sigmoid: no scikit-learn,
no pickle, fully auditable and diffable in config, exactly like every other gate threshold.

scikit-learn is a DEV dependency only (used here, never at runtime). A HistGradientBoosting
comparison is printed for honesty about what the linear model leaves on the table, but only the
linear model is exported. Deterministic: fixed seeds, deterministic features, pinned MiniLM.

Usage:  backend/.venv/bin/python scripts/train_matcher.py
"""

from __future__ import annotations

import gzip
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import numpy as np  # noqa: E402

from app.intelligence import local_embeddings  # noqa: E402
from app.intelligence.match_features import (  # noqa: E402
    FEATURES,
    MatchFeaturizer,
    defs_from_catalogue,
)

SEED_DIR = ROOT / "backend" / "seed"
OUT = ROOT / "config" / "matcher_model.json"


def main() -> None:
    if not local_embeddings.available():
        raise SystemExit("MiniLM model missing — run scripts/fetch_minilm.py first")
    bench = json.loads(
        gzip.decompress((SEED_DIR / "golden_matches.json.gz").read_bytes())
    )
    rows = bench["rows"]
    stories = {r["k"]: r for r in json.load(gzip.open(SEED_DIR / "stories.json.gz"))}
    cat = json.load(gzip.open(SEED_DIR / "catalogue_v7.json.gz"))
    # exemplars = the author-curated positives themselves (the same catalogue story refs the
    # runtime has); leakage is prevented per-pair below by excluding the story's own project
    exemplars: dict[str, list[dict]] = {}
    for r in rows:
        if r["label"] == 1:
            exemplars.setdefault(r["subcap_id"], []).append(stories[r["story_key"]])
    fz = MatchFeaturizer(defs_from_catalogue(cat["subcaps"]), exemplars=exemplars)
    assert fz.available

    keys = sorted({r["story_key"] for r in rows})
    print(f"encoding {len(keys)} stories + 851 defs + exemplars through MiniLM …")
    vecs = fz.encode_stories([stories[k] for k in keys])
    assert vecs is not None
    vec_by_key = dict(zip(keys, vecs, strict=True))

    X, y, split, src = [], [], [], []
    for r in rows:
        srow = stories[r["story_key"]]
        f = fz.features(
            srow,
            r["subcap_id"],
            vec_by_key[r["story_key"]],
            exclude_project=str(srow.get("pk") or ""),
        )
        if f is None:
            continue
        X.append([f[name] for name in FEATURES])
        y.append(int(r["label"]))
        split.append(r["split"])
        src.append(r["source"])
    Xa = np.asarray(X)
    ya = np.asarray(y)
    tr = np.asarray([s == "train" for s in split])
    te = ~tr
    print(f"features: {Xa.shape}, train={int(tr.sum())}, test={int(te.sum())}")

    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import precision_score, recall_score, roc_auc_score
    from sklearn.preprocessing import StandardScaler

    scaler = StandardScaler().fit(Xa[tr])
    Xs = scaler.transform(Xa)
    lr = LogisticRegression(max_iter=2000, C=1.0, random_state=7).fit(Xs[tr], ya[tr])
    p_tr, p_te = lr.predict_proba(Xs[tr])[:, 1], lr.predict_proba(Xs[te])[:, 1]

    # OPERATING POINT chosen on TRAIN only, verified on held-out TEST. The gate's asymmetry:
    # a genuine delivery must (almost) never be dumped, so the KEEP threshold is the highest
    # cut that retains >= 98.5% of train positives; garbage-catch is whatever that point buys.
    grid = np.linspace(0.01, 0.99, 197)
    keep_ok = [t for t in grid if (p_tr[ya[tr] == 1] >= t).mean() >= 0.985]
    thr = float(max(keep_ok)) if keep_ok else 0.01
    pred_te = p_te >= thr
    pos_te, neg_te = ya[te] == 1, ya[te] == 0
    keep_recall = float(pred_te[pos_te].mean())
    garbage_catch = float((~pred_te[neg_te]).mean())
    acc = float((pred_te == ya[te]).mean())
    prec = float(precision_score(ya[te], pred_te))
    rec = float(recall_score(ya[te], pred_te))
    auc = float(roc_auc_score(ya[te], p_te))
    print(f"\nLOGISTIC (exported) — held-out test @keep-threshold={thr:.3f}")
    print(f"  KEEP-RECALL (genuine kept)    = {keep_recall:.4f}   <- must be >= 0.98")
    print(f"  GARBAGE-CATCH (garbage caught)= {garbage_catch:.4f}")
    print(
        f"  accuracy={acc:.4f}  precision={prec:.4f}  recall={rec:.4f}  auc={auc:.4f}"
    )
    # per-negative-source error detail (which negatives still fool it?)
    src_te = np.asarray(src)[te]
    for s in sorted(set(src_te)):
        m = src_te == s
        print(
            f"  [{s:12}] n={int(m.sum()):5d}  acc={(pred_te[m] == ya[te][m]).mean():.4f}"
        )

    # VETO threshold — the gate's protective rescue only fires when the model is NEAR-CERTAIN the
    # original assignment is genuine (train precision >= 0.90), so the deterministic garbage
    # cleanup keeps its power; unattainable precision exports 0.99 (veto ~never fires — honest).
    veto_thr, veto_prec, veto_rec = 0.99, 0.0, 0.0
    pos_tr = ya[tr] == 1
    for t in grid:
        sel = p_tr >= t
        if sel.sum() >= 20:
            pr = float(ya[tr][sel].mean())
            if pr >= 0.90:
                veto_thr, veto_prec = float(t), pr
                veto_rec = float(sel[pos_tr].mean())
                break
    v_sel = p_te >= veto_thr
    v_prec_te = float(ya[te][v_sel].mean()) if v_sel.sum() else 0.0
    print(
        f"\n  VETO point: thr={veto_thr:.3f} train-precision={veto_prec:.3f} "
        f"train-recall={veto_rec:.3f}; held-out precision={v_prec_te:.3f} (n={int(v_sel.sum())})"
    )

    # the honest trade-off curve: garbage caught at each train keep-recall constraint (held-out)
    print("\n  keep-recall (train-set constraint) -> held-out keep / garbage-catch:")
    for target in (0.999, 0.995, 0.99, 0.985, 0.98, 0.95, 0.90):
        ok = [t for t in grid if (p_tr[ya[tr] == 1] >= t).mean() >= target]
        t0 = float(max(ok)) if ok else 0.01
        pk = float((p_te[pos_te] >= t0).mean())
        gc = float((p_te[neg_te] < t0).mean())
        print(
            f"    train>={target:.3f} thr={t0:.3f} -> held-out keep={pk:.4f} catch={gc:.4f}"
        )

    hgb = HistGradientBoostingClassifier(random_state=7).fit(Xa[tr], ya[tr])
    hp = hgb.predict_proba(Xa[te])[:, 1]
    hacc = float(((hp >= 0.5) == ya[te]).mean())
    print(
        f"\nHGB (comparison only) — held-out accuracy={hacc:.4f} auc={roc_auc_score(ya[te], hp):.4f}"
    )

    coef = (
        lr.coef_[0] / scaler.scale_
    ).tolist()  # fold standardization into the coefficients
    intercept = float(
        lr.intercept_[0] - float(np.dot(lr.coef_[0], scaler.mean_ / scaler.scale_))
    )
    model = {
        "kind": "logistic",
        "features": FEATURES,
        "coef": [round(c, 8) for c in coef],
        "intercept": round(intercept, 8),
        "threshold": round(thr, 4),
        "veto_threshold": round(veto_thr, 4),
        "metrics": {
            "veto_train_precision": round(veto_prec, 4),
            "veto_held_out_precision": round(v_prec_te, 4),
            "held_out_keep_recall": round(keep_recall, 4),
            "held_out_garbage_catch": round(garbage_catch, 4),
            "held_out_accuracy": round(acc, 4),
            "held_out_precision": round(prec, 4),
            "held_out_recall": round(rec, 4),
            "held_out_auc": round(auc, 4),
            "train_rows": int(tr.sum()),
            "test_rows": int(te.sum()),
        },
        "trained_on": "backend/seed/golden_matches.json.gz (author-curated catalogue story refs)",
        "embedder": "sentence-transformers/all-MiniLM-L6-v2 (local ONNX, scripts/fetch_minilm.py)",
        "trained_at": datetime.now(UTC).strftime("%Y-%m-%d"),
    }
    OUT.write_text(json.dumps(model, indent=2) + "\n")
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
