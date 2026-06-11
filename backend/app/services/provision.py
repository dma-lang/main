"""F4 — per-version provisioning: bring_version_online().

Generates the ``cat_<version>`` data plane from the template and seeds the canonical catalogue
(pillars -> categories -> capabilities -> subcaps) from the committed seed (the real v7 catalogue,
851 subcaps). The whole thing runs in one transaction so a half-applied version is impossible
(plan Part B / D10). The full automap studio that ingests arbitrary workbooks layers on top of this.
"""

from __future__ import annotations

import gzip
import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app import db

_BACKEND = Path(__file__).resolve().parents[2]  # backend/ (app/services/provision.py -> backend)
_SEED_DIR = _BACKEND / "seed"
_TEMPLATE = _BACKEND / "alembic" / "sql" / "dataplane_template.sql"
_SCHEMA_RE = re.compile(r"^cat_[a-z0-9_]+$")


def _load_catalogue(version_id: str) -> dict[str, Any]:
    """The per-version catalogue seed (catalogue_<v>.json.gz) — committed for v5/v7 (both
    generated from the REAL pillar-wise workbooks by services/workbooks.py; v7 round-trips the
    851 ids exactly) and written at runtime by the workbook-upload endpoint for new versions.
    A missing seed is an actionable error, never a silent fallback to another version."""
    path = _SEED_DIR / f"catalogue_{version_id}.json.gz"
    if not path.exists():
        raise FileNotFoundError(
            f"no catalogue seed for '{version_id}' — upload its pillar workbooks "
            f"(zip) via onboarding/Settings first"
        )
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        data: dict[str, Any] = json.load(fh)
    return data


def _load_enrichment(version_id: str) -> dict[str, list[dict[str, Any]]] | None:
    """Optional per-version catalogue enrichment (use cases, L3 platforms, personas, maturity),
    extracted from the comprehensive pillar workbooks. Absent => base catalogue only (resilient;
    v5 ships base-only)."""
    path = _SEED_DIR / f"catalogue_{version_id}_enrichment.json.gz"
    if not path.exists():
        return None
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        data: dict[str, list[dict[str, Any]]] = json.load(fh)
    return data


def load_id_register(exclude_version: str) -> tuple[str, dict[str, str]]:
    """The governing subcap-ID register for reconciliation: name -> id from the HIGHEST other
    committed/uploaded version's seed (ids are owned forever — never reused or recycled; a new
    version inherits identity from the register, it does not re-mint)."""
    best: tuple[int, str] | None = None
    for f in _SEED_DIR.glob("catalogue_*.json.gz"):
        name = f.stem.replace(".json", "")  # catalogue_v7
        vid = name.split("_", 1)[1]
        if vid == exclude_version or "enrichment" in name:
            continue
        num = int("".join(ch for ch in vid if ch.isdigit()) or 0)
        if best is None or num > best[0]:
            best = (num, vid)
    if best is None:
        return "", {}
    with gzip.open(_SEED_DIR / f"catalogue_{best[1]}.json.gz", "rt", encoding="utf-8") as fh:
        cat = json.load(fh)
    return best[1], {s["name"]: s["id"] for s in cat["subcaps"]}


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
    await ins(
        e.get("offerings", []),
        "offering_id, name, category, status, primary_vendor_id, description",
        "offering",
    )
    await ins(
        e.get("offering_subcaps", []),
        "offering_id, subcap_id, mapping_rationale, maturity_lift, status",
        "offering_subcap",
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
        # Completeness = DATA completeness of the loaded record (filled key fields / key fields).
        # Decay (subcaps with no Jira delivery) is a SEPARATE, live measure on the summary — the
        # two were conflated before, leaving every pillar at a meaningless "0% complete".
        key_fields = [s["name"], s.get("desc"), s.get("tier"), s.get("sol"), s.get("status")]
        completeness = round(sum(1 for f in key_fields if f) / len(key_fields), 3)
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
                "completeness": completeness,
            }
        )
    return pillars, categories, list(caps.values()), subcaps


