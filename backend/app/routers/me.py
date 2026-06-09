"""Identity routes (F2) — the prototype's auth/identity contract.

GET /api/me returns {uid, email, is_admin, preferences}; PATCH /api/me/preferences persists the
server-side home for the prototype's cia_theme / cia_lens / cia_persona keys.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.deps import get_current_user
from app.services import users

router = APIRouter(prefix="/api", tags=["identity"])


class PreferencesUpdate(BaseModel):
    preferences: dict[str, Any] = Field(default_factory=dict)


@router.get("/me")
async def get_me(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    return user


@router.patch("/me/preferences")
async def patch_preferences(
    payload: PreferencesUpdate,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    return await users.update_preferences(str(user["uid"]), payload.preferences)
