"""Server-issued session token (F2) — the Accelerate-style auth pattern.

After the OAuth Authorization-Code exchange verifies a user against Google, the backend mints its
OWN short-lived session and sets it as an HttpOnly cookie. Subsequent requests carry that cookie
(same-origin: FastAPI serves the SPA), so there is NO browser-side Google Identity Services, no
"Authorized JavaScript origins", and nothing that breaks behind a load balancer.

The token is a compact ``<payload>.<sig>`` where sig = HMAC-SHA256(payload, hmac_key) — signed with
the key already provisioned for exports, so no new secret is needed. Tamper-proof (constant-time
compare) and self-expiring (``exp``). This is intentionally a tiny, dependency-free stand-in for a
JWT: one service issues and verifies it, so a full asymmetric JWT is unnecessary.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any


def _b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64u_decode(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def make_session(claims: dict[str, Any], secret: str, ttl_seconds: int) -> str:
    """Sign {**claims, exp} into a compact HMAC token."""
    body = {**claims, "exp": int(time.time()) + ttl_seconds}
    payload = _b64u(json.dumps(body, separators=(",", ":")).encode())
    sig = _b64u(hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{sig}"


def read_session(token: str, secret: str) -> dict[str, Any] | None:
    """Verify signature + expiry; return the claims, or None if invalid/expired/tampered."""
    try:
        payload, sig = token.split(".", 1)
        expected = _b64u(hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, expected):
            return None
        claims: dict[str, Any] = json.loads(_b64u_decode(payload))
    except Exception:
        return None
    if float(claims.get("exp", 0)) < time.time():
        return None
    return claims
