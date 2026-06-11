"""OAuth 2.0 Authorization-Code login (F2) — the proven Accelerate pattern.

Three routes, all full-page (no XHR, no browser SDK):
  GET /api/auth/login    -> 302 to Google's consent screen (hd-restricted to the domain).
  GET /api/auth/callback -> exchange the code for tokens using the client SECRET, verify the
                            hosted domain, mint an HttpOnly signed session cookie, 302 to the app.
  GET /api/auth/logout   -> clear the session cookie, 302 to the app.

Why this and not browser Google Identity Services: the redirect flow needs only an *Authorized
redirect URI* (not JavaScript origins), works behind a load balancer / any origin, and depends on
no client-side script — so it "just goes through" where GSI breaks. The client secret is REQUIRED
here (server-to-server code exchange); it never reaches the browser.
"""

from __future__ import annotations

import asyncio
import json
import secrets
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse

from app.sessions import _b64u_decode, make_session
from app.settings import Settings, get_settings

router = APIRouter(prefix="/api/auth", tags=["auth"])

_GOOGLE_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"  # noqa: S105 - public endpoint, not a secret
SESSION_COOKIE = "cia_session"
_STATE_COOKIE = "cia_oauth_state"


def _redirect_uri(request: Request) -> str:
    """This service's callback URL, derived from the incoming request so it is correct on any
    host (run.app, the load balancer, localhost). Must match an Authorized redirect URI on the
    OAuth client. Honours X-Forwarded-Proto so it stays https behind the load balancer."""
    base = str(request.base_url).rstrip("/")
    proto = request.headers.get("x-forwarded-proto")
    if proto == "https" and base.startswith("http://"):
        base = "https://" + base[len("http://") :]
    return f"{base}/api/auth/callback"


def _secure(request: Request) -> bool:
    return request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"


@router.get("/login")
async def auth_login(
    request: Request, settings: Settings = Depends(get_settings)
) -> RedirectResponse:
    """Begin sign-in: redirect to Google's consent screen (domain-restricted)."""
    if not settings.google_client_id or not settings.google_client_secret:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="sign-in is not configured — set GOOGLE_OAUTH_CLIENT_ID and "
            "GOOGLE_OAUTH_CLIENT_SECRET on the service",
        )
    state = secrets.token_urlsafe(24)
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": _redirect_uri(request),
        "response_type": "code",
        "scope": "openid email profile",
        "hd": settings.auth_email_domain,  # pre-filter the account picker to the domain
        "state": state,
        "access_type": "online",
        "prompt": "select_account",
    }
    resp = RedirectResponse(f"{_GOOGLE_AUTH}?{urlencode(params)}", status_code=302)
    # CSRF: bind the state to this browser; checked on callback.
    resp.set_cookie(
        _STATE_COOKIE, state, max_age=600, httponly=True, secure=_secure(request), samesite="lax"
    )
    return resp


def _decode_id_token(id_token: str) -> dict[str, Any]:
    """The id_token claims. It arrived directly from Google's token endpoint over TLS in a
    client-secret-authenticated exchange, so the channel is trusted and we read the payload
    without re-fetching Google's certs (standard for the server-side code flow)."""
    payload = id_token.split(".")[1]
    return json.loads(_b64u_decode(payload))  # type: ignore[no-any-return]


@router.get("/callback")
async def auth_callback(
    request: Request,
    settings: Settings = Depends(get_settings),
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    """Finish sign-in: validate state, exchange the code, verify the domain, set the session."""
    if error:
        return RedirectResponse(f"/#/login?error={error}", status_code=302)
    if not code or not state or state != request.cookies.get(_STATE_COOKIE):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="invalid oauth state")

    import requests as _requests  # installed via google-auth[requests]; used for the code exchange

    def _exchange() -> dict[str, Any]:
        r = _requests.post(
            _GOOGLE_TOKEN,
            data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": _redirect_uri(request),
                "grant_type": "authorization_code",
            },
            timeout=10,
        )
        r.raise_for_status()
        return dict(r.json())

    try:
        tokens = await asyncio.to_thread(_exchange)
        claims = _decode_id_token(str(tokens["id_token"]))
    except Exception as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, detail=f"google token exchange failed: {exc}"
        ) from exc

    email = str(claims.get("email", "")).lower()
    domain = settings.auth_email_domain.lower()
    if not email.endswith("@" + domain) or not claims.get("email_verified", False):
        # Honest, fail-closed: the account is real but not permitted.
        return RedirectResponse("/#/login?error=domain", status_code=302)
    sub = str(claims.get("sub") or email)

    session = make_session(
        {"sub": sub, "email": email}, settings.session_secret, settings.session_ttl_hours * 3600
    )
    resp = RedirectResponse("/", status_code=302)
    resp.set_cookie(
        SESSION_COOKIE,
        session,
        max_age=settings.session_ttl_hours * 3600,
        httponly=True,
        secure=_secure(request),
        samesite="lax",
    )
    resp.delete_cookie(_STATE_COOKIE)
    return resp


@router.get("/logout")
async def auth_logout() -> RedirectResponse:
    """Clear the session and return to the app (which will show the login page)."""
    resp = RedirectResponse("/#/login", status_code=302)
    resp.delete_cookie(SESSION_COOKIE)
    return resp
