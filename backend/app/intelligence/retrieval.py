"""F6 retrieval — hybrid lexical + structured grounding over the active catalogue version.

Lexical: the subcap ``search`` tsvector (GIN). Structured: scoped to ``cat_<version>``. Dense (HNSW
over the shared ``vector(768)`` space) layers on once the embedding column is populated; the wrapper
shape stays the same so chat / SOW / story matching share one retrieval contract.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


async def retrieve(
    conn: AsyncConnection, schema: str, query: str, k: int = 5
) -> list[dict[str, Any]]:
    """Top-k subcaps for ``query`` in ``schema`` by lexical rank. Empty result => not grounded."""
    sql = text(
        "SELECT s.subcap_id, s.name, s.description, left(s.subcap_id, 2) AS pillar, "
        "ts_rank(s.search, websearch_to_tsquery('english', :q)) AS rank "
        f"FROM {schema}.subcap s "
        "WHERE s.search @@ websearch_to_tsquery('english', :q) "
        "ORDER BY rank DESC, s.subcap_id LIMIT :k"
    )
    rows = (await conn.execute(sql, {"q": query, "k": k})).mappings().all()
    return [dict(r) for r in rows]
