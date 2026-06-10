"""Authentication & authorization dependencies (F2).

Hermetic mode returns a deterministic dev identity (no Firebase, no network). Live mode verifies a
Firebase ID token via google-auth, enforces the ``@<domain>`` allow-list (fails closed), and upserts
the user. ``require_admin`` gates admin surfaces on the single is_admin flag.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import Depends, Header, HTTPException, status

from app.services import users
from app.settings import Settings, get_settings

logger = logging.getLogger("cia.auth")


def _admin_set(settings: Settings) -> set[str]:
    return {e.lower() for e in settings.admin_emails}


def _bearer_token(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="missing bearer token")
    return authorization.split(" ", 1)[1].strip()


def _verify_firebase(token: str, settings: Settings) -> dict[str, Any]:
    if not settings.firebase_project_id:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="auth not configured")
    # Imported lazily so hermetic dev/tests never touch google-auth or the network.
    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token

    try:
        raw = id_token.verify_firebase_token(  # type: ignore[no-untyped-call]
            token, google_requests.Request(), audience=settings.firebase_project_id
        )
    except Exception as exc:
        logger.warning("firebase token verification failed: %s", exc)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="invalid token") from exc
    if not raw:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="invalid token")
    return dict(raw)


async def get_current_user(
    authorization: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """Resolve + upsert the caller. Fails closed unless AUTH_MODE=dev is set EXPLICITLY — the
    hermetic cost switch (LLM_MODE) can never disable authentication (defense in depth)."""
    if settings.is_dev_auth:
        email = settings.hermetic_email.lower()
        is_admin = settings.hermetic_is_admin or email in _admin_set(settings)
        return await users.upsert_user(settings.hermetic_uid, email, is_admin)

    claims = _verify_firebase(_bearer_token(authorization), settings)
    email = str(claims.get("email", "")).lower()
    domain_ok = email.endswith("@" + settings.auth_email_domain.lower())
    if not domain_ok or not claims.get("email_verified", False):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="account not permitted")
    uid = str(claims.get("user_id") or claims.get("sub") or "")
    if not uid:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="invalid token")
    return await users.upsert_user(uid, email, email in _admin_set(settings))


async def require_admin(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    """Gate admin surfaces on the single is_admin flag (403 otherwise)."""
    if not user.get("is_admin"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="admin only")
    return user
