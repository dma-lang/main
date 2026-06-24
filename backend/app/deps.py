"""Authentication & authorization dependencies (F2).

Hermetic/dev mode returns a deterministic dev identity (no network). Live mode reads the SESSION
COOKIE that the OAuth Authorization-Code callback set (``app/routers/auth.py``) — the proven
Accelerate pattern: the heavy Google interaction happens once, at the redirect; every request
afterwards just verifies a signed cookie. Enforces the ``@<domain>`` allow-list (fails closed) and
upserts the user. ``require_admin`` gates admin surfaces on the single is_admin flag.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import Depends, HTTPException, Request, status

from app.services import admins, users
from app.settings import Settings, get_settings

logger = logging.getLogger("cia.auth")


async def get_current_user(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """Resolve + upsert the caller from the SESSION COOKIE the OAuth callback set (the proven
    Accelerate pattern — no per-request Google call, no bearer token). Fails closed unless
    AUTH_MODE=dev is set EXPLICITLY — the hermetic cost switch (LLM_MODE) can never disable
    authentication (defense in depth)."""
    if settings.is_dev_auth:
        email = settings.hermetic_email.lower()
        is_admin = settings.hermetic_is_admin or await admins.resolve_is_admin(email, settings)
        return await users.upsert_user(settings.hermetic_uid, email, is_admin)

    from app.routers.auth import SESSION_COOKIE
    from app.sessions import read_session

    token = request.cookies.get(SESSION_COOKIE)
    claims = read_session(token, settings.session_secret) if token else None
    if not claims:
        # No / expired / tampered session: the SPA gate shows Login, whose button starts
        # /api/auth/login. 401 (never 500) so the frontend handles it cleanly.
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, detail="not signed in — start /api/auth/login"
        )
    email = str(claims.get("email", "")).lower()
    if not email.endswith("@" + settings.auth_email_domain.lower()):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="account not permitted")
    uid = str(claims.get("sub") or email)
    return await users.upsert_user(uid, email, await admins.resolve_is_admin(email, settings))


async def require_admin(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    """Gate admin surfaces on the single is_admin flag (403 otherwise)."""
    if not user.get("is_admin"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="admin only")
    return user
