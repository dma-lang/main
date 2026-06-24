"""Admin operations (F4) + the source registry (Settings · admin sources).

Provisioning trigger and the app's persisted ingestion points: GET /sources composes the
control.ingest_source registry with config/schedules.yaml and the last ingest_run per source —
which origin is active (database fixture vs online), cadence, last poll and staleness, nothing
hidden. PATCH /sources/{key} persists the enable switch the scan jobs enforce.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import text

from app import db
from app.deps import require_admin
from app.services import admins, provision, sources, stories

router = APIRouter(prefix="/api/admin", tags=["admin"])


class AdminGrantIn(BaseModel):
    email: str
    note: str = ""


class SourceOut(BaseModel):
    key: str
    name: str
    type: str
    tier: str
    enabled: bool
    mode: str
    origin_active: str
    origin_recorded: str
    origin_live: str
    cadence: str
    cron: str | None
    next_run: str | None
    last_run: str | None
    last_status: str | None
    last_stats: dict[str, Any]
    status: str
    notes: str


class SourcePatch(BaseModel):
    enabled: bool


@router.post("/provision/{version}")
async def provision_version(
    version: str, _admin: dict[str, Any] = Depends(require_admin)
) -> dict[str, Any]:
    """Generate + seed cat_<version> and register it (admin only)."""
    return await provision.bring_version_online(version, label=f"Catalogue {version}.0")


@router.post("/carry-forward/{version}")
async def carry_forward(
    version: str, _admin: dict[str, Any] = Depends(require_admin)
) -> dict[str, Any]:
    """Ingest the canonical story corpus and carry it onto cat_<version> (F5, admin only)."""
    return await stories.carry_forward(version)


@router.get("/mapping/{version}")
async def get_mapping(
    version: str, _admin: dict[str, Any] = Depends(require_admin)
) -> dict[str, Any]:
    """The APPLIED schema mapping for a version (F4): every source-field -> canonical-field row
    the provisioner wrote, plus the relations it materialized as FKs/link tables — the studio
    renders these, so what it shows IS what ran. A version with no rows hasn't been provisioned."""
    from app.versioning import resolve_version

    v = await resolve_version(version)
    engine = db.require_engine()
    async with engine.connect() as conn:
        fields = (
            (
                await conn.execute(
                    text(
                        "SELECT cs.sheet_name, m.source_field, m.canonical_entity, "
                        "m.canonical_field, m.confidence::float AS confidence, m.status, "
                        "m.is_custom "
                        "FROM control.source_field_mapping m "
                        "JOIN control.catalogue_sheet cs ON cs.sheet_id = m.sheet_id "
                        "WHERE m.version_id = :v ORDER BY cs.sheet_name, m.source_field"
                    ),
                    {"v": v.version_id},
                )
            )
            .mappings()
            .all()
        )
        relations = (
            (
                await conn.execute(
                    text(
                        "SELECT from_entity, rel_type::text AS rel_type, to_entity, "
                        "card::text AS card, via_sheet, is_cascade "
                        "FROM control.relation_def WHERE version_id = :v "
                        "ORDER BY from_entity, rel_type"
                    ),
                    {"v": v.version_id},
                )
            )
            .mappings()
            .all()
        )
    return {
        "version": v.version_id,
        "fields": [dict(r) for r in fields],
        "relations": [dict(r) for r in relations],
    }


@router.get("/sources")
async def list_sources(_admin: dict[str, Any] = Depends(require_admin)) -> list[SourceOut]:
    """The persisted source registry: every ingestion point with its ACTIVE origin (database
    fixture vs online, per LLM_MODE), cadence, last poll and staleness — warned, never hidden."""
    return [SourceOut(**vars(s)) for s in await sources.list_sources()]


@router.patch("/sources/{key}")
async def patch_source(
    key: str, body: SourcePatch, admin: dict[str, Any] = Depends(require_admin)
) -> dict[str, Any]:
    """Persist the per-source enable switch (audited). Scan jobs enforce it before any fetch."""
    result = await sources.set_enabled(key, body.enabled, str(admin["uid"]))
    if result.get("status") == "not_found":
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"unknown source '{key}'")
    return result


