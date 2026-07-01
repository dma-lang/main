"""Story → use-case matcher (B2 Use Case Explorer): attribute each delivered story to a use case.

Carry-forward (F5) maps a Jira story to a **subcap** only, so every use case under a subcap inherits
that subcap's *whole* delivery — the "static number" the Use Case Explorer showed (the same count on
every use case of a subcap, and a drawer that listed the subcap's stories, not the use case's). This
closes that grain: for each subcap, every carried story is scored against that subcap's individual
use cases and assigned to the best-matching one, so per-use-case delivery is **real and grounded**.

The score is a **per-subcap TF-IDF cosine** between the story summary and each use-case title +
description + archetype. The IDF is computed over the subcap's OWN use cases, so a term shared by
all of them (e.g. "case" for a Case-Intake subcap) does not drive the match — only the
*discriminating* terms (triage, dashboard, escalate, …) do. Deterministic (a real vector cosine,
identical under hermetic and live, **zero spend**, bounded by the corpus).

**Grounded only (safeguard 4): nothing is fabricated.** A story is attributed only when it shares a
real discriminating term with a use case; a story whose terse implementation summary genuinely
overlaps none of its subcap's conceptual use cases is LEFT subcap-level (general delivery), never
force-pinned onto a use case. So per-use-case counts are real and differentiated (a match at/above
the floor is ``confirmed``, a weaker overlap is ``review``), and they sum to AT MOST the subcap's
delivery. ``multi_match`` (config) lets a story match several use cases instead of just the best.

Idempotent + version-scoped (DELETE + rebuild), hermetic-safe; runs inside ``stories.carry_forward``
so the deploy self-refresh rebuilds it. A base-only version inherits the reference version's use
cases (same rule the reads use) and matches its OWN carried delivery onto them.
"""

from __future__ import annotations

import logging
import math
import re
from collections import Counter
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app import db
from app.intelligence import gates
from app.intelligence.gemini import Gemini
from app.versioning import resolve_version

logger = logging.getLogger(__name__)

_SCHEMA_RE = re.compile(r"^cat_[a-z0-9_]+$")
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_INSERT_BATCH = 1000
_EMB_BATCH = 256  # embed use-case texts + story summaries in bounded chunks (resilience: bounded)


def _cosine(a: list[float], b: list[float]) -> float:
    """Cosine of two dense embedding vectors (already the embedding space's output)."""
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


async def _embed_all(texts: list[str]) -> list[list[float]]:
    """Embed ``texts`` in bounded batches (gemini-embedding-001; hermetic = deterministic token-
    hash, zero spend). Deduped by the caller so each distinct text is embedded once."""
    gem = Gemini()
    out: list[list[float]] = []
    for i in range(0, len(texts), _EMB_BATCH):
        out.extend(await gem.embed(texts[i : i + _EMB_BATCH]))
    return out


# Lightweight English/Jira stopwords — dropped so the cosine reflects CONTENT-word overlap, not
# boilerplate ("the system shall enable the user to ..."). Kept small + deterministic.
_STOP = frozenset(
    (
        "a an and are as at be by for from has have in into is it its of on or that the their this "
        "to with will shall can able user users system systems story epic feature support supports "
        "provide provides using use used via per across enable enables allow allows new existing"
    ).split()
)


def _tokens(s: str) -> Counter[str]:
    """Content tokens of a text as a term-frequency vector: lowercase, alphanumeric, stopwords and
    very short tokens dropped, a light plural/'s' fold so ``dashboards`` and ``dashboard`` agree."""
    out: Counter[str] = Counter()
    for tok in _TOKEN_RE.findall(s.lower()):
        if len(tok) < 3 or tok in _STOP:
            continue
        if len(tok) > 4 and tok.endswith("s") and not tok.endswith("ss"):
            tok = tok[:-1]
        out[tok] += 1
    return out


