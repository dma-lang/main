"""F2: identity, preferences, and the admin gate.

The identity/preferences tests are DB-backed (skipped without DATABASE_URL). The require_admin gate
is pure logic and always runs. A module fixture brings the control plane to head before DB tests.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.deps import require_admin
from app.main import create_app

needs_db = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"), reason="DATABASE_URL not set (DB-backed test)"
)


@pytest.fixture(scope="module")
def _migrated() -> None:
    from app import migrate

    migrate.run()  # idempotent: at-head skip or upgrade


@pytest.fixture
def client(_migrated: None) -> Iterator[TestClient]:
    with TestClient(create_app()) as c:
        yield c


@needs_db
def test_me_returns_hermetic_identity(client: TestClient) -> None:
    r = client.get("/api/me")
    assert r.status_code == 200
    body = r.json()
    assert body["uid"]
    assert body["email"] == "dev@zennify.com"
    assert body["is_admin"] is True
    assert "preferences" in body


@needs_db
def test_update_preferences_persists(client: TestClient) -> None:
    payload = {"preferences": {"theme": "dark", "lens": "pillar"}}
    r = client.patch("/api/me/preferences", json=payload)
    assert r.status_code == 200
    assert r.json()["preferences"]["theme"] == "dark"
    again = client.get("/api/me").json()  # a fresh read reflects the persisted change
    assert again["preferences"]["lens"] == "pillar"


def test_hermetic_llm_mode_does_not_disable_auth() -> None:
    """The cost switch must never disable authentication: LLM_MODE=hermetic + live auth still
    fails closed when there is no session cookie (dev identity needs AUTH_MODE=dev EXPLICITLY)."""
    from starlette.requests import Request

    from app.deps import get_current_user
    from app.settings import Settings

    s = Settings(llm_mode="hermetic", auth_mode="live")
    req = Request({"type": "http", "headers": [], "method": "GET", "path": "/api/me"})
    with pytest.raises(HTTPException) as exc:
        asyncio.run(get_current_user(request=req, settings=s))
    assert exc.value.status_code == 401


@needs_db
def test_admin_grant_list_is_runtime_editable(client: TestClient) -> None:
    """The admin config space: the two named admins are seeded; grants/revokes persist, are
    domain-restricted, audited, and a bootstrap (env) admin cannot be revoked here."""
    seeded = {a["email"] for a in client.get("/api/admin/admins").json()}
    assert "tom.hedgecoth@zennify.com" in seeded
    assert "mishley.otiende@zennify.com" in seeded

    # grant -> persisted and listed as a removable runtime grant
    assert client.post("/api/admin/admins", json={"email": "qa.lead@zennify.com"}).json()["ok"]
    row = next(
        a for a in client.get("/api/admin/admins").json() if a["email"] == "qa.lead@zennify.com"
    )
    assert row["source"] == "grant" and row["removable"] is True

    # non-domain is rejected (admins must be @zennify.com, like sign-in)
    assert client.post("/api/admin/admins", json={"email": "x@gmail.com"}).status_code == 400

    # revoke a runtime grant; revoking a non-grant 404s
    assert client.request("DELETE", "/api/admin/admins/qa.lead@zennify.com").json()["ok"]
    assert client.request("DELETE", "/api/admin/admins/nobody@zennify.com").status_code == 404


def test_admin_resolution_unions_bootstrap_and_grants() -> None:
    """ADMIN_EMAILS (env bootstrap) is admin immediately, before any DB grant — defense in depth
    so an operator can never lock everyone out."""
    from app.services.admins import _bootstrap
    from app.settings import Settings

    s = Settings(admin_emails=["boss@zennify.com"])
    assert _bootstrap(s) == {"boss@zennify.com"}


def test_named_admins_are_hardcoded_defaults_and_login_fails_closed_unconfigured() -> None:
    """The two named admins stay baked-in defaults. Live OAuth: without the client id/secret the
    login route must fail CLOSED with an actionable 503 — never start a flow it can't complete."""
    from starlette.requests import Request

    from app.routers.auth import auth_login
    from app.settings import Settings

    s = Settings()
    assert s.admin_emails == ["tom.hedgecoth@zennify.com", "mishley.otiende@zennify.com"]
    assert s.google_client_id == "" and s.google_client_secret == ""  # set per-deployment
    req = Request({"type": "http", "headers": [], "method": "GET", "path": "/api/auth/login"})
    with pytest.raises(HTTPException) as exc:
        asyncio.run(auth_login(req, Settings(auth_mode="live")))
    assert exc.value.status_code == 503
    assert "GOOGLE_OAUTH_CLIENT" in str(exc.value.detail)


