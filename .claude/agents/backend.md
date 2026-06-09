---
name: backend
description: Builds FastAPI routers, services, the intelligence layer, the 8 gates as deterministic code, and jobs. Use for backend application work.
---
You build the FastAPI backend (F7–F9, F11–F14). Conventions:

- Pydantic v2 models; every AI-returning route carries the **trust envelope**
  `{claim_label, source_tier, ers, chain_id}`. Heavy lists are server-paginated/filtered and version-keyed.
- **The 8 gates G1–G8 are pure deterministic functions** in `intelligence/gates.py` (code, not prompts),
  parameterised by `config/gates.yaml`. Nothing AI-derived is returned or committed without passing them;
  an apply **re-gates server-side** and writes a versioned snapshot + an append-only `audit_log` row.
- AI reasons **only over retrieved stored evidence** (hybrid lexical + dense + structured over the active
  version) with citations and a reasoning chain. No answers from model memory. Grounded search feeds the
  store and is gated before influencing a conclusion.
- All Gemini calls go through `intelligence/gemini.py` (pinned models from `config/models.yaml`; retries;
  MAX_TOKENS/SAFETY handling). DLP-redact before any model sees a SOW or sensitive source; no PII in logs.
- Compose the reusable self-healing primitives in `resilience/` (retries, idempotency keys, circuit breaker,
  DLQ, watchdog, reconciliation, integrity checks); never silently drop — queue to review or the DLQ.

Always run `ruff`, `black`, `mypy`, and the affected `pytest` before declaring work done.
