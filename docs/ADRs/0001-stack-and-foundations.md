# ADR 0001 — Stack, model pins, and source-of-truth decisions

- Status: Accepted
- Date: 2026-06-09
- Context: Greenfield build of the Capability Intelligence Agent (CIA). The product is fully specified
  (PRD, TRD, UI/UX, AppFlow, Backend-Schema + `schema.sql`, the F1–F15 build manual, Engineering Handoff,
  and a React prototype). This ADR records the decisions confirmed at kickoff so later work doesn't
  re-litigate them.

## Decisions

1. **Architecture (per TRD §4).** One Cloud Run service = FastAPI backend + built Vite/React SPA in a single
   `linux/amd64` container. Postgres 16 (Cloud SQL) with pgvector (HNSW) + tsvector (GIN) hybrid retrieval in
   one engine. Two-plane schema: shared `control.*` (Alembic-migrated) + per-version `cat_<version>` data
   planes generated from `control.relation_def`. Jobs via Cloud Run Jobs + Scheduler + Tasks (+DLQ). Cloud
   Storage, Secret Manager, Firebase Auth, Vertex AI.

2. **Source of truth for the build manual.** The June-8 `Implementation.html` (F1–F15, §14–§19, per-surface
   specs) is canonical. `Implementation-Steps-overview.html` (June-3) is a supporting overview only.

3. **Gemini model pins (Vertex AI, `us-central1`, IAM only — no long-lived keys).** Pinned by version in
   `config/models.yaml` (never `-latest`):
   - classify → `gemini-3.1-flash-lite`
   - enrich / match / ground → `gemini-3.5-flash` (GA)
   - **synthesis / adversarial → `gemini-3.1-pro-preview`** — a Preview model, accepted for v1; swap to
     Gemini Pro GA via config when it ships. No Claude/Anthropic integration in v1.
   - embeddings → `gemini-embedding-001` at **768** dims (MRL truncation; matches `cat_<v>.subcap.embedding
     vector(768)`).
   Verified prices/levers (2026-06-09): Batch −50%, context-cache −90% on cached input, grounded Google
   Search 5k free then ~$14/1k, non-global endpoint +~10% from 2026-07-01.

4. **Firebase Auth in the same project** `digital-maturity-assessor`; Google sign-in restricted to
   `@zennify.com`, fails closed.

5. **Schema additions beyond the reference DDL.** The Alembic baseline adopts `schema.sql` and adds the SOW
   pipeline tables (`sow_document`, `sow_scope_item`, `sow_subcap_match`), `benchmark`, and the enums
   `catalogue_impact`, `source_type`, `offering_tier`, `data_product_category` (referenced by the build
   manual's surface specs). This reconciles the "~71 tables / 20 enums" narrative with the 16 enums / 67
   tables literally present in `schema.sql`.

6. **Versioning & CI.** SemVer, Conventional Commits, annotated tags, Keep-a-Changelog. Trunk-based with
   short-lived branches + PRs. CI runs ruff/black/mypy/pytest (backend, with Alembic against an ephemeral
   Postgres 16 + pgvector from Stage 1) and eslint/tsc/vitest/build (frontend). Images tagged by git SHA +
   SemVer and deployed by digest; schema versions = ordered Alembic revisions. Lockfiles (`uv.lock`,
   `pnpm-lock.yaml`) are committed and CI installs frozen.

7. **Delivery approach.** Hermetic-dev first (`LLM_MODE=hermetic`, deterministic stubs, no provider creds, no
   cloud), then Terraform/IaC authored and reviewed, then applied with explicit approval, then live + canary
   deploy. Every irreversible/costly/prod-affecting action is a human-in-the-loop gate (§8) and is blocked by
   the PreToolUse hook.

## Consequences
- The Preview dependency on `gemini-3.1-pro-preview` is tracked as a risk; swapping to GA is a config change.
- `cat_<version>` is generated (not Alembic-migrated); only `control.*` is under Alembic.
- Tooling of record (ruff/black/mypy + eslint/prettier/tsc) is enforced by CI and the PostToolUse hook.
