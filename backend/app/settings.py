"""Application settings (F1).

Read from the environment (12-factor). Cloud Run injects ``PORT``; ``LLM_MODE`` selects the
deterministic hermetic stub stack vs live Vertex AI; ``DATABASE_URL`` is wired by F3. Secrets are
never defaulted here — they arrive from Secret Manager via the environment at runtime.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    # Environment + provider mode.
    app_env: str = "dev"  # dev | staging | prod
    llm_mode: str = "hermetic"  # hermetic (stubs, no spend) | live (Vertex AI)

    # Server.
    port: int = 8080
    # Built SPA dir. The container copies frontend/dist -> <app root>/static; a relative value is
    # resolved against the app root (the dir holding the `app` package), not the process cwd, so it
    # serves the same build wherever uvicorn starts. Local dev: STATIC_DIR=<repo>/frontend/dist.
    static_dir: str = "static"

    # Datastore (wired in F3; optional at F1 so the service boots without a DB).
    database_url: str | None = None

    # Auth (F2). Live mode verifies Firebase ID tokens; hermetic mode uses a deterministic dev user.
    firebase_project_id: str | None = None
    auth_email_domain: str = "zennify.com"  # sign-in restricted to this domain; fails closed
    admin_emails: list[str] = Field(default_factory=list)  # these verified emails receive is_admin
    hermetic_uid: str = "dev-user"
    hermetic_email: str = "dev@zennify.com"
    hermetic_is_admin: bool = True

    # CORS — only needed when the Vite dev server calls the API cross-origin. Same-origin in prod.
    cors_allow_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    @property
    def is_hermetic(self) -> bool:
        return self.llm_mode.lower() == "hermetic"


@lru_cache
def get_settings() -> Settings:
    """Cached singleton so settings are read once per process."""
    return Settings()
