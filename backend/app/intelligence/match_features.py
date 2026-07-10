"""Story<->subcap match features — the ONE feature definition shared by training and runtime.

The trained matcher (config/matcher_model.json, produced by scripts/train_matcher.py against the
author-curated golden benchmark) is a linear model over exactly these features, so this module is
the contract: the trainer computes them for labelled pairs, the relatedness gate computes them for
live carries, and the exported coefficients only make sense if both sides agree. Deterministic,
in-process, zero spend — the dense half is the local MiniLM (intelligence/local_embeddings); when
the model files are absent ``MatchFeaturizer.available`` is False and callers keep today's
lexical-only behaviour.

Features (names are stored in the model JSON and validated at load):
* ``dense_cos``    — MiniLM cosine(story text, subcap definition text). The semantic signal.
* ``dense_margin`` — dense_cos minus the best OTHER same-pillar subcap's dense cosine.
* ``dense_z``      — dense_cos z-scored against the story's cosine field over ALL subcaps: "how
                     unusually close is THIS subcap for THIS story" (calibrates terse stories
                     whose absolute cosines run low across the board).
* ``uc_dense``     — max MiniLM cosine(story, the subcap's USE-CASE texts). Use cases speak
                     implementation language ("configure…", "automate…"), far closer to terse
                     Jira summaries than the abstract capability description.
* ``uc_margin``    — uc_dense minus the best other same-pillar subcap's uc_dense.
* ``lex_cos``      — the production TF-IDF relatedness (story_relatedness.RelatednessIndex).
* ``lex_margin``   — lex_cos minus the best other same-pillar lexical cosine.
* ``shared_terms`` — discriminating shared-term count, capped at 8, scaled 0..1 (the single-word-
                     coincidence guard, as a graded signal).
* ``name_overlap`` — fraction of the subcap NAME's content tokens present in the story text.
* ``ex_top``       — max MiniLM cosine(story, the candidate's author-curated EXEMPLAR stories).
                     The strongest signal (AUC 0.75 alone): stories genuinely delivering the same
                     capability resemble each other even when the capability's abstract definition
                     matches neither. Exemplars are catalogue data (the authors' per-subcap story
                     refs), so this is legitimate runtime input; training excludes same-project
                     exemplars so the benchmark stays leakage-free.
* ``ex_mean3``     — mean of the top-3 exemplar cosines (robust to a single lucky neighbour).
* ``has_ex``       — 1 when usable exemplars exist for the candidate. Separates "no exemplar
                     evidence available" (ex_top = 0 by absence) from "exemplars disagree"
                     (ex_top = 0 by dissimilarity) — two different worlds for the classifier.
* ``n_ex_log``     — log1p(#usable exemplars)/4: confidence in the exemplar evidence.
* ``uc_x_noex``    — uc_dense in the NO-exemplar regime (uc_dense * (1 - has_ex)): lets the model
                     weigh use-case similarity differently when exemplar evidence is absent.
* ``dense_x_noex`` — dense_cos in the NO-exemplar regime, same rationale.
"""

from __future__ import annotations

import ast
import math
from typing import Any

from app.services.story_relatedness import RelatednessIndex, story_doc
from app.services.use_case_match import _tokens

FEATURES = [
    "dense_cos",
    "dense_margin",
    "dense_z",
    "uc_dense",
    "uc_margin",
    "lex_cos",
    "lex_margin",
    "shared_terms",
    "name_overlap",
    "ex_top",
    "ex_mean3",
    "has_ex",
    "n_ex_log",
    "uc_x_noex",
    "dense_x_noex",
]


def subcap_text(sub: dict[str, Any]) -> str:
    """Natural-language subcap definition for the sentence model (no bag-of-words repeats —
    transformers don't need term weighting, they need fluent text)."""
    name = str(sub.get("name") or "")
    cluster = str(sub.get("cluster") or sub.get("l2") or "")
    desc = str(sub.get("desc") or sub.get("description") or "")
    return ". ".join(p for p in (name, cluster, desc) if p)


def story_text(story: dict[str, Any]) -> str:
    """Natural-language story text for the sentence model: summary first (the tokenizer truncates
    at 256 tokens, so the headline always survives), then description and acceptance criteria."""
    summary = str(story.get("sum") or story.get("summary") or "")
    desc = str(story.get("desc") or story.get("description") or "")
    ac = str(story.get("act") or story.get("ac_text") or "")
    return ". ".join(p for p in (summary, desc, ac) if p)