# The field mapping this provisioner ACTUALLY applies (seed field -> canonical entity.field) and
# the relations it materializes as FKs/link tables. Registered per version so the schema-mapping
# studio shows the real, applied mapping — every row traces to a load statement in this module,
# nothing is invented. confidence 1.0 / status 'confirmed' because the seed pipeline is exact;
# a future workbook automap writes its own scored rows through the same tables (F4).
_FIELD_MAPPING: tuple[tuple[str, str, str, str], ...] = (
    # (sheet_id, source_field, canonical_entity, canonical_field)
    ("pillars", "id", "pillar", "pillar_id"),
    ("pillars", "name", "pillar", "name"),
    ("catNames", "id", "category", "category_id"),
    ("catNames", "name", "category", "name"),
    ("subcaps", "id", "subcap", "subcap_id"),
    ("subcaps", "name", "subcap", "name"),
    ("subcaps", "desc", "subcap", "description"),
    ("subcaps", "sol", "subcap", "solution_type"),
    ("subcaps", "tier", "subcap", "tier"),
    ("subcaps", "status", "subcap", "lifecycle_state"),
    ("subcaps", "cluster", "capability", "name"),
    ("subcaps", "personas", "persona", "canonical_name"),
    ("subcaps", "platforms", "l3_platform", "name"),
    ("subcaps", "uc", "use_case", "name"),
    ("enrichment", "maturity", "maturity_descriptor", "descriptor"),
    ("enrichment", "offerings", "offering", "name"),
)
_RELATIONS: tuple[tuple[str, str, str, str, str, str, str], ...] = (
    # (from_entity, from_field, rel_type, to_entity, to_field, cardinality, via) — the FKs and
    # link tables the provisioner actually creates in cat_<v>.
    (
        "subcap",
        "capability_id",
        "belongs_to",
        "capability",
        "capability_id",
        "many_to_one",
        "subcaps",
    ),
    (
        "capability",
        "category_id",
        "belongs_to",
        "category",
        "category_id",
        "many_to_one",
        "subcaps",
    ),
    ("category", "pillar_id", "belongs_to", "pillar", "pillar_id", "many_to_one", "catNames"),
    ("subcap", "subcap_id", "uses_platform", "l3_platform", "l3_id", "many_to_many", "subcaps"),
    ("subcap", "subcap_id", "has_persona", "persona", "persona_id", "many_to_many", "subcaps"),
    ("subcap", "subcap_id", "has_usecase", "use_case", "subcap_id", "one_to_many", "subcaps"),
    (
        "subcap",
        "subcap_id",
        "maps_to_offering",
        "offering",
        "offering_id",
        "many_to_many",
        "enrichment",
    ),
)


async def _register_mapping(conn: AsyncConnection, version_id: str) -> None:
    await conn.execute(
        text("DELETE FROM control.source_field_mapping WHERE version_id = :v"), {"v": version_id}
    )
    await conn.execute(
        text("DELETE FROM control.relation_def WHERE version_id = :v"), {"v": version_id}
    )
    await conn.execute(
        text("DELETE FROM control.catalogue_sheet WHERE version_id = :v"), {"v": version_id}
    )
    # one catalogue_sheet row per seed "sheet" (the source units the field rows reference)
    sheet_ids: dict[str, Any] = {}
    for sheet in dict.fromkeys(s for s, _, _, _ in _FIELD_MAPPING):
        sheet_ids[sheet] = (
            await conn.execute(
                text(
                    "INSERT INTO control.catalogue_sheet "
                    "(version_id, sheet_name, sheet_role, maps_to_entity) "
                    "VALUES (:v, :name, CAST('entity' AS sheet_role), :ent) RETURNING sheet_id"
                ),
                {
                    "v": version_id,
                    "name": sheet,
                    "ent": next(e for s, _, e, _ in _FIELD_MAPPING if s == sheet),
                },
            )
        ).scalar_one()
    await conn.execute(
        text(
            "INSERT INTO control.source_field_mapping "
            "(version_id, sheet_id, source_field, canonical_entity, canonical_field, "
            "confidence, status) VALUES (:v, :sheet, :src, :ent, :fld, 1.0, 'confirmed')"
        ),
        [
            # sheet-qualified: the baseline keys (version_id, source_field) globally
            {"v": version_id, "sheet": sheet_ids[s], "src": f"{s}.{src}", "ent": ent, "fld": fld}
            for s, src, ent, fld in _FIELD_MAPPING
        ],
    )
    await conn.execute(
        text(
            "INSERT INTO control.relation_def "
            "(version_id, from_entity, from_field, rel_type, to_entity, to_field, card, "
            "via_sheet, is_cascade) "
            "VALUES (:v, :fe, :ff, CAST(:rt AS relation_type), :te, :tf, "
            "CAST(:c AS cardinality), :via, false)"
        ),
        [
            {"v": version_id, "fe": fe, "ff": ff, "rt": rt, "te": te, "tf": tf, "c": c, "via": via}
            for fe, ff, rt, te, tf, c, via in _RELATIONS
        ],
    )


