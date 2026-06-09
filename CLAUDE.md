# CLAUDE.md — Capability Intelligence Agent (CIA)

Always-loaded rule sheet. Authoritative plan: `/root/.claude/plans/indexed-enchanting-llama.md`.
Canonical specs live in `docs/specs/` (HTML is canonical; `docs/specs/text/` are convenience extractions).
Index of specs → detail: `docs/SPEC.md`.

## What this is
Internal, trust-first consultant workbench (~10–30 users) over a four-pillar capability catalogue
(851 subcaps) + a canonical 14,406-row Jira delivery corpus. One Cloud Run service = FastAPI backend +
built Vite/React SPA. Postgres 16 + pgvector + tsvector (hybrid retrieval). Two-plane schema:
shared `control.*` + per-version `cat_<version>`. Gemini via Vertex AI (IAM, no keys).

## Stack
- Backend: Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 (async), Alembic, `uv` for deps.
- Frontend: Vite + React 18 + TypeScript, react-router v6, Zustand, TanStack Query; `pnpm`.
- DB: Cloud SQL Postgres 16, pgvector (HNSW) + tsvector (GIN). Embedding space `vector(768)`.
- Infra: Cloud Run (service + Jobs), Scheduler, Tasks (+DLQ), Cloud Storage, Secret Manager,
  Firebase Auth (`@zennify.com`, fails closed), Vertex AI. GCP project `digital-maturity-assessor` / `us-central1`.

## Commands (run from repo root)
- Backend deps:    `cd backend && uv sync`
- Lint/format:     `cd backend && uv run ruff check . && uv run black --check .`
- Typecheck:       `cd backend && uv run mypy .`
- Test:            `cd backend && uv run pytest -q`
- Migrate (local): `cd backend && uv run alembic upgrade head`   (NEVER on app startup; see safeguards)
- Frontend deps:   `cd frontend && pnpm install`
- Frontend checks: `cd frontend && pnpm lint && pnpm typecheck && pnpm test && pnpm build`
- Local stack:     `docker compose -f docker-compose.dev.yml up`  (Postgres 16 + pgvector)
- Container:       `docker buildx build --platform linux/amd64 -t cia:dev .` then run, hit `/healthz`
- Hermetic mode:   set `LLM_MODE=hermetic` (deterministic stubs; no provider creds, no cloud, no spend)

## Directory map
```
backend/app/{main,settings,db,migrate,deps}.py
backend/app/{routers,services,intelligence,models,jobs,resilience}/
backend/alembic/  backend/tests/
frontend/src/{components,pages,state,api}/  frontend/src/tokens.css
config/{models.yaml,schedules.yaml,gates.yaml}
terraform/{envs,modules}/
docs/{specs,ADRs,SPEC.md}
.claude/{settings.json,hooks,agents}
```

## NON-NEGOTIABLE SAFEGUARDS (hard rules)
1. **Verify before "done".** Never claim done until typecheck + lint + the affected tests pass. If tests
   fail, say so with output. No fabricated results.
2. **Gated mutation.** Nothing AI-derived (catalogue edit, KG edge, SOW link, suggestion, offering) is
   shown or committed without passing the 8 deterministic gates **G1–G8 (code, not prompts)**. An apply
   **re-gates server-side** and writes a versioned snapshot + an append-only `audit_log` row.
3. **Trust envelope is mandatory** on every surface that shows an AI value: claim label, source tier, ERS,
   reasoning-chain backlink. No opaque codes.
4. **Grounded only.** AI reasons only over retrieved stored evidence (hybrid lexical + dense + structured,
   active version). Always cite (G5/G7). No answers from model memory. Grounded search feeds the store and
   is gated before influencing any conclusion.
5. **Never migrate on app startup.** Migrations run as a one-shot Cloud Run Job to completion **before** the
   new revision gets traffic. Advisory lock on a **direct** connection, `lock_timeout`, version-check skip,
   transactional DDL, expand/contract, `CREATE INDEX CONCURRENTLY` outside a txn. Terraform triggers the
   Job; it never embeds migrations. `control.*` = Alembic; `cat_<version>` = generated per version.
6. **Secrets.** Never commit secrets or `.env`. Secrets come from Secret Manager. Services run as
   least-privilege SAs. No long-lived keys (Vertex + WIF use IAM).
7. **No PII in logs. DLP-redact** before any model sees a SOW or sensitive source.
8. **Gemini** calls go through the one wrapper `intelligence/gemini.py`; models **pinned by version**
   (`config/models.yaml`, never `-latest`); retry 429/5xx w/ backoff+jitter; MAX_TOKENS→raise/chunk;
   SAFETY→review; 4xx no-retry. Cost: Batch −50%, context-cache −90%, weekly cadence, **G8 budget gate**
   + cost meter (alert 80% / throttle 90% / fallback).
9. **Self-healing reused, not re-coded** (`backend/app/resilience/`): retries+backoff+jitter, idempotency
   keys, circuit breaker, DLQ+poison, watchdog/reaper, reconciliation, integrity self-checks, graceful
   shutdown, auto-rollback, bounded-everything. Nothing is ever silently dropped — failures queue to
   review (Change Flags) or the DLQ.
10. **Human-in-the-loop (§8).** Pause and present the exact command + expected effect before anything
    irreversible/costly/prod-affecting: enabling APIs, `terraform plan/apply`, creating Cloud SQL,
    creating SAs/IAM bindings, deploying, migrating a non-dev DB, creating/rotating secrets, or spending
    real model budget. These are also blocked by the PreToolUse hook.
11. **Scope discipline (v1).** Internal only; single `is_admin` role; **public sources only** (D6); **no
    cross-pillar capability surface** (D16). Build to the prototype + specs; do not gold-plate.

## Versioning & git
- SemVer; Conventional Commits; annotated tags; maintained `CHANGELOG.md`.
- Trunk-based, short-lived branches, PRs; `main` stays releasable. Never force-push; never rewrite shared history.
- Container images tagged by git SHA + SemVer, deployed by digest. Schema versions = ordered Alembic revisions.
- Surface app version + active catalogue version in the UI and `/healthz`.

## Model pins (confirmed; see config/models.yaml)
classify → `gemini-3.1-flash-lite` · enrich/match/ground → `gemini-3.5-flash` (GA) ·
synthesis/adversarial → `gemini-3.1-pro-preview` (Preview; swap to GA via config) ·
embeddings → `gemini-embedding-001` @ 768 dims. All via Vertex AI in `us-central1`, IAM-based.