@router.get("/admins")
async def list_admins(_admin: dict[str, Any] = Depends(require_admin)) -> list[dict[str, Any]]:
    """The administrator config space: every admin with its source (bootstrap env vs runtime
    grant). Bootstrap admins are shown but not removable from the UI."""
    return await admins.list_admins()


@router.post("/admins")
async def grant_admin(
    body: AdminGrantIn, admin: dict[str, Any] = Depends(require_admin)
) -> dict[str, Any]:
    """Grant an administrator at runtime (persisted + audited). Domain-restricted."""
    result = await admins.grant_admin(body.email, str(admin["uid"]), body.note)
    if result.get("status") in ("invalid", "rejected"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=result.get("reason"))
    return result


@router.delete("/admins/{email}")
async def revoke_admin(
    email: str, admin: dict[str, Any] = Depends(require_admin)
) -> dict[str, Any]:
    """Revoke a granted administrator (persisted + audited). Bootstrap admins cannot be removed."""
    result = await admins.revoke_admin(email, str(admin["uid"]))
    if result.get("status") == "not_found":
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"'{email}' is not a granted admin")
    if result.get("status") == "rejected":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=result.get("reason"))
    return result


@router.post("/catalogue/upload/{version}")
async def upload_catalogue(
    version: str,
    file: UploadFile,
    _admin: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    """Accept the pillar-wise catalogue upload (FR-1): a ZIP of the four pillar .xlsx workbooks
    (or a single .xlsx). Validates the archive, lists the workbooks found, and records the upload
    as an ingest_run so it shows in the source registry — honestly returning which pillar files
    were recognised. Provisioning then runs against the committed seed until the workbook parser
    lands (the upload manifest is the contract it will consume)."""
    if not version or set(version) - set("abcdefghijklmnopqrstuvwxyz0123456789_"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="invalid version id")
    raw = await file.read()
    if len(raw) > 100 * 1024 * 1024:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="upload over the 100 MB bound")
    name = (file.filename or "").lower()
    workbooks: list[dict[str, Any]] = []
    if name.endswith(".zip"):
        import io
        import zipfile

        try:
            zf = zipfile.ZipFile(io.BytesIO(raw))
        except zipfile.BadZipFile as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="not a valid zip") from exc
        for info in zf.infolist():
            base = info.filename.rsplit("/", 1)[-1]
            if base.lower().endswith(".xlsx") and not base.startswith((".", "~")):
                workbooks.append({"name": base, "bytes": info.file_size})
    elif name.endswith(".xlsx"):
        workbooks.append({"name": file.filename, "bytes": len(raw)})
    else:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="upload a .zip of the pillar workbooks or a single .xlsx",
        )
    if not workbooks:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail="the zip contains no .xlsx workbooks"
        )
    pillars = sorted(
        {
            f"P{n}"
            for w in workbooks
            for n in "1234"
            if f"pillar {n}" in str(w["name"]).lower() or f"pillar{n}" in str(w["name"]).lower()
        }
    )
    # Parse the workbooks into the provisioning seed (services/workbooks): the upload is not
    # just validated, it BECOMES the version's catalogue source. Committed seeds (v5/v7) are
    # regenerated the same way; a new version's seed lives for the instance's life (re-upload
    # after a restart — Cloud Run's filesystem is ephemeral).
    subcaps_parsed = 0
    synthetic_found = 0
    parsed: dict[str, Any] = {}
    if name.endswith(".zip"):
        import gzip as _gzip

        from app.services import workbooks as wb_service
        from app.services.provision import _SEED_DIR, load_id_register

        reg_ver, register = load_id_register(exclude_version=version)
        try:
            parsed = wb_service.parse_catalogue_zip(raw, version, id_register=register)
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        subcaps_parsed = len(parsed["subcaps"])
        parsed["id_register_version"] = reg_ver
        with _gzip.open(_SEED_DIR / f"catalogue_{version}.json.gz", "wt", encoding="utf-8") as fh:
            json.dump(
                {
                    k: parsed[k]
                    for k in (
                        "pillars",
                        "catNames",
                        "subcaps",
                        "id_reconciliations",
                        "id_conflicts",
                        "id_register_version",
                    )
                },
                fh,
            )
        # The per-subcap × per-subvertical VALUE-CHAIN mapping (sheet 21) — persisted so the
        # atlas / SV filters run on the catalogue's REAL stage names for this version too.
        vc = wb_service.parse_vc_mapping_zip(raw)
        if vc.get("mapping"):
            with _gzip.open(
                _SEED_DIR / f"vc_mapping_{version}.json.gz", "wt", encoding="utf-8"
            ) as fh:
                json.dump(vc, fh)
        # The workbooks may embed a user-story tab: its non-Jira rows are SYNTHETIC stories,
        # seeded per version and ingested labelled (is_synthetic) at carry — the real corpus
        # comes only from the Full Story Catalog, so the two never mix.
        synthetic = wb_service.parse_synthetic_stories_zip(raw)
        synthetic_found = len(synthetic)
        if synthetic:
            syn_path = _SEED_DIR / f"stories_synthetic_{version}.json.gz"
            with _gzip.open(syn_path, "wt", encoding="utf-8") as fh:
                json.dump(synthetic, fh)
    # PERSIST EVERY LOAD (D10): the upload registers the version immediately (status 'uploaded' —
    # provisioning later flips it to 'provisioned'; never downgraded on re-upload) and records the
    # full parse as an ingest_run row — detected schema, counts, governance — so each load is
    # committed to the database and auditable, not just echoed to the browser.
    engine = db.require_engine()
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO control.catalogue_version (version_id, label, schema_name, status) "
                "VALUES (:v, :label, :schema, 'uploaded') ON CONFLICT (version_id) DO NOTHING"
            ),
            {"v": version, "label": f"Catalogue {version} (uploaded)", "schema": f"cat_{version}"},
        )
        await conn.execute(
            text(
                "INSERT INTO control.ingest_run (version_id, source, status, finished_at, stats) "
                "VALUES (:v, 'workbook_upload', 'succeeded', now(), CAST(:s AS jsonb))"
            ),
            {
                "v": version,
                "s": json.dumps(
                    {
                        "workbooks": len(workbooks),
                        "pillars": pillars,
                        "files": workbooks[:8],
                        "subcaps_parsed": subcaps_parsed,
                        "synthetic_stories_found": synthetic_found,
                        "skipped_rows": parsed.get("skipped_rows", 0),
                        "duplicate_rows": parsed.get("duplicate_rows", 0),
                        "id_reconciliations": parsed.get("id_reconciliations", []),
                        "id_conflicts": parsed.get("id_conflicts", []),
                        "workbooks_detail": parsed.get("workbooks_detail", []),
                        "relations_detected": parsed.get("relations_detected", []),
                    }
                ),
            },
        )
    return {
        "version": version,
        "workbooks": workbooks,
        "pillars_recognised": pillars,
        "subcaps_parsed": subcaps_parsed,
        "synthetic_stories_found": synthetic_found,
        "id_reconciliations": parsed.get("id_reconciliations", []),
        "id_conflicts": parsed.get("id_conflicts", []),
        # the DETECTED SCHEMA per workbook (sheet, column->field mapping with confidence/
        # signals/samples, unmapped headers, per-book counts) and the RELATIONSHIPS the backend
        # schema needs — what the onboarding "Detect schema" step reviews
        "workbooks_detail": parsed.get("workbooks_detail", []),
        "relations_detected": parsed.get("relations_detected", []),
        "skipped_rows": parsed.get("skipped_rows", 0),
        "duplicate_rows": parsed.get("duplicate_rows", 0),
        "recorded": True,
        "note": (
            f"Parsed {subcaps_parsed} subcaps from the workbooks"
            + (
                f" (+{synthetic_found} embedded synthetic stories, labelled, never analysis)"
                if synthetic_found
                else ""
            )
            + "; run Apply & provision to bring the version online."
            if subcaps_parsed
            else "Upload validated and recorded; run Apply & provision to bring the version online."
        ),
    }