def test_redirect_uri_is_pinned_to_the_canonical_url() -> None:
    """REGRESSION (the operator's own probe caught this): Cloud Run serves the same app on TWO
    hostnames, and a host-derived redirect_uri was a MOVING TARGET — whichever URL a user opened
    dictated the redirect_uri sent, so the OAuth client's registered list could never match for
    everyone. With PUBLIC_BASE_URL set, the flow is pinned: a login on a non-canonical host hops
    to the canonical one first (cookies are per-host), and the canonical host sends ONE stable
    redirect_uri — the single value to register."""
    from urllib.parse import parse_qs, urlparse

    from app.main import create_app
    from app.settings import Settings, get_settings

    canonical = "https://cia-306195530103.us-central1.run.app"
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: Settings(
        auth_mode="live",
        google_client_id="cid.apps.googleusercontent.com",
        google_client_secret="GOCSPX-test",
        public_base_url=canonical,
    )
    # arriving on a NON-canonical host (e.g. the legacy hash url) -> hop to the canonical host
    with TestClient(app, base_url="https://cia-dukrne5v4a-uc.a.run.app") as c:
        r = c.get("/api/auth/login", follow_redirects=False)
        assert r.status_code == 302
        assert r.headers["location"] == f"{canonical}/api/auth/login"
        assert "cia_oauth_state" not in r.cookies  # state must be set on the canonical host only
    # arriving on the canonical host -> straight to Google with the PINNED redirect_uri
    with TestClient(app, base_url=canonical) as c:
        r = c.get("/api/auth/login", follow_redirects=False)
        assert r.status_code == 302 and "accounts.google.com" in r.headers["location"]
        qs = parse_qs(urlparse(r.headers["location"]).query)
        assert qs["redirect_uri"] == [f"{canonical}/api/auth/callback"]


def test_oauth_env_aliases_are_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    """The deployment uses Accelerate's GOOGLE_OAUTH_* names; GOOGLE_CLIENT_ID stays a legacy
    alias. Both must populate the same settings, and GOOGLE_OAUTH_HOSTED_DOMAIN sets the domain."""
    from app.settings import Settings

    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "id-oauth.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "GOCSPX-secret")
    monkeypatch.setenv("GOOGLE_OAUTH_HOSTED_DOMAIN", "zennify.com")
    s = Settings()
    assert s.google_client_id == "id-oauth.apps.googleusercontent.com"
    assert s.google_client_secret == "GOCSPX-secret"
    assert s.auth_email_domain == "zennify.com"
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_ID")
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "id-legacy.apps.googleusercontent.com")
    assert Settings().google_client_id == "id-legacy.apps.googleusercontent.com"


def test_admin_emails_env_accepts_plain_lists(monkeypatch: pytest.MonkeyPatch) -> None:
    """ADMIN_EMAILS=a,b (the documented form) must not crash settings at boot — pydantic-settings
    would JSON-decode it in the env source; NoDecode + the validator accept comma, semicolon and
    JSON-array forms."""
    from app.settings import Settings

    monkeypatch.setenv("ADMIN_EMAILS", "a@zennify.com,b@zennify.com")
    assert Settings().admin_emails == ["a@zennify.com", "b@zennify.com"]
    monkeypatch.setenv("ADMIN_EMAILS", "a@zennify.com;b@zennify.com")
    assert Settings().admin_emails == ["a@zennify.com", "b@zennify.com"]
    monkeypatch.setenv("ADMIN_EMAILS", '["c@zennify.com"]')
    assert Settings().admin_emails == ["c@zennify.com"]


def test_live_config_advertises_oauth_login() -> None:
    """GET /api/config tells the SPA auth is configured and where to start the redirect flow —
    NOT the client id/secret (they stay server-side in the code flow). No Firebase, no GSI."""
    from app.routers.me import client_config
    from app.settings import Settings

    cfg = asyncio.run(
        client_config(
            Settings(
                auth_mode="live",
                google_client_id="abc.apps.googleusercontent.com",
                google_client_secret="GOCSPX-x",
            )
        )
    )
    assert cfg["auth_mode"] == "live"
    assert cfg["auth_configured"] is True
    assert cfg["login_url"] == "/api/auth/login"
    assert "google_client_id" not in cfg and "firebase" not in cfg  # secret-free contract
    # configured=False when the secret is missing (so the Login names the exact blocker)
    half = asyncio.run(client_config(Settings(auth_mode="live", google_client_id="abc")))
    assert half["auth_configured"] is False


def test_db_not_ready_is_503_not_500(monkeypatch: pytest.MonkeyPatch) -> None:
    """No engine (DATABASE_URL unset / migration job not run) must surface as an actionable 503
    `unavailable` envelope, not a generic 500 — the Login page tells the operator to run A9."""
    from app import db

    monkeypatch.setattr(db, "init_engine", lambda: None)  # lifespan no-op: simulate no DB
    monkeypatch.setattr(db, "_engine", None)
    monkeypatch.setattr(db, "_sessionmaker", None)
    with TestClient(create_app(), raise_server_exceptions=False) as c:
        r = c.get("/api/me")
    assert r.status_code == 503
    body = r.json()["error"]
    assert body["code"] == "unavailable"
    assert "migration job" in body["message"]


