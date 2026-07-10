"""Story <-> capability RELATEDNESS gate (delivery-mapping QA).

Carry-forward links a Jira story to the subcap named by its SOURCE ``sub_cap_id`` and, for a native
id hit, auto-confirms it at similarity 1.0 with NO check that the story TEXT actually concerns that
capability. The source ids are noisy (measured: the median story<->assigned-capability lexical
relatedness across the real corpus is ~0.02, and hundreds of P1 stories about Salesforce Knowledge
Base sit under "Innovation Vision"). This module scores whether a story genuinely belongs to its
assigned capability — and, when it clearly does not, which sibling in the SAME pillar it fits better
— so the delivery surfaces can flag / demote / re-route the wrong matches instead of showing them as
confident delivery.

The score is a deterministic TF-IDF cosine between the story text (summary x3 + description + AC)
and the capability DEFINITION (subcap name + its L2 cluster + L1 category + description + personas
+ use-case texts), with the IDF taken over ALL of the version's subcap definitions so generic
scaffolding ("capability", "digital", "management") carries ~no weight and only discriminating terms
drive the score. This is the LEXICAL half — it runs everywhere (hermetic == live, zero spend) and is
strong enough to catch a zero-overlap mismatch. In production the caller blends a DENSE embedding
cosine on top (the "deep learning" half, services/embeddings) which rescues vocabulary-gap true
matches the lexical half would under-score; a match is only demoted when BOTH halves are weak, so
the gate never punishes a real match just because the consultant and the catalogue chose different
words. Grounded + gated: the gate DEMOTES a weak carry to review or STAGES a re-route proposal — it
never silently rewrites the delivery attribution.
"""

from __future__ import annotations

import ast
import math
from collections import Counter
from dataclasses import dataclass
from typing import Any

from app.services.use_case_match import _tokens

# how the capability-definition doc is built — the NAME and its L2 cluster are the most
# discriminating signal, so they are repeated to weight them above the long generic description.
_NAME_REPEAT = 3
_CLUSTER_REPEAT = 2


@dataclass(frozen=True)
class Verdict:
    """One story's relatedness to its assigned subcap + its best-fitting sibling in the pillar."""

    assigned: float  # lexical relatedness to the assigned subcap (0..1)
    best_id: str  # the best-fitting subcap in the story's pillar
    best: float  # its relatedness
    verdict: str  # "fit" | "review" | "misrouted"

    @property
    def reroute(self) -> str | None:
        """The subcap to re-route to when the story clearly fits a sibling better — else None."""
        return self.best_id if self.verdict == "misrouted" else None


def _as_list(v: Any) -> list[Any]:
    if isinstance(v, list):
        return v
    if isinstance(v, str) and v.strip().startswith("["):
        try:
            out = ast.literal_eval(v)
            return out if isinstance(out, list) else []
        except (ValueError, SyntaxError):
            return []
    return []


def definition_doc(sub: dict[str, Any]) -> str:
    """The capability definition text used to test relatedness: name (x3) + L2 cluster (x2) + L1
    category + description + personas + use-case texts. Tolerant of the seed's stringified lists and
    of both the seed keys and the DB column names (cluster/l2, catName/category_name, desc/…)."""
    name = str(sub.get("name") or "")
    cluster = str(sub.get("cluster") or sub.get("l2") or "")
    cat = str(sub.get("catName") or sub.get("category_name") or "")
    desc = str(sub.get("desc") or sub.get("description") or "")
    parts = [name] * _NAME_REPEAT + [cluster] * _CLUSTER_REPEAT + [cat, desc]
    parts += [str(p) for p in _as_list(sub.get("personas"))]
    for u in _as_list(sub.get("uc")):
        if isinstance(u, dict):
            parts.append(str(u.get("text") or ""))
        elif isinstance(u, str):
            parts.append(u)
    return " ".join(p for p in parts if p)


def story_doc(story: dict[str, Any]) -> str:
    """The story text: summary x3 (headline dominates) + description + acceptance criteria. Reads
    both the seed short keys (``sum``/``desc``/``act``) and the DB column names."""
    summary = str(story.get("sum") or story.get("summary") or "")
    desc = str(story.get("desc") or story.get("description") or "")
    ac = str(story.get("act") or story.get("ac_text") or "")
    return " ".join([summary, summary, summary, desc, ac])