async def _record_id_governance(conn: AsyncConnection) -> tuple[int, int]:
    """Write every committed seed's ID reconciliations into the version crosswalk — but only
    where BOTH versions exist in ``catalogue_version`` (the crosswalk FKs each side). Idempotent
    and order-independent: a legacy-first provision defers its rows rather than failing the
    transaction; the next provision of the governing version sweeps them in. Nothing is silently
    dropped — the seed keeps the record permanently and the deferred count is surfaced in the
    provision report. Returns (written, deferred)."""
    present = {
        str(r[0])
        for r in (
            await conn.execute(text("SELECT version_id FROM control.catalogue_version"))
        ).all()
    }
    written = 0
    deferred = 0
    for f in sorted(_SEED_DIR.glob("catalogue_*.json.gz")):
        if "enrichment" in f.name:
            continue
        vid = f.stem.replace(".json", "").split("_", 1)[1]
        with gzip.open(f, "rt", encoding="utf-8") as fh:
            seed = json.load(fh)
        recs = seed.get("id_reconciliations") or []
        reg_ver = seed.get("id_register_version") or ""
        if not recs or not reg_ver:
            continue
        if vid not in present or reg_ver not in present:
            deferred += len(recs)
            continue
        await conn.execute(
            text(
                "DELETE FROM control.version_crosswalk WHERE from_version = :v "
                "AND note LIKE 'id-governance:%'"
            ),
            {"v": vid},
        )
        await conn.execute(
            text(
                "INSERT INTO control.version_crosswalk "
                "(from_version, from_subcap, to_version, to_subcap, note) "
                "VALUES (:fv, :fs, :tv, :ts, :note) "
                "ON CONFLICT (from_version, from_subcap, to_version) DO UPDATE "
                "SET to_subcap = EXCLUDED.to_subcap, note = EXCLUDED.note"
            ),
            [
                {
                    "fv": vid,
                    "fs": r["assigned_id"],
                    "tv": reg_ver,
                    "ts": r["assigned_id"],
                    "note": (
                        f"id-governance: source workbook stamped {r['source_id']} for "
                        f"'{r['name']}' (collision); reconciled by name against the "
                        f"{reg_ver} ID register — ids are never recycled"
                    ),
                }
                for r in recs
            ],
        )
        written += len(recs)
    return written, deferred


def _toks(s: str | None) -> set[str]:
    return {t for t in re.sub(r"[^a-z0-9 ]", " ", (s or "").lower()).split() if len(t) > 2}


def _near(a: str | None, b: str | None, thr: float = 0.25) -> bool:
    ta, tb = _toks(a), _toks(b)
    if not ta or not tb:
        return False  # need both to claim a description match
    return len(ta & tb) / len(ta | tb) >= thr