def test_requests_dependency_is_installed() -> None:
    """REGRESSION: the OAuth code exchange POSTs to Google's token endpoint with `requests`,
    shipped only by the google-auth[requests] EXTRA. When it was missing, sign-in 500'd with an
    ImportError the Login page mislabelled 'database not ready'. Guard the dependency for good."""
    import importlib

    importlib.import_module("requests")  # must import, not ImportError


@needs_db
def test_oauth_code_flow_signs_in_zennify_and_rejects_others(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """END-TO-END simulation of the Accelerate-style login: /api/auth/login -> Google ->
    /api/auth/callback (code exchange stubbed) -> signed session cookie -> /api/me. A @zennify.com
    account signs in; any other domain is refused with NO session. No GSI, no bearer token."""
    import base64
    import json as _json

    from app.main import create_app
    from app.settings import Settings, get_settings

    def _b64(o: dict[str, object]) -> str:
        return base64.urlsafe_b64encode(_json.dumps(o).encode()).rstrip(b"=").decode()

    def _id_token(email: str) -> str:
        body = {"email": email, "email_verified": True, "hd": "zennify.com", "sub": "g-" + email}
        return f"{_b64({'alg': 'RS256'})}.{_b64(body)}.sig"

    captured: dict[str, str] = {}

    class _Resp:
        def raise_for_status(self) -> None: ...
        def json(self) -> dict[str, str]:
            return {"id_token": _id_token(captured["email"])}

    def _fake_post(url: str, data: dict[str, str], timeout: int = 0) -> _Resp:
        captured["sent_secret"] = data["client_secret"]  # the secret IS used (server-to-server)
        return _Resp()

    monkeypatch.setattr("requests.post", _fake_post)

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: Settings(
        auth_mode="live",
        google_client_id="cid.apps.googleusercontent.com",
        google_client_secret="GOCSPX-test",
        hmac_key="test-session-key",
    )
    with TestClient(app) as c:
        # 1) login -> 302 to Google, with a CSRF state cookie bound to this browser
        r = c.get("/api/auth/login", follow_redirects=False)
        assert r.status_code == 302 and "accounts.google.com" in r.headers["location"]
        state = c.cookies.get("cia_oauth_state")
        assert state and "hd=zennify.com" in r.headers["location"]

        # 2) callback for a @zennify.com user -> session cookie set, redirect into the app
        captured["email"] = "consultant@zennify.com"
        r = c.get(f"/api/auth/callback?code=abc&state={state}", follow_redirects=False)
        assert r.status_code == 302 and r.headers["location"] == "/"
        assert c.cookies.get("cia_session") and captured["sent_secret"] == "GOCSPX-test"

        # 3) /api/me now resolves the identity from the cookie alone (no token, no Google call)
        me = c.get("/api/me")
        assert me.status_code == 200 and me.json()["email"] == "consultant@zennify.com"

        # 4) a non-domain account is refused — redirected with an error and NO session
        c.cookies.clear()
        c.get("/api/auth/login", follow_redirects=False)
        state = c.cookies.get("cia_oauth_state")
        captured["email"] = "outsider@gmail.com"
        r = c.get(f"/api/auth/callback?code=abc&state={state}", follow_redirects=False)
        assert r.status_code == 302 and "error=domain" in r.headers["location"]
        assert not c.cookies.get("cia_session")
        assert c.get("/api/me").status_code == 401  # fails closed


def test_db_unreachable_is_honest_503_not_500(monkeypatch: pytest.MonkeyPatch) -> None:
    """The engine EXISTS but the database is UNREACHABLE (driver OperationalError): the request
    must surface as a clean 503 whose message points at the SERVICE's Cloud SQL connection — never
    a raw 500, and never the misleading 'run the migration job' (that's a different connection)."""
    from sqlalchemy.exc import OperationalError

    from app.services import users

    async def _boom(*_a: object, **_k: object) -> dict[str, object]:
        raise OperationalError("SELECT 1", {}, Exception("connection refused"))

    monkeypatch.setattr(users, "upsert_user", _boom)
    with TestClient(create_app(), raise_server_exceptions=False) as c:
        r = c.get("/api/me")  # dev identity -> straight to the upsert -> DB error
    assert r.status_code == 503
    msg = r.json()["error"]["message"]
    assert "cannot reach its database" in msg
    # it must clarify this is the SERVICE's connection, NOT tell them to run the migration job
    assert "NOT the migration job" in msg


def test_config_reports_db_health_for_login_preflight() -> None:
    """/api/config carries db status so the Login page can name the exact blocker (sign-in
    unconfigured vs database unreachable) before the user ever clicks."""
    with TestClient(create_app()) as c:
        cfg = c.get("/api/config").json()
    assert cfg["db"] in {"ok", "down", "not_configured"}


def test_require_admin_blocks_non_admin() -> None:
    with pytest.raises(HTTPException) as exc:
        asyncio.run(require_admin(user={"uid": "u", "is_admin": False}))
    assert exc.value.status_code == 403


def test_require_admin_allows_admin() -> None:
    out = asyncio.run(require_admin(user={"uid": "u", "is_admin": True}))
    assert out["is_admin"] is True
