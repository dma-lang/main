"""Authentication & authorization dependencies (F2).

Hermetic mode returns a deterministic dev identity (no network). Live mode verifies a plain
Google ID token (Google Identity Services — no Firebase, no passwords handled or stored) via
google-auth, enforces the ``@<domain>`` allow-list (fails closed), and upserts
the user. ``require_admin`` gates admin surfaces on the single is_admin flag.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import Depends, Header, HTTPException, status

from app.services import admins, users
from app.settings import Settings, get_settings

logger = logging.getLogger("cia.auth")

# Shared google-auth transport: one HTTP session caches Google's signing certs across requests
# instead of refetching them on every token verification. Created lazily (hermetic never imports).
_google_request: Any = None


def _bearer_token(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="missing bearer token")
    return authorization.split(" ", 1)[1].strip()


def _verify_google(token: str, settings: Settings) -> dict[str, Any]:
    """Verify a plain Google Identity Services ID token (no Firebase): signature against
    Google's published certs, expiry, and audience == OUR OAuth web client id. Fails closed."""
    if not settings.google_client_id:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="auth not configured — set GOOGLE_CLIENT_ID on the service",
        )
    # Imported lazily so hermetic dev/tests never touch google-auth or the network.
    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token

    global _google_request
    if _google_request is None:

        class _BoundedRequest(google_requests.Request):
            """google-auth fetches Google's signing certs with NO timeout by default — a hung
            fetch would hang every sign-in (§15 bounded-everything: 10s, then a clean 401)."""

            def __call__(self, *args: Any, **kwargs: Any) -> Any:
                kwargs.setdefault("timeout", 10)
                return super().__call__(*args, **kwargs)  # type: ignore[no-untyped-call]

        _google_request = _BoundedRequest()

    try:
        raw = id_token.verify_oauth2_token(  # type: ignore[no-untyped-call]
            token, _google_request, audience=settings.google_client_id
        )
    except Exception as exc:
        logger.warning("google token verification failed: %s", exc)
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
        is_admin = settings.hermetic_is_admin or await admins.resolve_is_admin(email, settings)
        return await users.upsert_user(settings.hermetic_uid, email, is_admin)

    claims = _verify_google(_bearer_token(authorization), settings)
    email = str(claims.get("email", "")).lower()
    domain_ok = email.endswith("@" + settings.auth_email_domain.lower())
    if not domain_ok or not claims.get("email_verified", False):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="account not permitted")
    uid = str(claims.get("sub") or "")
    if not uid:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="invalid token")
    return await users.upsert_user(uid, email, await admins.resolve_is_admin(email, settings))


async def require_admin(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    """Gate admin surfaces on the single is_admin flag (403 otherwise)."""
    if not user.get("is_admin"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="admin only")
    return user