async def _inherit_enrichment(
    conn: AsyncConnection, schema: str, version_id: str
) -> dict[str, Any]:
    """Cross-version enrichment (user ask): a version with no enrichment of its OWN (e.g. v5,
    which ships base-only) inherits platforms / use cases / maturity / personas / offerings from
    the richest sibling version (e.g. v7), mapped per subcap so the deep dive is never empty.

    Mapping (most-specific first, so NO subcap is left without enrichment when a counterpart
    exists): exact subcap id -> id-governance crosswalk -> L2 capability name + near description
    -> L2 capability name (same capability) -> same category. Dimension tables (vendor, platform,
    persona, offering) are copied wholesale; the per-subcap links/children are copied with the
    subcap id remapped. The capability metadata is genuinely shared across catalogue versions, so
    this is enrichment reuse, not fabrication — and it is recorded in the provision report."""
    if not _SCHEMA_RE.match(schema):
        raise ValueError("invalid schema")
    uc = (await conn.execute(text(f"SELECT count(*) FROM {schema}.use_case"))).scalar() or 0
    plat = (await conn.execute(text(f"SELECT count(*) FROM {schema}.subcap_platform"))).scalar()
    if uc or (plat or 0):
        return {"inherited_from": None, "inherited_subcaps": 0, "reason": "has own enrichment"}

    # richest OTHER provisioned/active version (most use cases) is the enrichment source
    src = (
        await conn.execute(
            text(
                "SELECT cv.version_id, cv.schema_name FROM control.catalogue_version cv "
                "WHERE cv.version_id <> :v AND cv.status IN ('active', 'provisioned')"
            ),
            {"v": version_id},
        )
    ).all()
    best: tuple[int, str, str] | None = None
    for vid, sname in ((str(r[0]), str(r[1])) for r in src):
        if not _SCHEMA_RE.match(sname):
            continue
        n = (await conn.execute(text(f"SELECT count(*) FROM {sname}.use_case"))).scalar() or 0
        if n and (best is None or n > best[0]):
            best = (int(n), vid, sname)
    if best is None:
        return {"inherited_from": None, "inherited_subcaps": 0, "reason": "no enriched sibling"}
    _n, src_ver, src_schema = best

    # build the subcap correspondence this_subcap -> source_subcap
    async def _subcaps(sch: str) -> list[dict[str, Any]]:
        sql = (
            f"SELECT s.subcap_id AS id, cap.name AS l2, s.description AS descr, "
            f"cap.category_id AS cat FROM {sch}.subcap s "
            f"JOIN {sch}.capability cap ON cap.capability_id = s.capability_id"
        )
        return [dict(r) for r in (await conn.execute(text(sql))).mappings()]

    cur = await _subcaps(schema)
    srows = await _subcaps(src_schema)
    src_ids = {r["id"] for r in srows}
    src_by_l2: dict[str, list[dict[str, Any]]] = {}
    src_by_cat: dict[str, str] = {}
    for r in srows:
        src_by_l2.setdefault((r["l2"] or "").strip().lower(), []).append(r)
        src_by_cat.setdefault(r["cat"], r["id"])
    crosswalk = {
        str(r[0]): str(r[1])
        for r in await conn.execute(
            text(
                "SELECT from_subcap, to_subcap FROM control.version_crosswalk "
                "WHERE from_version = :a AND to_version = :b"
            ),
            {"a": version_id, "b": src_ver},
        )
    }
    mapping: list[dict[str, str]] = []
    for r in cur:
        sid = r["id"]
        tgt = None
        if sid in src_ids:
            tgt = sid
        elif sid in crosswalk and crosswalk[sid] in src_ids:
            tgt = crosswalk[sid]
        else:
            cands = src_by_l2.get((r["l2"] or "").strip().lower(), [])
            near = next((c["id"] for c in cands if _near(r["descr"], c["descr"])), None)
            tgt = near or (cands[0]["id"] if cands else src_by_cat.get(r["cat"]))
        if tgt:
            mapping.append({"this_sub": sid, "src_sub": tgt})
    if not mapping:
        return {"inherited_from": src_ver, "inherited_subcaps": 0, "reason": "no correspondence"}

    # dimensions copied wholesale (FK order: vendor -> l3_platform / offering; persona standalone)
    for tbl, cols in (
        ("vendor", "vendor_id, name"),
        ("l3_platform", "l3_id, vendor_id, name, category, description, reference_url"),
        ("persona", "persona_id, canonical_name, role_description"),
        ("offering", "offering_id, name, category, status, primary_vendor_id, description"),
    ):
        await conn.execute(
            text(f"INSERT INTO {schema}.{tbl} ({cols}) SELECT {cols} FROM {src_schema}.{tbl}")
        )

    await conn.execute(text("CREATE TEMP TABLE _emap (this_sub text, src_sub text) ON COMMIT DROP"))
    await conn.execute(
        text("INSERT INTO _emap (this_sub, src_sub) VALUES (:this_sub, :src_sub)"), mapping
    )
    # per-subcap links/children, subcap id remapped via _emap (use_case/maturity ids are made
    # unique by suffixing the target subcap, since one source subcap can map to several here)
    await conn.execute(
        text(
            f"INSERT INTO {schema}.subcap_platform (subcap_id, l3_id) "
            f"SELECT DISTINCT m.this_sub, sp.l3_id FROM _emap m "
            f"JOIN {src_schema}.subcap_platform sp ON sp.subcap_id = m.src_sub"
        )
    )
    await conn.execute(
        text(
            f"INSERT INTO {schema}.subcap_persona (subcap_id, persona_id) "
            f"SELECT DISTINCT m.this_sub, sp.persona_id FROM _emap m "
            f"JOIN {src_schema}.subcap_persona sp ON sp.subcap_id = m.src_sub"
        )
    )
    await conn.execute(
        text(
            f"INSERT INTO {schema}.offering_subcap "
            "(offering_id, subcap_id, mapping_rationale, maturity_lift, status) "
            f"SELECT DISTINCT os.offering_id, m.this_sub, os.mapping_rationale, os.maturity_lift, "
            f"os.status FROM _emap m "
            f"JOIN {src_schema}.offering_subcap os ON os.subcap_id = m.src_sub"
        )
    )
    await conn.execute(
        text(
            f"INSERT INTO {schema}.use_case (use_case_id, subcap_id, archetype, name, description) "
            f"SELECT uc.use_case_id || ':' || m.this_sub, m.this_sub, uc.archetype, uc.name, "
            f"uc.description FROM _emap m "
            f"JOIN {src_schema}.use_case uc ON uc.subcap_id = m.src_sub"
        )
    )
    await conn.execute(
        text(
            f"INSERT INTO {schema}.maturity_descriptor "
            "(descriptor_id, subcap_id, level, descriptor, features) "
            f"SELECT md.descriptor_id || ':' || m.this_sub, m.this_sub, md.level, md.descriptor, "
            f"md.features FROM _emap m "
            f"JOIN {src_schema}.maturity_descriptor md ON md.subcap_id = m.src_sub"
        )
    )
    enriched = (
        await conn.execute(text(f"SELECT count(DISTINCT subcap_id) FROM {schema}.subcap_platform"))
    ).scalar() or 0
    return {
        "inherited_from": src_ver,
        "inherited_subcaps": len(mapping),
        "subcaps_with_platforms": int(enriched),
    }


