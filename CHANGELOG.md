# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed
- **Sign-in completed but never redirected**: when Google's popup closed, the window-focus
  refetch re-fired the errored `/api/me` query WITHOUT the token; its stale 401 landing after the
  fresh identity bounced the gate straight back to the Login page (and the API layer's 401
  handler yanked the hash back to `#/login`). Identity now never refetches on focus/reconnect,
  the sign-in cancels in-flight `['me']` fetches before installing the fresh identity, a 401
  from a token-less request can no longer unseat a session that holds a token, and the post-
  sign-in `/api/me` wait is bounded (20s → retryable error, never an infinite spinner). The
  backend's Google-certs fetch is bounded too (10s — a hung fetch would have hung every sign-in).
- **No sign-out existed**: Settings now has Sign out — clears the Google ID token and every
  cached query, lands on the Login page.
- **Silent blank sign-in button**: when Google refuses to render the button (origin missing from
  the OAuth client's Authorized JavaScript origins) the Login now says exactly that, with the
  origin to add, instead of an empty space.

### Added (QA)
- **Live-auth transition harness (`scripts/qa_transitions.mjs`)**: the sign-in flow could never
  be automated against real Google — every auth bug hid there. The harness stubs ONLY Google's
  GSI script (+ `/api/config` forced live) and drives the real SPA against the real hermetic
  backend through login → mission control (including the stale-401 race, reproduced
  deterministically), a full 25-item sidebar walk, deep-link reload session restore, and
  sign-out → login.
- **Stale-build tripwire** in `qa_visual` + `qa_transitions`: both refuse to run unless the
  server serves exactly the bundle `frontend/dist` holds (a forgotten `backend/static` copy had
  been silently shadowing fresh local builds — production was unaffected, the Docker build bakes
  `dist` itself).

### Added
- **Pillar-wise workbook parser (FR-1, real)**: `services/workbooks.py` parses an uploaded ZIP of
  per-pillar .xlsx capability maps into the provisioning seed — tolerant header aliasing across the
  v5/v7 variants (incl. the v5 Pillar-3 layout), consolidated/archived files ignored, unparseable
  rows counted (never invented), corrupt members a clean 400. The upload endpoint now writes the
  seed it parses (`catalogue_<v>.json.gz`): the upload IS the version's source. Committed seeds for
  **v5 (837 subcaps / 17 categories)** and v7 (851), both regenerated from the real workbooks.
- **Subcap-ID governance**: ids are never reused, recycled, or minted. An in-source ID collision
  (two different subcaps under one id — the real v5 `P2C3.2.IC1` case) is reconciled by name
  against the governing version's ID register (v7) and recorded in `control.version_crosswalk`
  (`id-governance:` notes); unresolvable colliders surface as `id_conflicts` for a human, kept out
  of the seed but never silently dropped. Crosswalk records defer (not fail) when the register's
  version isn't provisioned yet and land self-healing on its provision; the upload manifest and
  onboarding surface reconciliations/conflicts.
- **Jira vs synthetic story split**: the v7 workbooks' embedded story catalogue (4,552 GEN-*/PUB-*
  rows: gen_stories_v1 / gen_synthesized_gap_fill / use_case_derived_public_validated) ingests as
  `is_synthetic` + `source_system`, per-version seeds (`stories_synthetic_<v>.json.gz`) extracted
  on upload. **Analysis is Jira-only by construction** — migration 0011 redefines
  `story_catalogue_link` to join `control.story` and exclude synthetic rows, so heatmap, counts,
  lifecycle, trace and gates only ever see the canonical 14,406-row corpus. The story library
  shows the split (default "Jira only"; `synthetic=include|only` behind an explicit filter, rows
  chipped "synthetic · provisional").
- **Carry-forward nearest-neighbour fallback**: carries the id rules can't place run a banded
  lexical NN over the target catalogue (config `gates.yaml` matching bands, shared with the SOW
  matcher): v7 now carries 14,406/14,406 (13,656 native + 750 nearest-neighbour, all auditable
  via `via`/`similarity`); v5 carries clean too.
- **Most-recent version default everywhere**: highest *numeric* version id (not `created_at`) on
  `/healthz`, active-version resolution, `/api/versions` order, and the SPA header/default —
  re-provisioning legacy v5 can never steal the default from v7. Onboarding gains a target-version
  field (any `v<n>`), so multiple versions provision side by side.
- **Catalogue read endpoints (version-scoped, F9)**: `GET /api/catalogue/{v}/subcaps` (tree),
  `/subcaps/{id}` (detail), `/summary` (per-pillar counts) over `cat_<version>`; pillar counts match
  the PRD (P1 205 / P2 292 / P3 164 / P4 190). `version_id` validated as a SQL identifier (hardening).
- **F4 — per-version provisioning (core)**: `bring_version_online()` generates the per-version
  `cat_<version>` data plane (32 tables, from the `schema.sql` template) and seeds the real v7
  catalogue (851 subcaps / 136 capabilities / 16 categories / 4 pillars) transactionally, then
  registers the version. Committed gzipped seed (catalogue + sample stories) extracted from the
  prototype's data. `POST /api/admin/provision/{version}` (admin); `/api/versions` + `/healthz`
  reflect the provisioned version. The automap workbook-ingest studio layers on top later.
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