class RelatednessIndex:
    """A TF-IDF space over one version's subcap definitions. Build once per carry, then score each
    story against its assigned subcap and against its pillar siblings. Deterministic, no spend."""

    def __init__(self, subcaps: list[dict[str, Any]]) -> None:
        self._pillar: dict[str, str] = {}
        self._by_pillar: dict[str, list[str]] = {}
        docs: dict[str, Counter[str]] = {}
        for s in subcaps:
            sid = str(s.get("id") or s.get("subcap_id"))
            docs[sid] = _tokens(definition_doc(s))
            pil = str(s.get("pillar") or "")
            self._pillar[sid] = pil
            self._by_pillar.setdefault(pil, []).append(sid)
        n = len(docs) or 1
        df: Counter[str] = Counter()
        for d in docs.values():
            df.update(d.keys())
        self._idf: dict[str, float] = {t: math.log(n / c) for t, c in df.items()}
        self._vec: dict[str, dict[str, float]] = {}
        self._norm: dict[str, float] = {}
        for sid, d in docs.items():
            v = {t: tf * self._idf[t] for t, tf in d.items()}
            self._vec[sid] = v
            self._norm[sid] = math.sqrt(sum(w * w for w in v.values())) or 1.0

    def _story_vec(self, story_text: str) -> tuple[dict[str, float], float]:
        v = {t: tf * self._idf.get(t, 0.0) for t, tf in _tokens(story_text).items()}
        return v, (math.sqrt(sum(w * w for w in v.values())) or 1.0)

    def _cos(self, v: dict[str, float], n: float, sid: str) -> float:
        sv = self._vec.get(sid)
        if sv is None:
            return 0.0
        dot = sum(w * sv.get(t, 0.0) for t, w in v.items())
        return dot / (n * self._norm[sid]) if dot else 0.0

    def _shared_terms(self, v: dict[str, float], sid: str) -> int:
        """How many DISCRIMINATING terms the story shares with a subcap definition (both weighted).
        A re-route resting on a SINGLE shared word is almost always coincidental — a Salesforce
        "Create Personal Lead Page Layout" matches "Personal Trading Compliance" only on 'personal',
        "x-JOURNEY: CL_Quote_Exit" matches "Exit Planning" only on 'exit'. Measured on the real
        corpus, 32% of lexical re-routes rest on one such word and are wrong; requiring two
        independent terms keeps the genuine multi-term re-routes and drops the coincidental ones."""
        sv = self._vec.get(sid)
        if not sv:
            return 0
        return sum(1 for t, w in v.items() if w > 0.0 and t in sv)

    def relatedness(self, story_text: str, subcap_id: str) -> float:
        v, n = self._story_vec(story_text)
        return self._cos(v, n, subcap_id)

    def classify(
        self,
        story_text: str,
        subcap_id: str,
        *,
        floor: float,
        margin: float,
        strong_sibling: float,
        min_reroute_terms: int = 2,
        dense_assigned: float | None = None,
        dense_strong: float = 1.0,
    ) -> Verdict:
        """Score the story against its assigned subcap and its pillar siblings, then classify:

        * ``fit``       — related to the assigned subcap (lexical >= floor), OR the dense half
                          vouches for it (``dense_assigned >= dense_strong``) so a vocabulary-gap
                          true match is never punished. Kept as-is.
        * ``misrouted`` — weak on the assigned subcap AND a pillar sibling is a strong, clearly
                          better fit (``best >= strong_sibling``, beats the assigned by ``margin``,
                          AND rests on >= ``min_reroute_terms`` shared discriminating terms so the
                          move is not a coincidental single-word hit). A re-route (``.reroute``).
        * ``review``    — weak on the assigned subcap and no clearly-better home (an orphan / noise
                          story, OR a sibling that only matches on one coincidental word). Flagged
                          as a low-confidence match, never a confident one, and never moved onto a
                          subcap it does not concern.
        """
        v, n = self._story_vec(story_text)
        assigned = self._cos(v, n, subcap_id)
        pil = self._pillar.get(subcap_id, "")
        best_id, best = subcap_id, assigned
        for cand in self._by_pillar.get(pil, ()):
            if cand == subcap_id:
                continue
            sco = self._cos(v, n, cand)
            if sco > best:
                best, best_id = sco, cand
        if assigned >= floor or (dense_assigned is not None and dense_assigned >= dense_strong):
            return Verdict(assigned, best_id, best, "fit")
        if (
            best >= strong_sibling
            and best >= assigned + margin
            and best_id != subcap_id
            and self._shared_terms(v, best_id) >= min_reroute_terms
        ):
            return Verdict(assigned, best_id, best, "misrouted")
        return Verdict(assigned, best_id, best, "review")