def _tfidf(docs: list[Counter[str]]) -> tuple[list[dict[str, float]], list[float]]:
    """TF-IDF weight each use-case doc against its SIBLINGS (the subcap's other use cases), so a
    term shared by every use case of the subcap carries ~no weight and only discriminating terms
    do. Returns the per-doc weighted vectors + their L2 norms (for the per-story cosine)."""
    n = len(docs)
    df: Counter[str] = Counter()
    for d in docs:
        df.update(d.keys())
    vecs: list[dict[str, float]] = []
    norms: list[float] = []
    for d in docs:
        # pure IDF: a term in ALL of the subcap's use cases (df == n) gets weight 0 and is dropped,
        # so only DISCRIMINATING terms drive the match — a story that overlaps a use case only on a
        # word common to every sibling (e.g. "case") does NOT match it. (A single-use-case subcap is
        # handled by the caller: its sole use case takes the subcap's whole delivery.)
        vec = {t: tf * math.log(n / df[t]) for t, tf in d.items() if df[t] < n}
        vecs.append(vec)
        norms.append(math.sqrt(sum(w * w for w in vec.values())))
    return vecs, norms


def _score(
    story: Counter[str], story_norm: float, uc_vec: dict[str, float], uc_norm: float
) -> float:
    """Cosine of the story's term frequencies against a use case's TF-IDF vector."""
    if story_norm == 0.0 or uc_norm == 0.0:
        return 0.0
    dot = sum(tf * uc_vec.get(t, 0.0) for t, tf in story.items())
    return dot / (story_norm * uc_norm) if dot else 0.0


async def _use_case_schema(conn: AsyncConnection, schema: str) -> str:
    """The schema whose ``use_case`` table this version should match against — its own, or the
    reference version's (v7) when it carries none (a base-only version inherits the reference's use
    cases, exactly as the Use Case Explorer reads do)."""
    own = (await conn.execute(text(f"SELECT count(*) FROM {schema}.use_case"))).scalar() or 0
    if own:
        return schema
    from app.services import enrichment_seed

    ref = enrichment_seed.reference_version()
    if not ref:
        return schema
    try:
        ref_v = await resolve_version(ref)
    except Exception:  # noqa: BLE001 - reference not provisioned -> match against own (empty)
        return schema
    ref_s = ref_v.schema_name
    if ref_s == schema or not _SCHEMA_RE.match(ref_s):
        return schema
    ref_has = (await conn.execute(text(f"SELECT count(*) FROM {ref_s}.use_case"))).scalar() or 0
    return ref_s if ref_has else schema


