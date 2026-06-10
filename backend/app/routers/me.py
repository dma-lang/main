"""Identity routes (F2) — the prototype's auth/identity contract.

GET /api/me returns {uid, email, is_admin, preferences}; PATCH /api/me/preferences persists the
server-side home for the prototype's cia_theme / cia_lens / cia_persona keys. GET /api/config is
the ONLY unauthenticated API route: it tells the SPA how to sign in (auth mode + the PUBLIC
Google OAuth client id) and exposes nothing else.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.deps import get_current_user
from app.services import users
from app.settings import Settings, get_settings

router = APIRouter(prefix="/api", tags=["identity"])


class PreferencesUpdate(BaseModel):
    preferences: dict[str, Any] = Field(default_factory=dict)


@router.get("/config")
async def client_config(settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    """Public bootstrap config for the SPA login: the auth mode and, in live mode, the Google
    OAuth WEB client id the Sign-in-with-Google button uses (a public identifier by design —
    security comes from server-side token VERIFICATION, which fails closed). No Firebase: plain
    Google Identity Services; no passwords are ever handled or stored."""
    live = not settings.is_dev_auth
    return {
        "auth_mode": "live" if live else "dev",
        "auth_email_domain": settings.auth_email_domain,
        "google_client_id": settings.google_client_id if live else None,
    }


@router.get("/me")
async def get_me(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    return user


@router.patch("/me/preferences")
async def patch_preferences(
    payload: PreferencesUpdate,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    return await users.update_preferences(str(user["uid"]), payload.preferences)
