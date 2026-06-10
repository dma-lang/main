"""Client journey atlas routes (F3, FR-19) — entity-resolved clients + journeys."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.deps import get_current_user
from app.services import clients as clients_service

router = APIRouter(prefix="/api", tags=["clients"])


@router.get("/clients")
async def list_clients(
    version: str = Query("v7"), _user: dict[str, Any] = Depends(get_current_user)
) -> list[dict[str, Any]]:
    return await clients_service.list_clients(version)


@router.get("/clients/{key}/journey")
async def journey(
    key: str,
    version: str = Query("v7"),
    _user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    found = await clients_service.client_journey(key, version)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="client not found")
    return found