async def match_use_cases(version: str = "v7") -> dict[str, Any]:
    """Rebuild ``control.story_use_case_carry`` for ``version``: assign every carried story that
    genuinely overlaps a use case to the best-matching one. Returns a summary
    ``{version, stories, matched, unmatched, use_cases_covered, review}``."""
    v = await resolve_version(version)
    schema = v.schema_name
    if not _SCHEMA_RE.match(schema):
        raise ValueError("invalid version schema")
    floor, multi = gates.use_case_match_config()
    sem_w, sem_floor = gates.use_case_match_hybrid()  # R6 hybrid: dense weight + attribution floor
    engine = db.require_engine()

    matched = review = 0
    covered: set[str] = set()
    async with engine.begin() as conn:
        ench_s = await _use_case_schema(conn, schema)
        # use cases per subcap, each a TF-IDF vector over title + description + archetype, weighted
        # against the subcap's OWN use cases so only discriminating terms drive the match.
        raw: dict[str, list[tuple[str, Counter[str]]]] = {}
        uc_rows = (
            await conn.execute(
                text(
                    "SELECT subcap_id, use_case_id, coalesce(name, '') AS name, "
                    "coalesce(description, '') AS description, "
                    "replace(coalesce(archetype, ''), '_', ' ') AS arch "
                    f"FROM {ench_s}.use_case ORDER BY subcap_id, use_case_id"
                )
            )
        ).all()
        uc_text: dict[str, str] = {}
        for sub, ucid, name, desc, arch in uc_rows:
            txt = f"{name} {desc} {arch}"
            raw.setdefault(str(sub), []).append((str(ucid), _tokens(txt)))
            uc_text[str(ucid)] = txt
        uc_by_subcap: dict[str, list[tuple[str, dict[str, float], float]]] = {}
        for sub, items in raw.items():
            vecs, norms = _tfidf([d for _, d in items])
            uc_by_subcap[sub] = [(items[i][0], vecs[i], norms[i]) for i in range(len(items))]
        # R6 HYBRID — dense embeddings of the use-case texts, keyed by use_case_id (the semantic
        # half); gemini.embed is the deterministic token-hash stub under hermetic (no spend).
        uc_ids = list(uc_text)
        uc_vecs = await _embed_all([uc_text[u] for u in uc_ids]) if uc_ids else []
        uc_emb = {uc_ids[i]: uc_vecs[i] for i in range(len(uc_ids))}

        # every carried (story, subcap) pair in THIS version, with a WEIGHTED RICH story doc (R8):
        # summary x3 (the headline stays dominant, so attribution never drifts) + description x2 +
        # ac_text x1 (the discriminating "what") — solution_design excluded (too long/noisy). Both
        # the lexical and the dense halves read this doc, so AC/description terms sharpen which use
        # case a story lands on without force-pinning. Aliased `summary` (the loop is unchanged).
        story_rows = (
            await conn.execute(
                text(
                    "SELECT scl.subcap_id, scl.story_key, "
                    "repeat(coalesce(st.summary, '') || ' ', 3) "
                    "|| repeat(coalesce(st.description, '') || ' ', 2) "
                    "|| coalesce(st.ac_text, '') AS summary "
                    "FROM control.story_catalogue_link scl "
                    "JOIN control.story st ON st.story_key = scl.story_key "
                    "WHERE scl.version_id = :ver"
                ),
                {"ver": v.version_id},
            )
        ).all()
        # dense embeddings of the DISTINCT story summaries (each embedded once) — the story half.
        distinct = sorted({str(s) for _, _, s in story_rows if str(s).strip()})
        sum_vecs = await _embed_all(distinct) if distinct else []
        s_emb = {distinct[i]: sum_vecs[i] for i in range(len(distinct))}

        await conn.execute(
            text("DELETE FROM control.story_use_case_carry WHERE target_version = :ver"),
            {"ver": v.version_id},
        )

        rows: list[dict[str, Any]] = []
        unmatched = 0
        for sub, story_key, summary in story_rows:
            ucs = uc_by_subcap.get(str(sub))
            if not ucs:
                continue  # subcap has no use cases -> story stays subcap-level only
            if len(ucs) == 1:
                picks = [(ucs[0][0], 1.0)]  # sole use case of the subcap -> all of its delivery
            else:
                svec = _tokens(summary)
                snorm = math.sqrt(sum(n * n for n in svec.values()))
                svemb = s_emb.get(str(summary))
                cand: list[tuple[float, str]] = []
                for ucid, vec, norm in ucs:
                    lex = _score(svec, snorm, vec, norm)  # lexical TF-IDF cosine
                    emb = _cosine(svemb, uc_emb[ucid]) if svemb and ucid in uc_emb else 0.0
                    combined = (1.0 - sem_w) * lex + sem_w * emb
                    # attribute on a shared discriminating TERM (preserves the unmatched set the
                    # gap detector needs) OR a STRONG semantic match (a summary that MEANS the same
                    # as a use case without sharing a word); baseline embedding noise stays out.
                    if lex > 0.0 or emb >= sem_floor:
                        cand.append((combined, ucid))
                cand.sort(key=lambda kv: (-kv[0], kv[1]))  # best combined, then lowest id
                picks = (
                    [(uid, sc) for sc, uid in cand]
                    if multi
                    else ([(cand[0][1], cand[0][0])] if cand else [])
                )
            if not picks:
                unmatched += 1
                continue
            for ucid, sc in picks:
                status = "confirmed" if sc >= floor else "review"
                if status == "review":
                    review += 1
                rows.append(
                    {
                        "story_key": str(story_key),
                        "target_version": v.version_id,
                        "use_case_id": ucid,
                        "subcap_id": str(sub),
                        "score": round(float(sc), 4),
                        "via": "use_case_hybrid",
                        "status": status,
                    }
                )
                covered.add(ucid)
                matched += 1

        for i in range(0, len(rows), _INSERT_BATCH):
            await conn.execute(
                text(
                    "INSERT INTO control.story_use_case_carry "
                    "(story_key, target_version, use_case_id, subcap_id, score, via, status) "
                    "VALUES (:story_key, :target_version, :use_case_id, :subcap_id, :score, "
                    ":via, CAST(:status AS carry_status))"
                ),
                rows[i : i + _INSERT_BATCH],
            )

    return {
        "version": v.version_id,
        "stories": len(story_rows),
        "matched": matched,
        "unmatched": unmatched,
        "use_cases_covered": len(covered),
        "review": review,
    }
