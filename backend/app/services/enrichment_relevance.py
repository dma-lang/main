"""R7 enrichment NECESSITY gate — is an enrichment relevant/necessary for a TARGET version?

Before an approved enrichment (a new use case first) is SAVED into another version (propagation,
services/enrichment_propagation) or INHERITED into a version at provision (provision._inherit_
enrichment), this gate weighs — DEEPLY, with NLP — whether it genuinely BELONGS under its (mapped)
subcap in that version's catalogue: it must FIT the subcap's meaning AND ADD something the subcap's
existing enrichment does not already cover. A duplicate or a poor fit is judged NOT relevant and is
never written, so we never "enrich the wrong things".

Two-stage, spend-safe (the "deep NLP everywhere" cost engineering):
  1. a cheap deterministic PREFILTER — embed the enrichment + the target subcap text + the subcap's
     existing use cases once (``Gemini.embed``; hermetic = deterministic token-hash, zero spend),
     cosine the fit + the nearest-existing overlap; the clear extremes are auto-decided;
  2. the BORDERLINE band is judged by the live enrich model (``Gemini.infer_relevance``), which
     degrades to the deterministic stub under the G8 throttle — never a hard failure.
Every verdict is CACHED in ``control.enrichment_relevance`` keyed on the enrichment's CONTENT hash,
so a re-provision reuses the decision with NO repeat spend (mirroring the deploy build-marker). The
deterministic floors (``relevance_min_cosine`` / ``overlap_max_cosine`` / ``min_confidence``) are a
hard belt-and-braces override on the model's verdict.
"""

from __future__ import annotations

import hashlib
import math
import re

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.intelligence import gates
from app.intelligence.gemini import Gemini, RelevanceVerdict

_SCHEMA_RE = re.compile(r"^cat_[a-z0-9_]+$")


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def _content_hash(*parts: str) -> str:
    """Stable short hash of the enrichment content + target subcap — the cache key so an EDIT to the
    enrichment re-decides, but an unchanged one (a re-provision) reuses the cached verdict."""
    return hashlib.blake2b("".join(parts).encode(), digest_size=12).hexdigest()


async def _cache_get(
    conn: AsyncConnection, kind: str, key: str, tv: str, ts: str, ch: str
) -> RelevanceVerdict | None:
    row = (
        await conn.execute(
            text(
                "SELECT relevant, confidence, rationale, model, cost_usd "
                "FROM control.enrichment_relevance WHERE kind = :k AND enrichment_key = :ek "
                "AND target_version = :tv AND target_subcap = :ts AND content_hash = :ch"
            ),
            {"k": kind, "ek": key, "tv": tv, "ts": ts, "ch": ch},
        )
    ).first()
    if row is None:
        return None
    return RelevanceVerdict(
        relevant=bool(row[0]),
        confidence=float(row[1] or 0.0),
        rationale=str(row[2] or ""),
        claim_label="INFERENCE",
        model=str(row[3] or "cache"),
        cost_usd=0.0,  # a cache hit spends nothing
    )


async def _cache_put(
    conn: AsyncConnection, kind: str, key: str, tv: str, ts: str, ch: str, v: RelevanceVerdict
) -> None:
    await conn.execute(
        text(
            "INSERT INTO control.enrichment_relevance "
            "(kind, enrichment_key, target_version, target_subcap, content_hash, relevant, "
            "confidence, rationale, model, cost_usd) "
            "VALUES (:k, :ek, :tv, :ts, :ch, :rel, :conf, :rat, :model, :cost) "
            "ON CONFLICT (kind, enrichment_key, target_version, target_subcap, content_hash) "
            "DO NOTHING"
        ),
        {
            "k": kind,
            "ek": key,
            "tv": tv,
            "ts": ts,
            "ch": ch,
            "rel": v.relevant,
            "conf": round(v.confidence, 3),
            "rat": v.rationale,
            "model": v.model,
            "cost": round(v.cost_usd, 6),
        },
    )


async def _existing_use_cases(
    conn: AsyncConnection, schema: str, subcap_id: str, exclude_id: str | None = None
) -> list[tuple[str, str]]:
    """The subcap's EXISTING use cases (name + description) — the overlap/duplicate reference set.
    ``exclude_id`` drops one id (used at inheritance time, where the gated enrichment is already
    inserted, so it must not match ITSELF as a duplicate)."""
    rows = (
        await conn.execute(
            text(
                "SELECT name, coalesce(description, '') FROM "
                f"{schema}.use_case WHERE subcap_id = :s "
                "AND (CAST(:ex AS text) IS NULL OR use_case_id <> :ex) "
                "ORDER BY use_case_id LIMIT 40"
            ),
            {"s": subcap_id, "ex": exclude_id},
        )
    ).all()
    return [(str(r[0]), str(r[1])) for r in rows]


