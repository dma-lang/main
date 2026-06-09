# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **F10 — frontend shell**: the React/TS shell ported faithfully from the prototype — the full
  stylesheet (lifted verbatim), the 9-group A–I sidebar, the header (pillar/SV/lens, data-driven
  version toggle, admin view, cost meter, theme), the shared primitives (`Claim/Tier/Mag/LifeChip/
  Page/Empty/Dropdown/Icon`), the `cia-*` event contract, hash routing, Zustand + TanStack Query
  wired to `/api/me` (identity/admin/preferences) and `/api/versions`. Surfaces are placeholders
  until Stage 2. Verified by building, serving from FastAPI same-origin, and headless-rendering the
  shell (light + dark) on live data.
- **F9 — API conventions & trust envelope**: the mandatory `TrustEnvelope`
  (claim_label / source_tier / ers / chain_id) + DB-mirrored enums; generic `Page[T]` pagination;
  a single error envelope (`{"error": {"code", "message"}}`); version resolution
  (`resolve_version` → 404). `GET /api/versions` + `GET /api/versions/{version}` (Version timeline
  read). Pydantic mypy plugin enabled. Verified end-to-end (14 DB tests; live error envelope).
- **F2 — auth & identity**: Firebase ID-token verification (google-auth) with `@zennify.com`
  fail-closed allow-list and a deterministic hermetic dev identity; `control.users` upsert
  (config-driven `is_admin`); `GET /api/me` + `PATCH /api/me/preferences` (the server home for the
  prototype's `cia_theme`/`cia_lens`/`cia_persona`); `require_admin` gate. Verified end-to-end
  (10 DB-backed tests; live `/api/me` + preference persistence).
- **F3 — control-plane schema & migrations**: Alembic baseline adopting `docs/specs/schema.sql`
  (control plane only: 16 enums, 35 tables, 11 indexes, 1 view) via vendored, regenerable DDL;
  async DB engine (asyncpg, bounded pool, pre-ping); sync Alembic + a one-shot advisory-lock runner
  (`app/migrate.py`: direct connection, `lock_timeout`, at-head skip, transactional DDL — never on
  app startup); `/healthz` now reports DB status + active catalogue version. Verified end-to-end on
  Postgres 16 + pgvector (upgrade / downgrade / re-upgrade idempotent).
- **F1 — service skeleton**: FastAPI app with `/healthz` + `/livez` probes (§16), env-driven
  settings (`LLM_MODE`/`PORT`/`DATABASE_URL`), graceful-shutdown lifespan, and resilient SPA static
  serving (API-only when no build is present). Verified by a live uvicorn boot on `0.0.0.0:$PORT`.
- Repository scaffold (Stage 0): monorepo layout, tooling configuration, and CI skeleton.
- `CLAUDE.md` rule sheet encoding the non-negotiable safeguards.
- Canonical specs committed under `docs/specs/` and indexed by `docs/SPEC.md`.
- Project safety hooks (`.claude/hooks/`) and subagent definitions (`.claude/agents/`).
- `config/{models.yaml,schedules.yaml,gates.yaml}` — model pins, schedules, and gate thresholds as data.
- ADR 0001 recording the approved stack, model pins, and source-of-truth decisions.
