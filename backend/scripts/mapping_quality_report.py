"""Per-L2 story->capability mapping-quality report.

Scores every real story's text against its SOURCE-assigned capability definition (the same
deterministic lexical relatedness the carry-forward gate uses, services/story_relatedness) and
reports, per L2 cluster, how many carries are weak-fit and how many clearly fit a different sibling
(``misrouted``). Run it to see where the source ``sub_cap_id`` mapping is noisy:

    cd backend && uv run python scripts/mapping_quality_report.py [--pillar P1] [--limit 20]

Lexical only (deterministic, no DB, no spend); the live carry blends the dense embedding half on
top, which narrows the weak-fit set by rescuing vocabulary-gap true matches.
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

# backend/ on sys.path so `python scripts/mapping_quality_report.py` resolves the app package
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.intelligence.gates import story_relatedness_config  # noqa: E402
from app.services.story_relatedness import RelatednessIndex, story_doc  # noqa: E402

_SEED = Path(__file__).resolve().parents[1] / "seed"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pillar", default="", help="restrict to one pillar, e.g. P1")
    ap.add_argument("--limit", type=int, default=15, help="worst-L2 rows to show")
    ap.add_argument("--examples", type=int, default=0, help="worst mis-map examples to list")
    args = ap.parse_args()

    cfg = story_relatedness_config()
    subs: list[dict[str, Any]] = json.load(gzip.open(_SEED / "catalogue_v7.json.gz"))["subcaps"]
    ids = {s["id"]: s for s in subs}
    index = RelatednessIndex(subs)
    rows = json.load(gzip.open(_SEED / "stories.json.gz"))

    per_l2: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])  # total, weak, misrouted
    examples: list[tuple[float, float, str, str, str, str]] = []
    for r in rows:
        sc = r.get("sc")
        if sc not in ids or (args.pillar and not str(sc).startswith(args.pillar)):
            continue
        v = index.classify(
            story_doc(r), sc, floor=cfg.floor, margin=cfg.margin, strong_sibling=cfg.strong_sibling
        )
        cluster = ids[sc].get("cluster", "?")
        cell = per_l2[cluster]
        cell[0] += 1
        cell[1] += v.assigned < cfg.floor
        if v.verdict == "misrouted":
            cell[2] += 1
            examples.append(
                (
                    v.assigned,
                    v.best,
                    str(r.get("k")),
                    ids[sc]["name"],
                    ids[v.best_id]["name"],
                    (r.get("sum") or "")[:50],
                )
            )

    print(f"config: floor={cfg.floor} margin={cfg.margin} strong_sibling={cfg.strong_sibling}")
    tot = sum(c[0] for c in per_l2.values())
    weak = sum(c[1] for c in per_l2.values())
    mis = sum(c[2] for c in per_l2.values())
    print(f"stories={tot}  weak-fit={weak} ({weak / tot:.1%})  misrouted={mis} ({mis / tot:.1%})\n")
    print(f"{'weak%':>6} {'misrt%':>7}  ({'n':>5})  L2 cluster")
    ranked = sorted(per_l2.items(), key=lambda kv: -(kv[1][1] / kv[1][0]) if kv[1][0] else 0)
    for cluster, (t, w, m) in ranked[: args.limit]:
        if t >= 15:
            print(f"{w / t:6.1%} {m / t:7.1%}  ({t:5d})  {cluster}")
    for a, b, k, an, bn, summ in sorted(examples, key=lambda e: e[1] - e[0], reverse=True)[
        : args.examples
    ]:
        print(f"  {k:14s} {a:.3f} [{an[:24]}] -> {b:.3f} [{bn[:24]}]  '{summ}'")


if __name__ == "__main__":
    main()