async def bring_version_online(
    version_id: str = "v7", label: str = "Catalogue v7.0"
) -> dict[str, Any]:
    """Drop+rebuild cat_<version> and seed the catalogue, transactionally; register the version."""
    if not version_id or set(version_id) - set("abcdefghijklmnopqrstuvwxyz0123456789_"):
        raise ValueError(f"invalid version_id: {version_id!r}")
    engine = db.require_engine()
    cat = _load_catalogue(version_id)
    pillars, categories, caps, subcaps = _derive(cat)
    enrich = _load_enrichment(version_id)
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
        # Cross-version enrichment: a base-only version (v5) inherits v7's platforms / use cases /
        # maturity / personas / offerings per subcap, so no deep dive is left empty (user ask).
        inherited = await _inherit_enrichment(conn, schema, version_id)
        # Provisioning makes a version COMMITTABLE, not active: activation is a separate,
        # admin-approved toggle (exactly one active). Re-provisioning the active version keeps
        # it active; the very first provision auto-activates so a fresh workspace works.
        await conn.execute(
            text(
                "INSERT INTO control.catalogue_version (version_id, label, schema_name, status) "
                "VALUES (:vid, :label, :schema, 'provisioned') "
                "ON CONFLICT (version_id) DO UPDATE SET "
                "status = CASE WHEN control.catalogue_version.status = 'active' "
                "THEN 'active' ELSE 'provisioned' END, "
                "schema_name = EXCLUDED.schema_name, label = EXCLUDED.label"
            ),
            {"vid": version_id, "label": label, "schema": schema},
        )
        await conn.execute(
            text(
                "UPDATE control.catalogue_version SET status = 'active' "
                "WHERE version_id = :vid AND NOT EXISTS "
                "(SELECT 1 FROM control.catalogue_version WHERE status = 'active')"
            ),
            {"vid": version_id},
        )
        # after the version row exists: register the mapping this run applied (FK on version_id)
        await _register_mapping(conn, version_id)
        # ID-governance record: reconciliations parsers made against the governing register land
        # in the version crosswalk (auditable; ids are never reused or recycled). Sweeps every
        # seed, so links another version had to defer (its register not provisioned yet) land
        # the moment both sides exist.
        gov_written, gov_deferred = await _record_id_governance(conn)

        # Counts reflect what the version ACTUALLY carries (own seed OR inherited), so the report
        # and the deep dive agree — never reporting 0 platforms while the tabs show them.
        async def _count(table: str) -> int:
            n = (await conn.execute(text(f"SELECT count(*) FROM {schema}.{table}"))).scalar()
            return int(n or 0)

        use_cases = await _count("use_case")
        platforms = await _count("l3_platform")
        personas = await _count("persona")
        maturity = await _count("maturity_descriptor")
        offerings = await _count("offering")

    return {
        "version_id": version_id,
        "schema": schema,
        "pillars": len(pillars),
        "categories": len(categories),
        "capabilities": len(caps),
        "subcaps": len(subcaps),
        "use_cases": int(use_cases or 0),
        "platforms": int(platforms or 0),
        "personas": int(personas or 0),
        "maturity": int(maturity or 0),
        "offerings": int(offerings or 0),
        "enrichment_inherited_from": inherited.get("inherited_from"),
        "enrichment_inherited_subcaps": inherited.get("inherited_subcaps", 0),
        "id_links_recorded": gov_written,
        "id_links_deferred": gov_deferred,
    }
