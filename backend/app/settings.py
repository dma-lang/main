"""Application settings (F1).

Read from the environment (12-factor). Cloud Run injects ``PORT``; ``LLM_MODE`` selects the
deterministic hermetic stub stack vs live Vertex AI; ``DATABASE_URL`` is wired by F3. Secrets are
never defaulted here — they arrive from Secret Manager via the environment at runtime.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


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

    # Auth (F2). DELIBERATELY decoupled from LLM_MODE: a hermetic (no-spend) deployment still
    # fails closed unless AUTH_MODE=dev is set explicitly — the cost switch must never be able to
    # disable authentication. "live" verifies GOOGLE ID tokens (plain Google Identity Services —
    # no Firebase, no passwords stored); "dev" is the deterministic local identity.
    auth_mode: str = "live"  # live (Google ID token, fails closed) | dev (local identity)

    # The OAuth 2.0 WEB client id the SPA's "Sign in with Google" button uses and the ONLY
    # audience the server accepts tokens for. A public identifier, not a secret — security is
    # server-side verification against Google's certs, which fails closed (503 when unset).
    # Set GOOGLE_CLIENT_ID on the service; create/copy it in GCP Console → APIs & Services →
    # Credentials (add the run.app origin as an authorized JavaScript origin).
    google_client_id: str = ""

    auth_email_domain: str = "zennify.com"  # sign-in restricted to this domain; fails closed
    # Break-glass bootstrap admins (always admin; the runtime grant list adds more). NoDecode +
    # the validator below accept a plain comma/semicolon env string — ADMIN_EMAILS=a@x.com,b@x.com
    # — as well as a JSON array (without NoDecode, pydantic-settings JSON-decodes in the env
    # source itself and a plain string CRASHES the service at boot).
    admin_emails: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: [
            "tom.hedgecoth@zennify.com",
            "mishley.otiende@zennify.com",
        ]
    )
    hermetic_uid: str = "dev-user"
    hermetic_email: str = "dev@zennify.com"
    hermetic_is_admin: bool = True

    @field_validator("admin_emails", "cors_allow_origins", mode="before")
    @classmethod
    def _split_plain_list(cls, v: object) -> object:
        """Env values for list fields arrive as strings; pydantic-settings expects JSON and would
        CRASH THE SERVICE AT BOOT on ADMIN_EMAILS=a@x.com,b@x.com. Accept plain comma/semicolon
        lists (and still accept JSON arrays)."""
        if isinstance(v, str):
            s = v.strip()
            if s.startswith("["):
                import json

                return json.loads(s)  # NoDecode skips the source's JSON pass — decode here
            return [part.strip() for part in s.replace(";", ",").split(",") if part.strip()]
        return v

    # Export signing (F12). Live key arrives from Secret Manager; hermetic falls back to a fixed
    # dev key so signed exports remain verifiable in dev. Live WITHOUT a key refuses to export.
    hmac_key: str | None = None

    # CORS — only needed when the Vite dev server calls the API cross-origin. Same-origin in prod.
    cors_allow_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173"]
    )

    @property
    def is_hermetic(self) -> bool:
        return self.llm_mode.lower() == "hermetic"

    @property
    def is_dev_auth(self) -> bool:
        return self.auth_mode.lower() == "dev"


@lru_cache
def get_settings() -> Settings:
    """Cached singleton so settings are read once per process."""
    return Settings()