class MatchFeaturizer:
    """Feature computer over one catalogue version's subcap definitions (+ use-case texts).

    Build once per carry/training run — it encodes every definition and use-case text through
    MiniLM once and keeps numpy matrices, so per-pair features are pure vector math. Story vectors
    come from one batched ``encode_stories`` call and are passed into ``features``."""

    def __init__(
        self,
        defs: list[dict[str, Any]],
        exemplars: dict[str, list[dict[str, Any]]] | None = None,
    ) -> None:
        """``exemplars``: per-subcap author-curated exemplar STORIES (each dict a corpus story row
        — its text is embedded; its project key retained so training can exclude same-project
        exemplars). Omit to score without the exemplar features (they read 0.0)."""
        from app.intelligence import local_embeddings

        self._defs = {str(d.get("id") or d.get("subcap_id")): d for d in defs}
        self._lex = RelatednessIndex(defs)
        self._ids = list(self._defs)
        self._pos = {sid: i for i, sid in enumerate(self._ids)}
        self._pillar = {sid: str(d.get("pillar") or sid[:2]) for sid, d in self._defs.items()}
        self._name_tokens = {
            sid: set(_tokens(str(d.get("name") or ""))) for sid, d in self._defs.items()
        }
        self.available = local_embeddings.available()
        self._dmat: Any = None  # (n_subcaps, dim) definition vectors
        self._pmask: dict[str, Any] = {}  # pillar -> boolean mask over subcap rows
        self._uc_owner: Any = None  # (n_uc_texts,) row -> subcap index
        self._ucmat: Any = None  # (n_uc_texts, dim) use-case text vectors
        if not self.available:
            return
        import numpy as np

        dvecs = local_embeddings.encode([subcap_text(self._defs[i]) for i in self._ids])
        if dvecs is None:
            self.available = False
            return
        self._dmat = np.asarray(dvecs)
        pillars = np.asarray([self._pillar[sid] for sid in self._ids])
        for p in sorted(set(pillars.tolist())):
            self._pmask[p] = pillars == p
        uc_texts: list[str] = []
        owners: list[int] = []
        for i, sid in enumerate(self._ids):
            for t in _uc_texts(self._defs[sid]):
                uc_texts.append(t)
                owners.append(i)
        if uc_texts:
            ucv = local_embeddings.encode(uc_texts)
            if ucv is not None:
                self._ucmat = np.asarray(ucv)
                self._uc_owner = np.asarray(owners)
        # exemplar stories: one matrix per subcap + each exemplar's project key (leakage-safe
        # training) and story key (a story never matches ITSELF as its own exemplar); a story is
        # embedded once even when it exemplifies several subcaps
        self._ex: dict[str, tuple[Any, list[str], list[str]]] = {}
        if exemplars:
            uniq: dict[str, dict[str, Any]] = {}
            for rows_ in exemplars.values():
                for st in rows_:
                    uniq[str(st.get("k") or st.get("story_key"))] = st
            ex_keys = sorted(uniq)
            ex_vecs = local_embeddings.encode([story_text(uniq[k]) for k in ex_keys])
            if ex_vecs is not None:
                mat = np.asarray(ex_vecs)
                pos = {k: i for i, k in enumerate(ex_keys)}
                for sid, rows_ in exemplars.items():
                    keys = [str(st.get("k") or st.get("story_key")) for st in rows_]
                    projects = [
                        str(uniq[k].get("pk") or uniq[k].get("project_key") or "") for k in keys
                    ]
                    self._ex[sid] = (mat[[pos[k] for k in keys]], projects, keys)

    def encode_stories(self, stories: list[dict[str, Any]]) -> list[list[float]] | None:
        """Batch-encode story texts (order-aligned with the input); None when MiniLM is absent."""
        if not self.available:
            return None
        from app.intelligence import local_embeddings

        return local_embeddings.encode([story_text(s) for s in stories])

    def features(
        self,
        story: dict[str, Any],
        subcap_id: str,
        story_vec: list[float] | None,
        *,
        exclude_project: str | None = None,
    ) -> dict[str, float] | None:
        """The FEATURES dict for one (story, subcap) pair, or None when the pair can't be scored
        (unknown subcap, or the dense half is unavailable). ``exclude_project`` drops exemplars
        from that Jira project (training-time leakage guard; runtime passes None)."""
        if subcap_id not in self._pos or story_vec is None or self._dmat is None:
            return None
        import numpy as np

        i = self._pos[subcap_id]
        sv = np.asarray(story_vec)[: self._dmat.shape[1]]
        field = self._dmat @ sv  # cosine vs every subcap (vectors are L2-normalised)
        dense = float(field[i])
        dense_z = float((dense - field.mean()) / (field.std() or 1.0))
        pmask = self._pmask.get(self._pillar[subcap_id])
        if pmask is not None and pmask.sum() > 1:
            others = field[pmask & (np.arange(len(field)) != i)]
            dense_margin = dense - float(others.max())
        else:
            dense_margin = 0.0
        uc_dense = uc_margin = 0.0
        if self._ucmat is not None:
            uc_field = self._ucmat @ sv[: self._ucmat.shape[1]]
            per_sub = np.zeros(len(self._ids))
            np.maximum.at(per_sub, self._uc_owner, uc_field)
            uc_dense = float(per_sub[i])
            if pmask is not None and pmask.sum() > 1:
                uothers = per_sub[pmask & (np.arange(len(per_sub)) != i)]
                uc_margin = uc_dense - float(uothers.max())
        text = story_doc(story)
        v, n = self._lex._story_vec(text)  # noqa: SLF001 - shared production vectors
        lex = self._lex._cos(v, n, subcap_id)  # noqa: SLF001
        best_lex = 0.0
        for cand in self._ids:
            if cand == subcap_id or self._pillar[cand] != self._pillar[subcap_id]:
                continue
            lc = self._lex._cos(v, n, cand)  # noqa: SLF001
            if lc > best_lex:
                best_lex = lc
        shared = self._lex._shared_terms(v, subcap_id)  # noqa: SLF001
        name_toks = self._name_tokens.get(subcap_id) or set()
        story_toks = set(_tokens(text))
        name_overlap = len(name_toks & story_toks) / len(name_toks) if name_toks else 0.0
        ex_top = ex_mean3 = 0.0
        n_ex = 0
        ex = self._ex.get(subcap_id)
        if ex is not None:
            mat, projects, ex_keys = ex
            self_key = str(story.get("k") or story.get("story_key") or "")
            # never match a story against ITSELF as its own exemplar (cosine-1.0 tautology), and
            # optionally exclude the story's whole project (training leakage guard)
            keep = [
                j
                for j, (p, kk) in enumerate(zip(projects, ex_keys, strict=True))
                if kk != self_key and (exclude_project is None or p != exclude_project)
            ]
            n_ex = len(keep)
            if keep:
                sims = mat[keep] @ sv[: mat.shape[1]]
                ex_top = float(np.max(sims))
                ex_mean3 = float(np.mean(np.sort(sims)[-3:]))
        has_ex = 1.0 if n_ex else 0.0
        return {
            "dense_cos": dense,
            "dense_margin": dense_margin,
            "dense_z": dense_z,
            "uc_dense": uc_dense,
            "uc_margin": uc_margin,
            "lex_cos": lex,
            "lex_margin": lex - best_lex,
            "shared_terms": min(shared, 8) / 8.0,
            "name_overlap": name_overlap,
            "ex_top": ex_top,
            "ex_mean3": ex_mean3,
            "has_ex": has_ex,
            "n_ex_log": math.log1p(n_ex) / 4.0,
            "uc_x_noex": uc_dense * (1.0 - has_ex),
            "dense_x_noex": dense * (1.0 - has_ex),
        }


