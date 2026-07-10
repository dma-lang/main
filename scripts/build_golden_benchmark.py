#!/usr/bin/env python3
"""Build the GOLDEN story<->subcap matching benchmark from the author-curated catalogue refs.

The v7 catalogue embeds, per subcap, the story keys its AUTHORS curated as genuine deliveries of
that capability (``subcaps[].stories[].k`` — the same refs the carry pipeline turns into
``via='catalogue_ref'`` links). Those are the only trustworthy labels in the corpus (the source
``sub_cap_id`` column is measurably noisy — that is why the relatedness gate exists), so they are
the benchmark's POSITIVES. NEGATIVES are constructed per positive story:

* ``hard``        — the highest-scoring OTHER subcap under the production lexical index from a
                    DIFFERENT L1 category than every author subcap (same pillar). Lexically
                    attracted yet structurally unrelated — the coincidental-vocabulary traps.
* ``same_pillar`` — a deterministic pseudo-random same-pillar, different-L1-category subcap.
* ``any``         — a deterministic pseudo-random different-L1-category subcap from anywhere.

Negatives are restricted to DIFFERENT-L1-CATEGORY subcaps deliberately: a same-category sibling
the authors didn't curate is often still genuinely related (measured: 39% of unconstrained
lexical-hard negatives shared an author subcap's category), so labelling it 0 would poison the
benchmark with irreducible noise. The benchmark therefore measures the decision the relatedness
gate actually makes — is this story's assignment PLAUSIBLE or clearly-unrelated garbage (the
Knowledge-Base-tasks-under-"Innovation Vision" failure class) — not fine intra-category ranking,
which the author refs cannot cleanly label.

Rows carry a train/test SPLIT keyed on the story's Jira project (md5(project) % 4 == 0 -> test),
so stories from one client project never straddle the split (vocabulary leakage would inflate the
held-out numbers). Deterministic end to end — re-running reproduces the identical file.

Output: backend/seed/golden_matches.json.gz
        {"meta": {...}, "rows": [{"story_key", "subcap_id", "label", "source", "split"}]}

Usage:  backend/.venv/bin/python scripts/build_golden_benchmark.py
"""

from __future__ import annotations

import gzip
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.services.story_relatedness import RelatednessIndex, story_doc  # noqa: E402

SEED = ROOT / "backend" / "seed"
OUT = SEED / "golden_matches.json.gz"


def _md5_int(s: str) -> int:
    return int(
        hashlib.md5(s.encode()).hexdigest(), 16
    )  # noqa: S324 - determinism, not crypto


def _split_for(project_key: str) -> str:
    return "test" if _md5_int(f"split:{project_key}") % 4 == 0 else "train"


def base_id(subcap_id: str) -> str:
    """P3C1.8.CL2 -> P3C1.8 (subvertical variants share a base capability)."""
    parts = subcap_id.split(".")
    while (
        parts and parts[-1][:2].isalpha() and parts[-1][:1].isupper() and len(parts) > 1
    ):
        # trailing subvertical segments look like CL2/RIA3 — alpha-prefixed, unlike numeric levels
        if parts[-1].isdigit():
            break
        parts = parts[:-1]
        break
    return ".".join(parts)


