"""Client journey atlas (F3, FR-19) — entity-resolved clients + their delivery journey.

A client is the union of identities across the two delivery records: `sow_document.account_key`
(the contractual side) and `control.story.project_key` (the Jira delivery side) — the SOW corpus
keys on the REAL project keys, so resolution is a deterministic key join, never a fuzzy auto-merge
(an ambiguous name stays two clients until a human merges). The journey is every dated event for
the key: SOW signings and their gated scope matches, plus the delivery footprint (stories +
subcaps touched, undated — the corpus carries no per-story dates).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

from app import db
from app.versioning import resolve_version


async def list_clients(version: str) -> list[dict[str, Any]]:
    v = await resolve_version(version)
    engine = db.require_engine()
    sql = text(
        "WITH keys AS ("
        "  SELECT account_key AS k FROM control.sow_document "
        "  UNION SELECT project_key FROM control.story WHERE project_key IS NOT NULL"
        "), agg AS ("
        "  SELECT k.k AS key, "
        "  (SELECT count(*) FROM control.sow_document d WHERE d.account_key = k.k) AS sows, "
        "  (SELECT count(*) FROM control.sow_scope_item si "
        "   JOIN control.sow_document d ON d.sow_id = si.sow_id "
        "   WHERE d.account_key = k.k) AS scope_items, "
        "  (SELECT count(*) FROM control.story st WHERE st.project_key = k.k) AS stories, "
        "  (SELECT count(DISTINCT l.subcap_id) FROM control.story st "
        "   JOIN control.story_catalogue_link l ON l.story_key = st.story_key "
        "   AND l.version_id = :v WHERE st.project_key = k.k) AS subcaps_touched, "
        "  (SELECT max(d.signed_date)::text FROM control.sow_document d "
        "   WHERE d.account_key = k.k) AS last_sow "
        "  FROM keys k"
        ") SELECT * FROM agg WHERE sows > 0 OR stories > 0 "
        "ORDER BY stories DESC, sows DESC LIMIT 40"
    )
    async with engine.connect() as conn:
        rows = (await conn.execute(sql, {"v": v.version_id})).mappings().all()
    return [dict(r) for r in rows]


async def client_journey(key: str, version: str) -> dict[str, Any] | None:
    """Dated SOW/match events + the delivery footprint for one entity-resolved client key."""
    v = await resolve_version(version)
    engine = db.require_engine()
    async with engine.connect() as conn:
        stories = (
            await conn.execute(
                text("SELECT count(*) FROM control.story WHERE project_key = :k"), {"k": key}
            )
        ).scalar() or 0
        sows = (
            (
                await conn.execute(
                    text(
                        "SELECT sow_id::text AS sow_id, title, sv_code, "
                        "signed_date::text AS signed_date, status "
                        "FROM control.sow_document WHERE account_key = :k "
                        "ORDER BY signed_date"
                    ),
                    {"k": key},
                )
            )
            .mappings()
            .all()
        )
        if not sows and not stories:
            return None
        matches = (
            (
                await conn.execute(
                    text(
                        "SELECT m.subcap_id, m.similarity::float AS similarity, m.status, "
                        "m.claim_label::text AS claim_label, m.chain_id::text AS chain_id, "
                        "d.signed_date::text AS date, si.clause, "
                        f"(SELECT s.name FROM {v.schema_name}.subcap s "
                        "WHERE s.subcap_id = m.subcap_id) AS subcap_name "
                        "FROM control.sow_subcap_match m "
                        "JOIN control.sow_scope_item si ON si.scope_id = m.scope_id "
                        "JOIN control.sow_document d ON d.sow_id = si.sow_id "
                        "WHERE d.account_key = :k AND m.version_id = :v "
                        "AND m.status IN ('confirmed', 'review') "
                        "ORDER BY d.signed_date, si.ordinal"
                    ),
                    {"k": key, "v": v.version_id},
                )
            )
            .mappings()
            .all()
        )
        top_delivery = (
            (
                await conn.execute(
                    text(
                        "SELECT l.subcap_id, count(*) AS stories, "
                        f"(SELECT s.name FROM {v.schema_name}.subcap s "
                        "WHERE s.subcap_id = l.subcap_id) AS subcap_name "
                        "FROM control.story st "
                        "JOIN control.story_catalogue_link l ON l.story_key = st.story_key "
                        "AND l.version_id = :v "
                        "WHERE st.project_key = :k "
                        "GROUP BY l.subcap_id ORDER BY stories DESC LIMIT 8"
                    ),
                    {"k": key, "v": v.version_id},
                )
            )
            .mappings()
            .all()
        )
    return {
        "key": key,
        "stories": int(stories),
        "sows": [dict(r) for r in sows],
        "matches": [dict(r) for r in matches],
        "top_delivery": [dict(r) for r in top_delivery],
    }
