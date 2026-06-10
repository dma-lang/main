"""Identity routes (F2) — the prototype's auth/identity contract.

GET /api/me returns {uid, email, is_admin, preferences}; PATCH /api/me/preferences persists the
server-side home for the prototype's cia_theme / cia_lens / cia_persona keys. GET /api/config is
the ONLY unauthenticated API route: it tells the SPA how to sign in (auth mode + the PUBLIC
Firebase web config) and exposes nothing else.
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
    """Public bootstrap config for the SPA login: which auth mode is active and, in live mode,
    the FULL public Firebase web config (these values ship to every browser by design — security
    comes from token VERIFICATION server-side, which fails closed). Defaults are hardcoded in
    settings.py; env vars override them on rotation."""
    firebase = None
    if not settings.is_dev_auth and settings.firebase_project_id and settings.firebase_web_api_key:
        firebase = {
            "api_key": settings.firebase_web_api_key,
            "auth_domain": settings.firebase_auth_domain,
            "project_id": settings.firebase_project_id,
            "storage_bucket": settings.firebase_storage_bucket,
            "messaging_sender_id": settings.firebase_messaging_sender_id,
            "app_id": settings.firebase_app_id,
            "measurement_id": settings.firebase_measurement_id,
        }
    return {
        "auth_mode": "dev" if settings.is_dev_auth else "live",
        "auth_email_domain": settings.auth_email_domain,
        "firebase": firebase,
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
