"""F6 retrieval — hybrid lexical + dense grounding over the active catalogue version.

Lexical: the subcap ``search`` tsvector (GIN). Dense: HNSW cosine over the shared ``vector(768)``
space, once the embedding column is populated (services/embeddings.py). The two are merged and
reranked; when a version has no embeddings the dense half is a no-op and retrieval is pure lexical —
the return contract is identical either way, so chat / SOW / story matching share one shape.
"""

import re
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.intelligence.gemini import Gemini

_TOKEN = re.compile(r"[A-Za-z0-9]{2,}")


def _or_query(question: str) -> str:
    """Turn a question into an OR tsquery (recall over AND); websearch_to_tsquery parses it safely
    and drops stopwords, so a broad question still matches and ranks by term overlap."""
    return " OR ".join(_TOKEN.findall(question))


async def _lexical(conn: AsyncConnection, schema: str, query: str, k: int) -> list[dict[str, Any]]:
    web = _or_query(query)
    if not web:
        return []
    sql = text(
        "SELECT s.subcap_id, s.name, s.description, left(s.subcap_id, 2) AS pillar, "
        "ts_rank(s.search, websearch_to_tsquery('english', :q)) AS rank "
        f"FROM {schema}.subcap s "
        "WHERE s.search @@ websearch_to_tsquery('english', :q) "
        "ORDER BY rank DESC, s.subcap_id LIMIT :k"
    )
    return [dict(r) for r in (await conn.execute(sql, {"q": web, "k": k})).mappings().all()]


async def _dense(conn: AsyncConnection, schema: str, query: str, k: int) -> list[dict[str, Any]]:
    """Top-k subcaps by cosine in the shared embedding space; [] when no embeddings are populated
    (or the query embedding fails) so retrieval degrades cleanly to lexical."""
    try:
        qvec = (await Gemini().embed([query]))[0]
    except Exception:  # noqa: BLE001 - a live embed failure degrades to lexical, never crashes chat
        return []
    if not qvec:
        return []
    lit = "[" + ",".join(f"{x:.6f}" for x in qvec) + "]"
    sql = text(
        "SELECT s.subcap_id, s.name, s.description, left(s.subcap_id, 2) AS pillar, "
        "1 - (s.embedding <=> CAST(:qv AS vector)) AS cosine "
        f"FROM {schema}.subcap s WHERE s.embedding IS NOT NULL "
        "ORDER BY s.embedding <=> CAST(:qv AS vector) ASC, s.subcap_id LIMIT :k"
    )
    return [dict(r) for r in (await conn.execute(sql, {"qv": lit, "k": k})).mappings().all()]


async def retrieve(
    conn: AsyncConnection, schema: str, query: str, k: int = 5
) -> list[dict[str, Any]]:
    """Top-k subcaps for ``query`` — lexical ∪ dense, reranked by a combined lexical+cosine score.
    Empty result => not grounded. Falls back to pure lexical when the version has no embeddings."""
    lexical = await _lexical(conn, schema, query, k)
    dense = await _dense(conn, schema, query, k)
    if not dense:
        return lexical  # no embeddings (or embed unavailable) -> unchanged lexical behaviour
    merged: dict[str, dict[str, Any]] = {}
    for r in lexical:
        merged[r["subcap_id"]] = {**r, "lex": float(r.get("rank") or 0.0), "cos": 0.0}
    for r in dense:
        row = merged.get(r["subcap_id"])
        if row is not None:
            row["cos"] = float(r["cosine"])
        else:
            merged[r["subcap_id"]] = {**r, "lex": 0.0, "cos": float(r["cosine"])}
    out = list(merged.values())
    out.sort(key=lambda x: 0.5 * x["cos"] + 0.5 * min(1.0, x["lex"]), reverse=True)
    return out[:k]
