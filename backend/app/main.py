"""FastAPI application entrypoint (F1).

Single Cloud Run service: this app serves the JSON API and the built Vite/React SPA from one
container. Binds ``0.0.0.0:$PORT`` (see the Dockerfile CMD). ``/healthz`` is the startup/readiness
probe that gates traffic; ``/livez`` is the liveness probe. The lifespan handler drains on SIGTERM
(F3 will open/dispose the DB pool here). No DB dependency at F1 so the service boots standalone.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app import db
from app._version import APP_VERSION
from app.settings import Settings, get_settings

logger = logging.getLogger("cia")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    logger.info(
        "startup: app_version=%s env=%s llm_mode=%s",
        APP_VERSION,
        settings.app_env,
        settings.llm_mode,
    )
    db.init_engine()  # open the bounded async pool (no-op without DATABASE_URL)
    yield
    await db.dispose_engine()  # drain the pool within the SIGTERM window
    logger.info("shutdown: drained")


def create_app() -> FastAPI:
    logging.basicConfig(level=logging.INFO)
    settings = get_settings()
    app = FastAPI(title="Capability Intelligence Agent", version=APP_VERSION, lifespan=lifespan)

    if settings.cors_allow_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_allow_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    @app.get("/healthz", tags=["system"])
    async def healthz() -> dict[str, object]:
        """Startup/readiness probe (§16). Reports app + active catalogue version + db + mode."""
        engine = db.get_engine()
        db_status = "ok" if await db.ping() else ("not_configured" if engine is None else "down")
        return {
            "status": "ok",
            "app_version": APP_VERSION,
            "catalogue_version": await db.active_catalogue_version(),
            "llm_mode": settings.llm_mode,
            "db": db_status,
        }

    @app.get("/livez", tags=["system"])
    async def livez() -> dict[str, str]:
        """Liveness probe — restarts a hung instance."""
        return {"status": "alive"}

    # --- API routers (register before the SPA mount so /api/* always wins) ---
    from app.routers import me as me_router

    app.include_router(me_router.router)

    _mount_spa(app, settings.static_dir)
    return app


def _mount_spa(app: FastAPI, static_dir: str) -> None:
    """Serve the built SPA at '/'. Mounted last so it never shadows API routes.

    Resilient: if the build is absent (e.g. backend-only dev), log and serve API only.
    """
    path = Path(static_dir)
    if not path.is_dir():
        logger.warning("static dir '%s' not found; serving API only", path)
        return
    app.mount("/", StaticFiles(directory=path, html=True), name="spa")


app = create_app()


__all__ = ["app", "create_app", "Settings"]