def _uc_texts(sub: dict[str, Any]) -> list[str]:
    """The subcap's use-case texts. Reads the seed's stringified list (``uc``) and the runtime
    shape (``uc_texts`` prepared by the caller from cat_<v>.use_case)."""
    if isinstance(sub.get("uc_texts"), list):
        return [str(t) for t in sub["uc_texts"] if t]
    raw = sub.get("uc")
    items: list[Any]
    if isinstance(raw, list):
        items = raw
    elif isinstance(raw, str) and raw.strip().startswith("["):
        try:
            items = ast.literal_eval(raw)
        except (ValueError, SyntaxError):
            items = []
    else:
        items = []
    out = []
    for u in items:
        if isinstance(u, dict) and u.get("text"):
            out.append(str(u["text"]))
        elif isinstance(u, str) and u:
            out.append(u)
    return out


def defs_from_catalogue(subs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Seed-catalogue subcaps -> the def shape both the lexical index and featurizer read (matches
    the production gate's DB query: name + L2 cluster + description + use-case texts)."""
    return [
        {
            "id": s["id"],
            "name": s.get("name") or "",
            "l2": s.get("cluster") or "",
            "description": s.get("desc") or "",
            "pillar": str(s["id"])[:2],
            "uc_texts": _uc_texts(s),
        }
        for s in subs
    ]
