"""F6 — populate the shared vector(768) embedding space (R2 Phase B).

Idempotent, metered, bounded one-shot: embed every ``cat_<v>.subcap`` that has no embedding yet
(name + description) into the gemini-embedding-001 space and store it for HNSW cosine retrieval.
Hermetic mode uses the deterministic token-hash stub (no spend); live mode meters the batch cost on
a ``reasoning_chain`` so the G8 envelope sees it. Re-running only fills gaps — it never re-embeds —
so it is safe to schedule and safe to retry (safeguard 9: idempotent, bounded).
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import text

from app import db
from app.intelligence import model_config
from app.intelligence.gemini import Gemini
from app.settings import get_settings
from app.versioning import resolve_version

_SCHEMA_RE = re.compile(r"^cat_[a-z0-9_]+$")
_BATCH = 64


def _est_tokens(texts: list[str]) -> int:
    return sum(len(t) for t in texts) // 4  # ~4 chars per token (estimate for the envelope meter)


async def build_embeddings(version: str, batch: int = _BATCH) -> dict[str, Any]:
    """Embed every un-embedded subcap in the version into ``cat_<v>.subcap.embedding``. Returns
    ``{version, schema, embedded, cost}``; ``embedded`` is 0 on a fully-embedded version (no-op)."""
    v = await resolve_version(version)
    schema = v.schema_name
    if not _SCHEMA_RE.match(schema):
        raise ValueError("invalid version schema")
    engine = db.require_engine()
    gemini = Gemini()
    _, _dim = model_config.embedding_model()
    embed_rate = model_config.token_price()[1]
    embedded = 0
    cost = 0.0
    async with engine.begin() as conn:
        rows = (
            (
                await conn.execute(
                    text(
                        "SELECT subcap_id, coalesce(name, '') AS name, "
                        "coalesce(description, '') AS description "
                        f"FROM {schema}.subcap WHERE embedding IS NULL ORDER BY subcap_id"
                    )
                )
            )
            .mappings()
            .all()
        )
        for i in range(0, len(rows), batch):
            chunk = rows[i : i + batch]
            texts = [f"{r['name']} {r['description']}".strip() for r in chunk]
            vecs = await gemini.embed(texts)
            cost += _est_tokens(texts) / 1000.0 * embed_rate
            for r, vec in zip(chunk, vecs, strict=True):
                lit = "[" + ",".join(f"{x:.6f}" for x in vec) + "]"
                await conn.execute(
                    text(
                        f"UPDATE {schema}.subcap SET embedding = CAST(:vec AS vector) "
                        "WHERE subcap_id = :id"
                    ),
                    {"vec": lit, "id": r["subcap_id"]},
                )
                embedded += 1
        cost = round(cost, 6)
        if embedded and not get_settings().is_hermetic and cost > 0:
            emb_model, _ = model_config.embedding_model()
            await conn.execute(
                text(
                    "INSERT INTO control.reasoning_chain "
                    "(operation, subject_ref, claim_label, summary, model, cost_usd) "
                    "VALUES ('embedding', :subj, 'FACT', :summary, :model, :cost)"
                ),
                {
                    "subj": f"{schema}:embeddings",
                    "summary": f"Embedded {embedded} subcaps in {schema}.",
                    "model": emb_model,
                    "cost": cost,
                },
            )
    return {"version": v.version_id, "schema": schema, "embedded": embedded, "cost": cost}