def main() -> None:
    cat = json.load(gzip.open(SEED / "catalogue_v7.json.gz"))
    subs = cat["subcaps"]
    stories = {r["k"]: r for r in json.load(gzip.open(SEED / "stories.json.gz"))}
    by_pillar: dict[str, list[str]] = {}
    cat_of: dict[str, str] = {}
    for s in subs:
        by_pillar.setdefault(str(s["pillar"]), []).append(s["id"])
        cat_of[s["id"]] = str(s.get("catId") or "")
    all_ids = [s["id"] for s in subs]

    # production-identical lexical index (name + L2 cluster + description) for hard negatives
    defs = [
        {
            "id": s["id"],
            "name": s.get("name") or "",
            "l2": s.get("cluster") or "",
            "description": s.get("desc") or "",
            "pillar": str(s["id"])[:2],
        }
        for s in subs
    ]
    index = RelatednessIndex(defs)

    # 1. positives: author-curated per-subcap story refs (strip the JIRA- prefix used by the sheet)
    author_subcaps: dict[str, set[str]] = {}  # story_key -> author-curated subcap ids
    positives: list[tuple[str, str]] = []
    unresolved = 0
    for s in subs:
        refs = s.get("stories") or []
        if isinstance(refs, str):
            try:
                import ast

                refs = ast.literal_eval(refs)
            except (ValueError, SyntaxError):
                refs = []
        for ref in refs:
            key = str(ref.get("k") or "")
            key = key[5:] if key.startswith("JIRA-") else key
            if key not in stories:
                unresolved += 1
                continue
            positives.append((key, s["id"]))
            author_subcaps.setdefault(key, set()).add(s["id"])

    # 2. negatives per positive story (deterministic; exclude every author subcap + base variants)
    rows: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()

    def add(story_key: str, subcap_id: str, label: int, source: str) -> None:
        if (story_key, subcap_id) in seen:
            return
        seen.add((story_key, subcap_id))
        project = str(stories[story_key].get("pk") or story_key)
        rows.append(
            {
                "story_key": story_key,
                "subcap_id": subcap_id,
                "label": label,
                "source": source,
                "split": _split_for(project),
            }
        )

    for key, sid in positives:
        add(key, sid, 1, "author_ref")

    for key, authors in sorted(author_subcaps.items()):
        author_bases = {base_id(a) for a in authors}
        author_cats = {cat_of.get(a, "") for a in authors}

        def excluded(cand: str) -> bool:
            # a negative must be OUTSIDE every author L1 category (same-category siblings are
            # often genuinely related — labelling them 0 would be noise, not signal)
            return (
                cand in authors
                or base_id(cand) in author_bases
                or cat_of.get(cand, "") in author_cats
            )

        srow = stories[key]
        text = story_doc(srow)
        pillar = str(next(iter(authors)))[:2]
        # hard negative: best-scoring non-author same-pillar subcap under the production index
        best_id, best = None, 0.0
        v, n = index._story_vec(
            text
        )  # noqa: SLF001 - reuse the exact production vectors
        for cand in by_pillar.get(pillar, ()):
            if excluded(cand):
                continue
            sco = index._cos(v, n, cand)  # noqa: SLF001
            if sco > best:
                best, best_id = sco, cand
        if best_id is not None:
            add(key, best_id, 0, "hard")
        # deterministic pseudo-random same-pillar + anywhere negatives
        pil_ids = [c for c in by_pillar.get(pillar, ()) if not excluded(c)]
        if pil_ids:
            add(key, pil_ids[_md5_int(f"sp:{key}") % len(pil_ids)], 0, "same_pillar")
        anywhere = [c for c in all_ids if not excluded(c)]
        if anywhere:
            add(key, anywhere[_md5_int(f"any:{key}") % len(anywhere)], 0, "any")

    n_pos = sum(1 for r in rows if r["label"] == 1)
    n_neg = len(rows) - n_pos
    n_test = sum(1 for r in rows if r["split"] == "test")
    meta = {
        "positives": n_pos,
        "negatives": n_neg,
        "test_rows": n_test,
        "train_rows": len(rows) - n_test,
        "stories": len(author_subcaps),
        "subcaps_with_refs": len({r["subcap_id"] for r in rows if r["label"] == 1}),
        "unresolved_refs": unresolved,
        "generated_from": "catalogue_v7.json.gz subcaps[].stories[].k (author-curated)",
    }
    OUT.write_bytes(gzip.compress(json.dumps({"meta": meta, "rows": rows}).encode()))
    print(json.dumps(meta, indent=2))
    print(f"wrote {OUT} ({OUT.stat().st_size:,} bytes, {len(rows)} rows)")


if __name__ == "__main__":
    main()
