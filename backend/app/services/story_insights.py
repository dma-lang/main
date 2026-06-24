"""Delivery drilldown insights for a subcap (C3 trace + A2 Delivery tab).

Two deterministic analyses over the CARRIED Jira corpus (story_catalogue_link is Jira-only by
construction — synthetic stories never enter it):

1. ``clients``  — the Jira *project key* is the engagement/client proxy in this corpus, so
   grouping a subcap's stories by ``project_key`` "parses the clients" that delivered it.
2. ``clusters`` — greedy token-overlap clustering of story summaries groups stories with similar
   characteristics; each cluster lists the *related clients* that delivered into it. Pure-python
   and deterministic (no model call, hermetic-safe) — the same overlap-coefficient family used by
   the value-chain dedupe, so results are reproducible and explainable: every cluster label is the
   member summaries' dominant terms, never a generated phrase.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

# Function words only — domain words ("data", "migration", "salesforce") MUST survive because they
# become the cluster labels.
_STOP = frozenset(
    "a an and are as at be been by can could did do does for from had has have i if in into is it "
    "its of on or our shall should so that the their then there these they this to was we were "
    "what when which will with would you your".split()
)
_TOKEN_RE = re.compile(r"[a-z0-9]{3,}")

# Overlap coefficient |A∩B| / min(|A|,|B|) ≥ this joins a story to a cluster. More forgiving than
# Jaccard for short summaries of very different lengths.
_JOIN = 0.5
_CENTROID_K = 12  # compare against the cluster's top-K terms, not its whole (growing) vocabulary
_MIN_CLUSTER = 3  # smaller groups stay "unclustered" rather than reading as fake themes
_MAX_CLUSTERS = 10
_SAMPLE = 5


def tokenize(summary: str | None) -> set[str]:
    return {t for t in _TOKEN_RE.findall((summary or "").lower()) if t not in _STOP}


def cluster_stories(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Greedy single-pass clustering of story rows (story_key, project_key, summary,
    composite_score). Input order is normalised (story_key) so the result is deterministic."""
    clusters: list[dict[str, Any]] = []  # {terms: Counter, members: [row]}
    unclustered = 0
    for row in sorted(rows, key=lambda r: str(r.get("story_key") or "")):
        toks = tokenize(row.get("summary"))
        if not toks:
            unclustered += 1
            continue
        best, best_ov = None, 0.0
        for c in clusters:
            centroid = {t for t, _ in c["terms"].most_common(_CENTROID_K)}
            inter = len(toks & centroid)
            ov = inter / min(len(toks), len(centroid)) if inter else 0.0
            if ov > best_ov:
                best, best_ov = c, ov
        if best is not None and best_ov >= _JOIN:
            best["terms"].update(toks)
            best["members"].append(row)
        else:
            clusters.append({"terms": Counter(toks), "members": [row]})

    kept = [c for c in clusters if len(c["members"]) >= _MIN_CLUSTER]
    unclustered += sum(len(c["members"]) for c in clusters if len(c["members"]) < _MIN_CLUSTER)
    kept.sort(key=lambda c: (-len(c["members"]), str(c["members"][0]["story_key"])))

    out: list[dict[str, Any]] = []
    for i, c in enumerate(kept[:_MAX_CLUSTERS]):
        members: list[dict[str, Any]] = c["members"]
        # Label = the dominant shared terms (frequency, then alphabetical for determinism).
        top = sorted(c["terms"].most_common(4), key=lambda x: (-x[1], x[0]))[:3]
        label = " · ".join(t for t, _ in top)
        scores = [m["composite_score"] for m in members if m.get("composite_score") is not None]
        client_counts = Counter(str(m["project_key"]) for m in members if m.get("project_key"))
        sample = sorted(
            members,
            key=lambda m: (-(m.get("composite_score") or 0.0), str(m["story_key"])),
        )[:_SAMPLE]
        out.append(
            {
                "cluster_id": i + 1,
                "label": label,
                "stories": len(members),
                "clients": [k for k, _ in client_counts.most_common()],
                "avg_composite": round(sum(scores) / len(scores), 2) if scores else None,
                "sample": sample,
            }
        )
    overflow = sum(len(c["members"]) for c in kept[_MAX_CLUSTERS:])
    return {"clusters": out, "unclustered": unclustered + overflow}
