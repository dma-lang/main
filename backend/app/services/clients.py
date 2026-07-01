"""Client journey atlas (F3, FR-19) — entity-resolved clients + their delivery journey.

A client is identified by its RESOLVED name (`control.story.client_name`, from the authoritative
story catalog), falling back to `project_key` for rows that carry no resolved name (synthetic /
unmatched) and to `sow_document.account_key` for SOW-only accounts — so a story is grouped under its
real client (e.g. "Academy Bank"), never a bare project/story id, while `story_key` stays the
per-story id in every drilldown. Resolution is still a deterministic key join (client_name links a
client's several project_keys; SOWs key on the real project_key), never a fuzzy auto-merge — an
ambiguous name stays two clients until a human merges. The journey is every dated event for the
client: SOW signings and their gated scope matches, plus the delivery footprint (stories + subcaps
touched, undated — the corpus carries no per-story dates).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

from app import db
from app.versioning import resolve_version

# a story's client identity: the resolved client_name, else its project_key (never the story_key).
_CLIENT = "coalesce(st.client_name, st.project_key)"
# a SOW's client identity: the client_name of a story sharing its account_key (project_key), else
# the account_key itself — so a contractual account maps onto the same client as its Jira delivery.
_SOW_CLIENT = (
    "coalesce((SELECT s.client_name FROM control.story s "
    "WHERE s.project_key = d.account_key AND s.client_name IS NOT NULL LIMIT 1), d.account_key)"
)


async def list_clients(version: str) -> list[dict[str, Any]]:
    v = await resolve_version(version)
    engine = db.require_engine()
    sql = text(
        "WITH sc AS ("
        f"  SELECT st.story_key, st.project_key, {_CLIENT} AS client, st.client_name, "
        "   st.salesforce_account_id, st.client_match_confidence "
        f"  FROM control.story st WHERE {_CLIENT} IS NOT NULL"
        "), sowc AS ("
        f"  SELECT d.sow_id, {_SOW_CLIENT} AS client FROM control.sow_document d"
        "), keys AS (SELECT DISTINCT client FROM sc UNION SELECT DISTINCT client FROM sowc), "
        "agg AS ("
        "  SELECT k.client AS key, "
        "  (SELECT max(sc.client_name) FROM sc WHERE sc.client = k.client) AS client_name, "
        "  (SELECT max(sc.salesforce_account_id) FROM sc WHERE sc.client = k.client) "
        "    AS salesforce_account_id, "
        "  (SELECT max(sc.client_match_confidence) FROM sc WHERE sc.client = k.client) "
        "    AS client_match_confidence, "
        "  (SELECT count(*) FROM sowc w WHERE w.client = k.client) AS sows, "
        "  (SELECT count(*) FROM control.sow_scope_item si JOIN sowc w ON w.sow_id = si.sow_id "
        "   WHERE w.client = k.client) AS scope_items, "
        "  (SELECT count(*) FROM sc WHERE sc.client = k.client) AS stories, "
        "  (SELECT count(DISTINCT sc.project_key) FROM sc WHERE sc.client = k.client) AS projects, "
        "  (SELECT count(DISTINCT l.subcap_id) FROM sc "
        "   JOIN control.story_catalogue_link l ON l.story_key = sc.story_key "
        "   AND l.version_id = :v WHERE sc.client = k.client) AS subcaps_touched, "
        "  (SELECT max(d.signed_date)::text FROM sowc w "
        "   JOIN control.sow_document d ON d.sow_id = w.sow_id "
        "   WHERE w.client = k.client) AS last_sow "
        "  FROM keys k"
        ") SELECT * FROM agg WHERE sows > 0 OR stories > 0 "
        "ORDER BY stories DESC, sows DESC LIMIT 40"
    )
    async with engine.connect() as conn:
        rows = (await conn.execute(sql, {"v": v.version_id})).mappings().all()
    return [dict(r) for r in rows]


async def client_journey(key: str, version: str) -> dict[str, Any] | None:
    """Dated SOW/match events + the delivery footprint for one entity-resolved client. ``key`` is
    the client identity (a resolved client_name, or a project_key fallback); ``story_key`` stays the
    per-story id inside the footprint."""
    v = await resolve_version(version)
    engine = db.require_engine()
    async with engine.connect() as conn:
        head_row = (
            (
                await conn.execute(
                    text(
                        "SELECT count(*) AS stories, max(st.client_name) AS client_name, "
                        "max(st.salesforce_account_id) AS salesforce_account_id, "
                        "max(st.client_match_confidence) AS client_match_confidence "
                        f"FROM control.story st WHERE {_CLIENT} = :k"
                    ),
                    {"k": key},
                )
            )
            .mappings()
            .first()
        )
        hd: dict[str, Any] = dict(head_row) if head_row is not None else {}
        stories = int(hd.get("stories") or 0)
        sows = (
            (
                await conn.execute(
                    text(
                        "SELECT d.sow_id::text AS sow_id, d.title, d.sv_code, "
                        "d.signed_date::text AS signed_date, d.status "
                        f"FROM control.sow_document d WHERE {_SOW_CLIENT} = :k "
                        "ORDER BY d.signed_date"
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
                        f"WHERE {_SOW_CLIENT} = :k AND m.version_id = :v "
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
                        f"WHERE {_CLIENT} = :k "
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
        "client_name": hd.get("client_name"),
        "salesforce_account_id": hd.get("salesforce_account_id"),
        "client_match_confidence": hd.get("client_match_confidence"),
        "stories": stories,
        "sows": [dict(r) for r in sows],
        "matches": [dict(r) for r in matches],
        "top_delivery": [dict(r) for r in top_delivery],
    }
