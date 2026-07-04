"""Version timeline (G1) + diff (G2) read surfaces — F9 conventions (auth + version resolution)."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import text

from app import db
from app.deps import get_current_user, require_admin
from app.versioning import Version, resolve_version

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["versions"])

_SCHEMA_RE = re.compile(r"^cat_[a-z0-9_]+$")


class VersionInfo(BaseModel):
    version_id: str
    label: str
    status: str
    schema_name: str
    created_at: str | None = None
    # active | inactive | legacy — computed RELATIVE to the active version's number: the active
    # version is "active"; higher-numbered versions are "inactive"; lower-numbered are "legacy"
    # (legacy versions still inherit enrichment from the standard provisioned versions).
    tier: str = "active"


def _vnum(version_id: str) -> int:
    """The numeric ordinal of a version id (``v7`` -> 7); 0 when it carries no digits."""
    digits = re.sub(r"[^0-9]", "", version_id)
    return int(digits) if digits else 0


def _tier(num: int, active_num: int) -> str:
    """Version tier relative to the active version: equal = active, higher = inactive (a newer
    modelled version not yet activated), lower = legacy (older, enrichment-inherited)."""
    if num == active_num:
        return "active"
    return "inactive" if num > active_num else "legacy"


@router.get("/versions")
async def list_versions(_user: dict[str, Any] = Depends(get_current_user)) -> list[VersionInfo]:
    engine = db.get_engine()
    if engine is None:
        return []
    sql = (
        # newest (highest numeric version) first — the governed "most recent" order, so every
        # consumer defaults the same way the header/active-version resolution does
        "SELECT version_id, label, status, schema_name, created_at::text AS created_at "
        "FROM control.catalogue_version "
        "ORDER BY coalesce(nullif(regexp_replace(version_id, '[^0-9]', '', 'g'), '')::int, 0) "
        "DESC, created_at DESC"
    )
    async with engine.connect() as conn:
        rows = (await conn.execute(text(sql))).mappings().all()
    # The tier is relative to the ACTIVE version's number: the status='active' row if one exists,
    # else the highest-numbered version (the de-facto active, matching how the header defaults).
    active_num = next((_vnum(r["version_id"]) for r in rows if r["status"] == "active"), None)
    if active_num is None:
        active_num = max((_vnum(r["version_id"]) for r in rows), default=0)
    return [
        VersionInfo.model_validate({**dict(r), "tier": _tier(_vnum(r["version_id"]), active_num)})
        for r in rows
    ]


class DiffRow(BaseModel):
    id: str
    name: str
    pillar: str
    l2: str | None = None
    explanation: str  # WHY it is added / removed (the detail the diff now spells out)


class DiffModified(BaseModel):
    id: str
    name: str
    pillar: str
    l2: str | None = None
    from_id: str | None = None  # set when the id was reassigned (a rename carried across versions)
    changes: list[str]  # human-readable field deltas
    explanation: str


class DiffResp(BaseModel):
    a: str
    b: str
    added: list[DiffRow]  # genuinely new in b (no id or L2+description match in a)
    removed: list[DiffRow]  # genuinely gone from a (no id or L2+description match in b)
    modified: list[DiffModified]  # same subcap, changed — INCLUDING renames (id reassigned)
    unchanged: int


def _norm(s: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _toks(s: str | None) -> set[str]:
    return {t for t in re.sub(r"[^a-z0-9 ]", " ", (s or "").lower()).split() if len(t) > 2}


def _near(a: str | None, b: str | None, thr: float = 0.4) -> bool:
    """Deterministic 'descriptions near in meaning' proxy (token overlap); live mode upgrades to
    embedding cosine over the shared vector(768) space — same contract."""
    ta, tb = _toks(a), _toks(b)
    if not ta and not tb:
        return True
    return (len(ta & tb) / len(ta | tb) if (ta | tb) else 1.0) >= thr


@router.get("/diff/{a}/{b}")
async def diff_versions(
    a: str, b: str, _user: dict[str, Any] = Depends(get_current_user)
) -> DiffResp:
    """Catalogue diff (G2) between two PROVISIONED versions, explained in detail.

    Identity rule (refined per the catalogue's own governance): a subcap's IDENTITY is its
    **subcap id OR its L2 capability name**. So a previous subcap is only *removed* when NEITHER
    its id NOR its L2 capability name survives with a near description; a new subcap is only
    *added* under the same test. If the id changed but the L2 name (or subcap name) still matches
    with a near description, that is a **rename/reassignment** — reported as *modified* (id
    reassigned), never as a remove+add pair. Same-id subcaps whose description stays near in
    meaning do not count as a change. Each row carries the explanation."""
    va = await resolve_version(a)
    vb = await resolve_version(b)
    for v in (va, vb):
        if not _SCHEMA_RE.match(v.schema_name):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="invalid version schema")
    engine = db.require_engine()
    sql = (
        "SELECT s.subcap_id AS id, s.name, cap.name AS l2, s.description AS descr, "
        "s.lifecycle_state AS life, s.tier, left(s.subcap_id, 2) AS pillar "
        "FROM {s}.subcap s JOIN {s}.capability cap ON cap.capability_id = s.capability_id"
    )
    async with engine.connect() as conn:
        a_rows = (await conn.execute(text(sql.format(s=va.schema_name)))).mappings().all()
        b_rows = (await conn.execute(text(sql.format(s=vb.schema_name)))).mappings().all()
    A = {str(r["id"]): dict(r) for r in a_rows}
    B = {str(r["id"]): dict(r) for r in b_rows}
    b_by_name: dict[str, str] = {_norm(r["name"]): str(r["id"]) for r in b_rows}
    b_by_l2: dict[str, list[str]] = {}
    for r in b_rows:
        b_by_l2.setdefault(_norm(r["l2"]), []).append(str(r["id"]))

    added: list[DiffRow] = []
    removed: list[DiffRow] = []
    modified: list[DiffModified] = []
    unchanged = 0
    matched_b: set[str] = set()  # B-only ids consumed as rename targets

    # 1) same-id subcaps — modified only if a field actually diverged
    for sid in sorted(set(A) & set(B)):
        x, y = A[sid], B[sid]
        changes: list[str] = []
        if _norm(x["name"]) != _norm(y["name"]):
            changes.append(f"name '{x['name']}' → '{y['name']}'")
        if _norm(x["l2"]) != _norm(y["l2"]):
            changes.append(f"L2 capability '{x['l2']}' → '{y['l2']}'")
        # Same id => same subcap; a reworded description is expected across versions and is NOT a
        # change. Only count a near-total rewrite, and only when BOTH versions actually carry a
        # description (an empty v5 field vs a populated v7 one is missing enrichment, not a change).
        dx, dy = _toks(x["descr"]), _toks(y["descr"])
        if dx and dy and (len(dx & dy) / len(dx | dy)) < 0.12:
            changes.append("description substantially rewritten")
        if (x["tier"] or "") != (y["tier"] or ""):
            changes.append(f"tier {x['tier'] or '—'} → {y['tier'] or '—'}")
        # NOTE: lifecycle_state is deliberately excluded — it is mutable RUNTIME state (evolved by
        # suggestions/flags after provisioning), not a version-defining catalogue attribute.
        if changes:
            modified.append(
                DiffModified(
                    id=sid,
                    name=y["name"],
                    pillar=y["pillar"],
                    l2=y["l2"],
                    changes=changes,
                    explanation="Same subcap id, kept; " + "; ".join(changes) + ".",
                )
            )
        else:
            unchanged += 1

    # 2) A-only ids — a rename (carried over under a new id) or a genuine removal
    for sid in sorted(set(A) - set(B)):
        x = A[sid]
        succ = b_by_name.get(_norm(x["name"]))
        matched_by = "subcap name"
        if not succ or succ in A:
            succ = None
            for cand in b_by_l2.get(_norm(x["l2"]), []):
                if cand not in A and cand not in matched_b and _near(x["descr"], B[cand]["descr"]):
                    succ, matched_by = cand, "L2 capability name + near description"
                    break
        if succ and succ not in A:
            matched_b.add(succ)
            y = B[succ]
            modified.append(
                DiffModified(
                    id=succ,
                    name=y["name"],
                    pillar=y["pillar"],
                    l2=y["l2"],
                    from_id=sid,
                    changes=[f"id reassigned {sid} → {succ}"],
                    explanation=(
                        f"Rename/reassignment: '{x['name']}' [{sid}] in {va.version_id} carries "
                        f"over as '{y['name']}' [{succ}] in {vb.version_id} (matched by "
                        f"{matched_by}). Id governance never recycles ids, so a new id was minted "
                        "— this is not a removal."
                    ),
                )
            )
        else:
            removed.append(
                DiffRow(
                    id=sid,
                    name=x["name"],
                    pillar=x["pillar"],
                    l2=x["l2"],
                    explanation=(
                        f"Genuinely removed: neither id {sid} nor its L2 capability '{x['l2']}' "
                        f"survives in {vb.version_id} with a near description (deduped or dropped "
                        "at source)."
                    ),
                )
            )

    # 3) B-only ids not consumed as a rename target — genuinely added
    for sid in sorted(set(B) - set(A)):
        if sid in matched_b:
            continue
        y = B[sid]
        added.append(
            DiffRow(
                id=sid,
                name=y["name"],
                pillar=y["pillar"],
                l2=y["l2"],
                explanation=(
                    f"Genuinely new: no id or L2-capability+description match in {va.version_id}."
                ),
            )
        )
    return DiffResp(
        a=va.version_id,
        b=vb.version_id,
        added=added,
        removed=removed,
        modified=modified,
        unchanged=unchanged,
    )


@router.get("/versions/{version}")
async def get_version(
    version: str, _user: dict[str, Any] = Depends(get_current_user)
) -> VersionInfo:
    found: Version = await resolve_version(version)
    return VersionInfo(
        version_id=found.version_id,
        label=found.label,
        status=found.status,
        schema_name=found.schema_name,
    )


async def _activate(version: str, actor: str) -> dict[str, Any]:
    """Make exactly ONE version active: demote the current active to 'provisioned', promote the
    target (which must be provisioned), and audit the switch. The transaction guarantees the
    single-active invariant."""
    engine = db.require_engine()
    async with engine.begin() as conn:
        row = (
            await conn.execute(
                text("SELECT status FROM control.catalogue_version WHERE version_id = :v"),
                {"v": version},
            )
        ).first()
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"version '{version}' not found")
        if row[0] == "uploaded":
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail=f"'{version}' is uploaded but not provisioned — Apply & provision first",
            )
        await conn.execute(
            text(
                "UPDATE control.catalogue_version SET status = 'provisioned' "
                "WHERE status = 'active' AND version_id <> :v"
            ),
            {"v": version},
        )
        await conn.execute(
            text("UPDATE control.catalogue_version SET status = 'active' WHERE version_id = :v"),
            {"v": version},
        )
        await conn.execute(
            text(
                "INSERT INTO control.audit_log (actor, action, target_ref, meta) "
                "VALUES (:a, 'version_activated', :t, CAST(:m AS jsonb))"
            ),
            {"a": actor, "t": version, "m": json.dumps({"previous_active_demoted": True})},
        )
    return {"ok": True, "active": version}


@router.post("/admin/versions/{version}/activate")
async def activate_version(
    version: str, admin: dict[str, Any] = Depends(require_admin)
) -> dict[str, Any]:
    """Admin approval toggle (G1): switch the single ACTIVE catalogue version. Provisioned
    versions are committable-but-inactive until approved here; exactly one is active. Activating a
    version also REFRESHES its gated discovery proposals (use-case gaps, structural KG edges,
    unscoped subverticals — the same idempotent pass a redeploy runs), so the newly-active catalogue
    never shows stale proposals; the refresh is best-effort and never fails the activation."""
    if not version or set(version) - set("abcdefghijklmnopqrstuvwxyz0123456789_"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="invalid version id")
    # audit_log.actor is a FK to control.users(uid) — always the uid, never the email
    result = await _activate(version, str(admin["uid"]))
    try:
        from app.refresh import run_discovery

        # manage_engine=False: reuse the app's shared engine and never dispose it (disposing the
        # shared pool mid-request would 503 every following request).
        await run_discovery([version], manage_engine=False)
    except Exception:  # noqa: BLE001 - discovery is additive; a failure must never fail activation
        logger.exception("discovery refresh on activation FAILED (non-fatal) for %s", version)
    return result
