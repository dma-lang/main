"""control.users data access (F2).

Identity is upserted on every authenticated request (first login creates the row). ``is_admin`` is
config-driven (settings.admin_emails / hermetic) and kept in sync on each login. Preferences (theme,
lens, persona) are the server home for the prototype's client-side ``cia_*`` keys.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text

from app import db

_RETURNING = "RETURNING uid, email, is_admin, preferences"


async def upsert_user(uid: str, email: str, is_admin: bool) -> dict[str, Any]:
    """Insert or update a user; returns {uid, email, is_admin, preferences}."""
    engine = db.get_engine()
    if engine is None:
        raise RuntimeError("database not initialised")
    async with engine.begin() as conn:
        result = await conn.execute(
            text(
                "INSERT INTO control.users (uid, email, is_admin) "
                "VALUES (:uid, :email, :is_admin) "
                "ON CONFLICT (uid) DO UPDATE SET "
                "email = EXCLUDED.email, is_admin = EXCLUDED.is_admin " + _RETURNING
            ),
            {"uid": uid, "email": email, "is_admin": is_admin},
        )
        row = result.mappings().first()
    assert row is not None
    return dict(row)


async def update_preferences(uid: str, preferences: dict[str, Any]) -> dict[str, Any]:
    """Replace a user's preferences jsonb; raises KeyError if the user does not exist."""
    engine = db.get_engine()
    if engine is None:
        raise RuntimeError("database not initialised")
    async with engine.begin() as conn:
        result = await conn.execute(
            text("UPDATE control.users SET preferences = :prefs WHERE uid = :uid " + _RETURNING),
            {"uid": uid, "prefs": json.dumps(preferences)},
        )
        row = result.mappings().first()
    if row is None:
        raise KeyError(uid)
    return dict(row)
