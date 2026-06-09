"""F4 — per-version provisioning: bring_version_online().

Generates the ``cat_<version>`` data plane from the template and seeds the canonical catalogue
(pillars -> categories -> capabilities -> subcaps) from the committed seed (the real v7 catalogue,
851 subcaps). The whole thing runs in one transaction so a half-applied version is impossible
(plan Part B / D10). The full automap studio that ingests arbitrary workbooks layers on top of this.
"""

from __future__ import annotations

import gzip
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from sqlalchemy import text

from app import db

_BACKEND = Path(__file__).resolve().parents[2]  # backend/ (app/services/provision.py -> backend)
_SEED_DIR = _BACKEND / "seed"
_TEMPLATE = _BACKEND / "alembic" / "sql" / "dataplane_template.sql"


def _load_catalogue() -> dict[str, Any]:
    with gzip.open(_SEED_DIR / "catalogue_v7.json.gz", "rt", encoding="utf-8") as fh:
        data: dict[str, Any] = json.load(fh)
    return data


def _statements(sql: str) -> Iterator[str]:
    for chunk in sql.split(";"):
        stmt = chunk.strip()
        if stmt:
            yield stmt


def _derive(
    cat: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Derive the relational hierarchy from the (denormalised) seed catalogue."""
    pillars = [{"pillar_id": pid, "name": p.get("name", pid)} for pid, p in cat["pillars"].items()]
    categories = [
        {"category_id": cid, "pillar_id": cid[:2], "name": name}
        for cid, name in cat["catNames"].items()
    ]
    caps: dict[str, dict[str, Any]] = {}
    subcaps: list[dict[str, Any]] = []
    for s in cat["subcaps"]:
        cap_id = s["id"].rsplit(".", 1)[0]
        caps.setdefault(
            cap_id,
            {"capability_id": cap_id, "category_id": s["catId"], "name": s.get("cluster", cap_id)},
        )
        subcaps.append(
            {
                "subcap_id": s["id"],
                "capability_id": cap_id,
                "name": s["name"],
                "description": s.get("desc"),
                "solution_type": s.get("sol"),
                "tier": s.get("tier"),
                "lifecycle_state": s.get("life", "stable"),
                "zennify_status": s.get("status"),
                "completeness": round(s.get("comp", 0) / 8.0, 3),
            }
        )
    return pillars, categories, list(caps.values()), subcaps


async def bring_version_online(
    version_id: str = "v7", label: str = "Catalogue v7.0"
) -> dict[str, Any]:
    """Drop+rebuild cat_<version> and seed the catalogue, transactionally; register the version."""
    if not version_id or set(version_id) - set("abcdefghijklmnopqrstuvwxyz0123456789_"):
        raise ValueError(f"invalid version_id: {version_id!r}")
    engine = db.get_engine()
    if engine is None:
        raise RuntimeError("database not initialised")
    cat = _load_catalogue()
    pillars, categories, caps, subcaps = _derive(cat)
    schema = f"cat_{version_id}"
    ddl = _TEMPLATE.read_text(encoding="utf-8").replace("{schema}", schema)

    async with engine.begin() as conn:
        await conn.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
        await conn.execute(text(f"CREATE SCHEMA {schema}"))
        for stmt in _statements(ddl):
            await conn.execute(text(stmt))
        await conn.execute(
            text(f"INSERT INTO {schema}.pillar (pillar_id, name) VALUES (:pillar_id, :name)"),
            pillars,
        )
        await conn.execute(
            text(
                f"INSERT INTO {schema}.category (category_id, pillar_id, name) "
                "VALUES (:category_id, :pillar_id, :name)"
            ),
            categories,
        )
        await conn.execute(
            text(
                f"INSERT INTO {schema}.capability (capability_id, category_id, name) "
                "VALUES (:capability_id, :category_id, :name)"
            ),
            caps,
        )
        await conn.execute(
            text(
                f"INSERT INTO {schema}.subcap "
                "(subcap_id, capability_id, name, description, solution_type, tier, "
                "lifecycle_state, zennify_status, completeness, search) VALUES "
                "(:subcap_id, :capability_id, :name, :description, :solution_type, :tier, "
                ":lifecycle_state, :zennify_status, :completeness, "
                "to_tsvector('english', coalesce(:name, '') || ' ' || coalesce(:description, '')))"
            ),
            subcaps,
        )
        await conn.execute(
            text(
                "INSERT INTO control.catalogue_version (version_id, label, schema_name, status) "
                "VALUES (:vid, :label, :schema, 'provisioned') "
                "ON CONFLICT (version_id) DO UPDATE SET "
                "status = 'provisioned', schema_name = EXCLUDED.schema_name, label = EXCLUDED.label"
            ),
            {"vid": version_id, "label": label, "schema": schema},
        )

    return {
        "version_id": version_id,
        "schema": schema,
        "pillars": len(pillars),
        "categories": len(categories),
        "capabilities": len(caps),
        "subcaps": len(subcaps),
    }
