"""Administrator resolution + the runtime-editable grant list (the admin config space).

Admin status is the UNION of two sources:
  * the ADMIN_EMAILS env (break-glass BOOTSTRAP — always admin, not revocable from the UI, so an
    operator can never lock everyone out), and
  * control.admin_grant, the persisted list admins edit at runtime (Settings -> Administrators)
    without a redeploy — durable across sessions, users and restarts.

Grants are domain-restricted (sign-in is @zennify.com, so an admin must be too) and audited. A
bootstrap admin can never be removed here (it lives in config); a granted admin can.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app import db
from app.settings import Settings, get_settings


def _bootstrap(settings: Settings) -> set[str]:
    return {e.strip().lower() for e in settings.admin_emails if e.strip()}


async def is_granted(conn: AsyncConnection, email: str) -> bool:
    row = (
        await conn.execute(
            text("SELECT 1 FROM control.admin_grant WHERE email = :e"), {"e": email.lower()}
        )
    ).first()
    return row is not None


async def resolve_is_admin(email: str, settings: Settings) -> bool:
    """Is this verified email an admin? Bootstrap env wins immediately; otherwise consult the
    persisted grant list. Degrades to bootstrap-only if the DB is unavailable (never crashes
    identity resolution)."""
    if email.lower() in _bootstrap(settings):
        return True
    engine = db.get_engine()
    if engine is None:
        return False
    async with engine.connect() as conn:
        return await is_granted(conn, email)


async def list_admins() -> list[dict[str, Any]]:
    """Every administrator with its SOURCE (bootstrap = config/env, grant = runtime list). The
    bootstrap entries are shown but cannot be removed from the UI."""
    settings = get_settings()
    out: list[dict[str, Any]] = [
        {"email": e, "source": "bootstrap", "removable": False, "granted_by": "env", "note": ""}
        for e in sorted(_bootstrap(settings))
    ]
    bootstrap = _bootstrap(settings)
    engine = db.get_engine()
    if engine is not None:
        async with engine.connect() as conn:
            rows = (
                (
                    await conn.execute(
                        text(
                            "SELECT email, granted_by, coalesce(note, '') AS note, "
                            "created_at::text AS created_at FROM control.admin_grant ORDER BY email"
                        )
                    )
                )
                .mappings()
                .all()
            )
        for r in rows:
            if r["email"].lower() in bootstrap:
                continue  # already shown as bootstrap (env wins)
            out.append(
                {
                    "email": r["email"],
                    "source": "grant",
                    "removable": True,
                    "granted_by": r["granted_by"],
                    "note": r["note"],
                    "created_at": r["created_at"],
                }
            )
    return out


async def grant_admin(email: str, actor: str, note: str = "") -> dict[str, Any]:
    """Add an administrator to the persisted list (audited). Domain-restricted and idempotent."""
    settings = get_settings()
    e = email.strip().lower()
    if "@" not in e:
        return {"ok": False, "status": "invalid", "reason": "not an email address"}
    if not e.endswith("@" + settings.auth_email_domain.lower()):
        return {
            "ok": False,
            "status": "rejected",
            "reason": f"admins must be @{settings.auth_email_domain} accounts",
        }
    if e in _bootstrap(settings):
        return {"ok": True, "status": "bootstrap", "email": e}  # already a config admin, no-op
    engine = db.require_engine()
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO control.admin_grant (email, granted_by, note) VALUES (:e, :by, :n) "
                "ON CONFLICT (email) DO UPDATE SET granted_by = EXCLUDED.granted_by"
            ),
            {"e": e, "by": actor, "n": note or None},
        )
        await conn.execute(
            text(
                "INSERT INTO control.audit_log (actor, action, target_ref, meta) "
                "VALUES ((SELECT uid FROM control.users WHERE uid = :a), 'admin_grant', :ref, "
                "CAST(:m AS jsonb))"
            ),
            {"a": actor, "ref": f"admin:{e}", "m": json.dumps({"email": e})},
        )
    return {"ok": True, "status": "granted", "email": e}


async def revoke_admin(email: str, actor: str) -> dict[str, Any]:
    """Remove a GRANTED administrator (audited). Bootstrap (env) admins cannot be removed here."""
    settings = get_settings()
    e = email.strip().lower()
    if e in _bootstrap(settings):
        return {
            "ok": False,
            "status": "rejected",
            "reason": "this admin is a config (ADMIN_EMAILS) bootstrap and cannot be removed here",
        }
    engine = db.require_engine()
    async with engine.begin() as conn:
        deleted = (
            await conn.execute(
                text("DELETE FROM control.admin_grant WHERE email = :e RETURNING email"), {"e": e}
            )
        ).first()
        if deleted is None:
            return {"ok": False, "status": "not_found"}
        # also clear the live is_admin flag on the user row (next request re-resolves anyway)
        await conn.execute(
            text("UPDATE control.users SET is_admin = false WHERE lower(email) = :e"), {"e": e}
        )
        await conn.execute(
            text(
                "INSERT INTO control.audit_log (actor, action, target_ref, meta) "
                "VALUES ((SELECT uid FROM control.users WHERE uid = :a), 'admin_revoke', :ref, "
                "CAST(:m AS jsonb))"
            ),
            {"a": actor, "ref": f"admin:{e}", "m": json.dumps({"email": e})},
        )
    return {"ok": True, "status": "revoked", "email": e}
