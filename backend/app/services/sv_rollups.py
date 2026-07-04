"""R8 per-subvertical rollups — read-time SV tailoring, precomputed.

For each subcap and use case, precompute per-(entity x subvertical) delivery aggregates so a surface
viewed under a subvertical lens shows the representative stories + a narrative drawn from THAT
subvertical's own delivery (framed in its language), falling back to an all-SV canonical rollup when
no lens is set. Deterministic, idempotent (version-scoped rebuild), bounded (only entity/SV pairs
that actually have delivery), hermetic-safe (no spend). Built best-effort in carry_forward after
story synthesis; read via ``get`` with the all-SV fallback.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app import db
from app.services.sv_aliases import normalize_sv_code

_REP = 5  # representative stories kept per (entity x SV)

# subcap grain: the version's carried delivery, joined to the story's own client + SV + narrative.
_SUBCAP_SQL = (
    "SELECT scl.subcap_id AS entity, coalesce(st.story_sv_code, '') AS sv, st.story_key, "
    "st.client_name, st.composite_score, st.narrative "
    "FROM control.story_catalogue_link scl JOIN control.story st ON st.story_key = scl.story_key "
    "WHERE scl.version_id = :ver AND NOT st.is_synthetic"
)
# use-case grain: the matched story<->use-case links (real per-use-case delivery).
_USECASE_SQL = (
    "SELECT sul.use_case_id AS entity, coalesce(st.story_sv_code, '') AS sv, st.story_key, "
    "st.client_name, st.composite_score, st.narrative "
    "FROM control.story_use_case_link sul JOIN control.story st ON st.story_key = sul.story_key "
    "WHERE sul.version_id = :ver AND NOT st.is_synthetic"
)


def _narrative(sv: str, rows: list[dict[str, Any]]) -> str:
    """A deterministic SV-tailored rollup line: the delivery scale + the top representative story's
    own narrative (already SV-role-substituted at synthesis)."""
    clients = len({r["client_name"] for r in rows if r["client_name"]})
    where = f"For {sv}, " if sv else "Across all subverticals, "
    scale = f"{len(rows)} stories across {clients} client(s) delivered this."
    top = next((r["narrative"] for r in rows if r.get("narrative")), "")
    return f"{where}{scale} {top}".strip()[:900]


def _aggregate(version_id: str, kind: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group rows into per-(entity, sv) rollups PLUS the per-entity all-SV canonical row."""
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for r in rows:
        entity = str(r["entity"])
        sv = normalize_sv_code(r["sv"]) or ""
        groups.setdefault((entity, sv), []).append(r)
        groups.setdefault((entity, ""), []).append(r)  # all-SV canonical (dedup handled below)
    # the '' bucket double-counts (a story is added once for its SV and once for ''); de-dup by key
    out: list[dict[str, Any]] = []
    for (entity, sv), grp in groups.items():
        uniq = list({r["story_key"]: r for r in grp}.values())
        uniq.sort(key=lambda r: (-(r["composite_score"] or 0.0), r["story_key"]))
        out.append(
            {
                "version_id": version_id,
                "entity_kind": kind,
                "entity_id": entity,
                "subvertical": sv,
                "story_count": len(uniq),
                "client_count": len({r["client_name"] for r in uniq if r["client_name"]}),
                "rep_story_keys": json.dumps([r["story_key"] for r in uniq[:_REP]]),
                "narrative": _narrative(sv, uniq),
            }
        )
    return out


async def build_rollups(version_id: str) -> dict[str, int]:
    """Rebuild the per-SV rollups for one version (delete + insert, idempotent). Best-effort."""
    engine = db.require_engine()
    p = {"ver": version_id}
    async with engine.connect() as conn:
        sub_rows = [dict(r) for r in (await conn.execute(text(_SUBCAP_SQL), p)).mappings()]
        uc_rows = [dict(r) for r in (await conn.execute(text(_USECASE_SQL), p)).mappings()]
    payload = _aggregate(version_id, "subcap", sub_rows)
    payload += _aggregate(version_id, "use_case", uc_rows)
    async with engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM control.sv_rollup WHERE version_id = :ver"), {"ver": version_id}
        )
        if payload:
            await conn.execute(
                text(
                    "INSERT INTO control.sv_rollup (version_id, entity_kind, entity_id, "
                    "subvertical, story_count, client_count, rep_story_keys, narrative) VALUES "
                    "(:version_id, :entity_kind, :entity_id, :subvertical, :story_count, "
                    ":client_count, CAST(:rep_story_keys AS jsonb), :narrative)"
                ),
                payload,
            )
    return {"rollups": len(payload)}


async def get(
    conn: AsyncConnection, version_id: str, entity_kind: str, entity_id: str, sv: str | None
) -> dict[str, Any] | None:
    """The rollup for the active SV lens, falling back to the all-SV canonical (subvertical='')."""
    code = normalize_sv_code(sv) or ""
    row = (
        (
            await conn.execute(
                text(
                    "SELECT subvertical, story_count, client_count, rep_story_keys, narrative "
                    "FROM control.sv_rollup WHERE version_id = :v AND entity_kind = :k "
                    "AND entity_id = :e AND subvertical IN (:sv, '') "
                    "ORDER BY (subvertical = :sv) DESC LIMIT 1"
                ),
                {"v": version_id, "k": entity_kind, "e": entity_id, "sv": code},
            )
        )
        .mappings()
        .first()
    )
    return dict(row) if row is not None else None
