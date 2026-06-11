"""Consistent error envelope (F9): every error response is `{"error": {"code", "message"}}`."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("cia.errors")

_CODES: dict[int, str] = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    409: "conflict",
    422: "validation_error",
    429: "rate_limited",
    503: "unavailable",
}


def _envelope(code: str, message: str, **extra: Any) -> dict[str, Any]:
    body: dict[str, Any] = {"code": code, "message": message}
    body.update(extra)
    return {"error": body}


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _CODES.get(exc.status_code, "error")
        return JSONResponse(status_code=exc.status_code, content=_envelope(code, str(exc.detail)))

    # A registry-disabled source is configuration, not a server fault: readable 409, never a 500.
    from app.services.sources import SourceDisabledError

    @app.exception_handler(SourceDisabledError)
    async def _source_disabled(request: Request, exc: SourceDisabledError) -> JSONResponse:
        return JSONResponse(status_code=409, content=_envelope("conflict", str(exc)))

    # A missing/unmigrated database is deploy-sequencing, not a server fault: actionable 503.
    from app.db import DatabaseNotReadyError

    @app.exception_handler(DatabaseNotReadyError)
    async def _db_not_ready(request: Request, exc: DatabaseNotReadyError) -> JSONResponse:
        return JSONResponse(status_code=503, content=_envelope("unavailable", str(exc)))

    # The engine exists but the DB is UNREACHABLE (driver connection error): a clean, honest 503,
    # never a scary 500 — and the message must NOT send the operator back to the migration job
    # (that's a different connection). This is the running SERVICE's Cloud SQL link.
    from sqlalchemy.exc import InterfaceError, OperationalError

    @app.exception_handler(OperationalError)
    @app.exception_handler(InterfaceError)
    async def _db_unreachable(request: Request, exc: Exception) -> JSONResponse:
        logger.warning("database unreachable: %s", str(exc).splitlines()[0][:200])
        return JSONResponse(
            status_code=503,
            content=_envelope(
                "unavailable",
                "the service cannot reach its database — this is the running service's Cloud SQL "
                "connection (NOT the migration job, which is separate and may already have run). "
                "Check that the service has --add-cloudsql-instances and a reachable instance.",
            ),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=_envelope("validation_error", "request validation failed", fields=exc.errors()),
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled error")
        return JSONResponse(
            status_code=500,
            content=_envelope("internal_error", "internal server error"),
        )
