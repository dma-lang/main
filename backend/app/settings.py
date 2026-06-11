"""Application settings (F1).

Read from the environment (12-factor). Cloud Run injects ``PORT``; ``LLM_MODE`` selects the
deterministic hermetic stub stack vs live Vertex AI; ``DATABASE_URL`` is wired by F3. Secrets are
never defaulted here — they arrive from Secret Manager via the environment at runtime.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from pydantic import AliasChoices, Field, field_validator
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
    auth_mode: str = "live"  # live (Google OAuth code flow, fails closed) | dev (local identity)

    # OAuth 2.0 Authorization-Code flow (the proven Accelerate pattern): a full-page redirect to
    # Google and back. The backend exchanges the code using the client SECRET (server-to-server),
    # verifies the hosted domain, and mints its own signed session cookie — so there is NO
    # browser-side Google Identity Services and NO "Authorized JavaScript origins" to register;
    # it works behind a load balancer / any origin (only the redirect URI is registered). Accepts
    # the GOOGLE_OAUTH_* env names (Accelerate's) and GOOGLE_CLIENT_ID as a legacy alias.
    google_client_id: str = Field(
        default="",
        validation_alias=AliasChoices("google_oauth_client_id", "google_client_id"),
    )
    google_client_secret: str = Field(
        default="",
        validation_alias=AliasChoices("google_oauth_client_secret", "google_client_secret"),
    )
    session_ttl_hours: int = 12  # session cookie lifetime (matches Accelerate's JWT_TTL_HOURS)

    # THE canonical public URL of this service (e.g. https://cia-<project#>.us-central1.run.app).
    # Cloud Run answers on TWO hostnames (deterministic + legacy hash); deriving the OAuth
    # redirect_uri from the incoming Host made it a MOVING TARGET — whichever URL a user opened
    # dictated the redirect_uri sent, so Google's "registered redirect URI" check could never be
    # satisfied for everyone. When set, the entire OAuth round-trip is pinned to this base: login
    # hops here first, Google redirects here, the session cookie lives here. Empty => derive from
    # the request (local dev / tests).
    public_base_url: str = ""

    auth_email_domain: str = Field(
        default="zennify.com",  # sign-in restricted to this hosted domain; fails closed
        validation_alias=AliasChoices("google_oauth_hosted_domain", "auth_email_domain"),
    )
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

    @property
    def session_secret(self) -> str:
        """Key for signing session cookies — reuses the provisioned hmac_key (no new secret), with
        a fixed dev fallback so local/hermetic sessions still verify."""
        return self.hmac_key or "dev-session-secret-not-for-production"


@lru_cache
def get_settings() -> Settings:
    """Cached singleton so settings are read once per process."""
    return Settings()
