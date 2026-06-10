"""Test-suite environment defaults.

AUTH_MODE is deliberately decoupled from LLM_MODE (the cost switch can never disable auth), so
the DB-backed API tests opt into the dev identity EXPLICITLY here — exactly as a developer's
local run does. test_auth still exercises the live fail-closed path by constructing Settings
directly. setdefault keeps any caller-provided values authoritative.
"""

from __future__ import annotations

import os

os.environ.setdefault("LLM_MODE", "hermetic")
os.environ.setdefault("AUTH_MODE", "dev")