async def relevance(
    conn: AsyncConnection,
    *,
    kind: str,
    enrichment_key: str,
    enrichment_text: str,
    target_version: str,
    target_schema: str,
    target_subcap: str,
    exclude_key: str | None = None,
) -> RelevanceVerdict:
    """Decide whether ``enrichment_text`` (already mapped to ``target_subcap`` in the target schema)
    belongs in ``target_version``. Cache-first (no re-spend on a re-provision); then a deterministic
    cosine prefilter; then the borderline band is judged by deep NLP (or the deterministic gate when
    ``deep_nlp`` is off / the budget is throttled). ``exclude_key`` drops that use_case_id from the
    overlap set (the inheritance post-pass, where the gated enrichment is already inserted). The
    caller writes only when ``relevant``."""
    if not _SCHEMA_RE.match(target_schema):
        raise ValueError("invalid target schema")
    cfg = gates.enrichment_relevance_config()
    # the cache key folds in the gate POLICY, so a threshold recalibration re-decides (rare
    # re-spend) while a stable-config re-provision reuses the verdict (no spend).
    policy = (
        f"{cfg.relevance_min_cosine}:{cfg.overlap_max_cosine}:{cfg.prefilter_low}:"
        f"{cfg.prefilter_high}:{cfg.min_confidence}:{cfg.deep_nlp}"
    )
    ch = _content_hash(kind, enrichment_text, target_subcap, policy)
    cached = await _cache_get(conn, kind, enrichment_key, target_version, target_subcap, ch)
    if cached is not None:
        return cached

    sub = (
        await conn.execute(
            text(
                f"SELECT name, coalesce(description, '') FROM {target_schema}.subcap "
                "WHERE subcap_id = :s"
            ),
            {"s": target_subcap},
        )
    ).first()
    if sub is None:
        # the mapped subcap does not exist here -> no home for the enrichment, not relevant
        v = RelevanceVerdict(
            relevant=False,
            confidence=0.0,
            rationale=f"{target_subcap} is absent from {target_version} — no home for it.",
            claim_label="INFERENCE",
            model="prefilter",
            cost_usd=0.0,
        )
        await _cache_put(conn, kind, enrichment_key, target_version, target_subcap, ch, v)
        return v
    subcap_name, subcap_desc = str(sub[0]), str(sub[1])

    existing = await _existing_use_cases(conn, target_schema, target_subcap, exclude_id=exclude_key)
    gem = Gemini()
    texts = [enrichment_text, f"{subcap_name} {subcap_desc}"] + [f"{n} {d}" for n, d in existing]
    vecs = await gem.embed(texts)
    e_vec, s_vec = vecs[0], vecs[1]
    subcap_cos = _cosine(e_vec, s_vec)
    overlap_cos = max((_cosine(e_vec, ev) for ev in vecs[2:]), default=0.0)

    # 1. deterministic prefilter — auto-decide the clear extremes (no model call)
    if subcap_cos < cfg.prefilter_low:
        v = RelevanceVerdict(
            relevant=False,
            confidence=round(subcap_cos, 3),
            rationale=f"Poor fit for {subcap_name} (similarity {subcap_cos:.0%}) — not added.",
            claim_label="INFERENCE",
            model="prefilter",
            cost_usd=0.0,
        )
    elif subcap_cos >= cfg.prefilter_high and overlap_cos < cfg.overlap_max_cosine:
        v = RelevanceVerdict(
            relevant=True,
            confidence=round(subcap_cos, 3),
            rationale=(
                f"Clear fit for {subcap_name} (similarity {subcap_cos:.0%}) and distinct from its "
                f"existing use cases (nearest {overlap_cos:.0%}) — a relevant addition."
            ),
            claim_label="INFERENCE",
            model="prefilter",
            cost_usd=0.0,
        )
    else:
        # 2. borderline -> deep NLP judgment (or the deterministic gate); infer_relevance itself
        #    degrades to the deterministic stub under the G8 throttle, so this never hard-fails.
        payload = {
            "enrichment": enrichment_text,
            "subcap_name": subcap_name,
            "subcap_desc": subcap_desc,
            "target_subcap": target_subcap,
            "subcap_cosine": subcap_cos,
            "overlap_cosine": overlap_cos,
            "existing": [n for n, _ in existing[:6]],
        }
        if cfg.deep_nlp:
            v = await gem.infer_relevance(payload)
        else:
            v = Gemini._hermetic_infer_relevance(payload)

    # hard belt-and-braces floors on the model's verdict (never write a poor-fit / duplicate / low-
    # confidence enrichment even if the model said relevant).
    hard_ok = (
        v.relevant
        and v.confidence >= cfg.min_confidence
        and subcap_cos >= cfg.relevance_min_cosine
        and overlap_cos < cfg.overlap_max_cosine
    )
    if hard_ok != v.relevant:
        reason = v.rationale
        if not hard_ok:
            reason = (
                f"{v.rationale} (overridden — fit {subcap_cos:.0%} / nearest existing "
                f"{overlap_cos:.0%} / confidence {v.confidence:.0%} did not clear the floors)."
            )
        v = RelevanceVerdict(hard_ok, v.confidence, reason, v.claim_label, v.model, v.cost_usd)

    await _cache_put(conn, kind, enrichment_key, target_version, target_subcap, ch, v)
    return v
