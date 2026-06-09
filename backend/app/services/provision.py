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
from sqlalchemy.ext.asyncio import AsyncConnection

from app import db

_BACKEND = Path(__file__).resolve().parents[2]  # backend/ (app/services/provision.py -> backend)
_SEED_DIR = _BACKEND / "seed"
_TEMPLATE = _BACKEND / "alembic" / "sql" / "dataplane_template.sql"
_ENRICH = _SEED_DIR / "catalogue_v7_enrichment.json.gz"


def _load_catalogue() -> dict[str, Any]:
    with gzip.open(_SEED_DIR / "catalogue_v7.json.gz", "rt", encoding="utf-8") as fh:
        data: dict[str, Any] = json.load(fh)
    return data


def _load_enrichment() -> dict[str, list[dict[str, Any]]] | None:
    """Optional per-version catalogue enrichment (use cases, L3 platforms, personas, maturity),
    extracted from the comprehensive pillar workbooks. Absent => base catalogue only (resilient)."""
    if not _ENRICH.exists():
        return None
    with gzip.open(_ENRICH, "rt", encoding="utf-8") as fh:
        data: dict[str, list[dict[str, Any]]] = json.load(fh)
    return data


async def _seed_enrichment(
    conn: AsyncConnection, schema: str, e: dict[str, list[dict[str, Any]]]
) -> None:
    """Seed the enrichment tables in FK order, within the provisioning transaction."""

    async def ins(rows: list[dict[str, Any]], cols: str, table: str) -> None:
        if not rows:
            return
        names = [c.strip() for c in cols.split(",")]
        binds = ", ".join(f":{n}" for n in names)
        await conn.execute(text(f"INSERT INTO {schema}.{table} ({cols}) VALUES ({binds})"), rows)

    await ins(e.get("vendors", []), "vendor_id, name", "vendor")
    await ins(
        e.get("l3_platforms", []),
        "l3_id, vendor_id, name, category, description, reference_url",
        "l3_platform",
    )
    await ins(e.get("personas", []), "persona_id, canonical_name, role_description", "persona")
    await ins(
        e.get("use_cases", []), "use_case_id, subcap_id, archetype, name, description", "use_case"
    )
    await ins(e.get("subcap_platforms", []), "subcap_id, l3_id", "subcap_platform")
    await ins(e.get("subcap_personas", []), "subcap_id, persona_id", "subcap_persona")
    await ins(
        e.get("maturity_descriptors", []),
        "descriptor_id, subcap_id, level, descriptor, features",
        "maturity_descriptor",
    )


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
    enrich = _load_enrichment()
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
        if enrich:
            await _seed_enrichment(conn, schema, enrich)
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
        "use_cases": len(enrich["use_cases"]) if enrich else 0,
        "platforms": len(enrich["l3_platforms"]) if enrich else 0,
        "personas": len(enrich["personas"]) if enrich else 0,
        "maturity": len(enrich["maturity_descriptors"]) if enrich else 0,
    }
