# CLAUDE.md — Capability Intelligence Agent (CIA)

Always-loaded rule sheet + component map. Read top-to-bottom once; the SAFEGUARDS section is
binding on every change. Canonical specs live in `docs/specs/` (HTML canonical; `docs/specs/text/`
convenience extractions); index: `docs/SPEC.md`. Deployment runbook: `docs/DEPLOYMENT.md`.

## What this is
Internal, trust-first consultant workbench (~10–30 expert users) over a four-pillar capability
catalogue (851 subcaps: P1 Strategy · P2 Customer Experience · P3 Operations/Risk/Compliance ·
P4 Data & AI) + a canonical 14,406-row real-Jira delivery corpus (73 client projects, resolved
client names) + 4,552 labelled synthetic stories (never mixed into analysis). One Cloud Run
service = FastAPI backend + built Vite/React SPA served from `./static`. Postgres 16 + pgvector
(HNSW) + tsvector (GIN) hybrid retrieval. Two-plane schema: shared `control.*` (Alembic-migrated)
+ per-version `cat_<version>` (generated per catalogue version; v7 is the reference). Gemini via
Vertex AI (IAM, no keys) for live intelligence; a LOCAL MiniLM sentence model is the deterministic
zero-spend dense half (see ML stack).

## Stack
- Backend: Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 (async, asyncpg), Alembic, `uv`.
  ML runtime: `onnxruntime` + `tokenizers` + `numpy` (NO torch). `scikit-learn` is DEV-ONLY
  (training scripts); the runtime consumes exported JSON coefficients.
- Frontend: Vite + React 18 + TypeScript, react-router v6, Zustand (ephemeral UI state),
  TanStack Query (server state, keyed `[version, resource, filters]`); `pnpm`.
- DB: Postgres 16, pgvector `vector(768)` (HNSW cosine) + tsvector (GIN). One shared 768-d
  embedding space (gemini-embedding-001 live; MiniLM zero-padded 384→768 hermetic).
- Infra: Cloud Run (service `cia` + one-shot Job `cia-migrate`), Cloud SQL, Secret Manager,
  Firebase Auth (`@zennify.com`, fails closed), Vertex AI. GCP `digital-maturity-assessor` /
  `us-central1`.

## Commands (run from repo root)
- Backend deps:      `cd backend && uv sync`
- Lint/format:       `cd backend && uv run ruff check . && uv run black --check .`
- Typecheck:         `cd backend && uv run mypy .`
- Test (fast tier):  `cd backend && uv run pytest -q`               (DB + model tests auto-skip)
- Test (DB tier):    start Postgres, then
                     `DATABASE_URL=postgresql+asyncpg://cia:cia@localhost:5432/cia uv run pytest -q`
- Local stack:       `docker compose -f docker-compose.dev.yml up`  (Postgres 16 + pgvector)
                     or `scripts/dev_up.sh` (dockerd + DBs + migrate + SPA build, idempotent)
- Migrate (local):   `cd backend && uv run alembic upgrade head`    (NEVER on app startup)
- Frontend:          `cd frontend && pnpm install && pnpm lint && pnpm typecheck && pnpm test && pnpm build`
- ML model fetch:    `python scripts/fetch_minilm.py`               (~90MB, pinned SHA-256, gitignored;
                     absent model = graceful token-hash fallback, never a failure)
- Golden benchmark:  `backend/.venv/bin/python scripts/build_golden_benchmark.py`  (deterministic)
- Train matcher:     `backend/.venv/bin/python scripts/train_matcher.py`  (dev; exports config JSON)
- Container:         `docker buildx build --platform linux/amd64 -t cia:dev .` then run, hit `/healthz`
                     (build fetches MiniLM; `--build-arg SKIP_MINILM=1` to skip)
- Hermetic mode:     `LLM_MODE=hermetic` — deterministic, zero cloud, zero spend. With the MiniLM
                     files present, hermetic dense = REAL semantics (not just token overlap).

## Directory map
```
backend/app/{main,settings,db,migrate,deps,refresh}.py
backend/app/routers/       # HTTP surface (see Routers)
backend/app/services/      # domain logic (see Services)
backend/app/intelligence/  # models, gates, retrieval, ML stack (see Intelligence)
backend/app/jobs/schedule.py
backend/alembic/           # control-plane migrations + sql/{control_baseline,dataplane_template}.sql
backend/seed/              # committed data: catalogue_v7, stories (14,406), enrichment, vc-mapping,
                           # golden_matches (the ML benchmark), offerings
backend/models/minilm/     # GITIGNORED MiniLM onnx+tokenizer (scripts/fetch_minilm.py)
backend/tests/             # three tiers: pure / needs_db / needs_model (all auto-skip cleanly)
frontend/src/{pages,components,state,api,lib}/  frontend/src/tokens.css
config/{models,gates,schedules,value_chain,subvertical_aliases}.yaml + matcher_model.json
scripts/                   # ops + ML scripts (see Scripts)
docs/{specs,SPEC.md,DEPLOYMENT.md}   terraform/   .claude/{settings.json,hooks,agents}
```

## NON-NEGOTIABLE SAFEGUARDS (hard rules)
1. **Verify before "done".** Never claim done until typecheck + lint + the affected tests pass. If
   tests fail, say so with output. No fabricated results — this includes ML metrics: report the
   measured number, never the aspirational one.
2. **Gated mutation.** Nothing AI-derived (catalogue edit, KG edge, SOW link, suggestion, offering,
   use-case proposal) is shown or committed without passing the 8 deterministic gates **G1–G8
   (code, not prompts)**. An apply **re-gates server-side** and writes a versioned snapshot + an
   append-only `audit_log` row.
3. **Trust envelope is mandatory** on every surface that shows an AI value: claim label, source
   tier, ERS, reasoning-chain backlink. Delivery rows carry per-carry provenance
   (`carry_status/carry_similarity/carry_via` → Review / Re-routed / match% badges).
4. **Grounded only.** AI reasons only over retrieved stored evidence (hybrid lexical + dense +
   structured, active version). Always cite (G5/G7). No answers from model memory.
5. **Never migrate on app startup.** Migrations run as a one-shot Cloud Run Job to completion
   **before** the new revision gets traffic (advisory lock on a direct connection, `lock_timeout`,
   at-head skip, transactional DDL, expand/contract, `CREATE INDEX CONCURRENTLY` outside txn).
   `control.*` = Alembic; `cat_<version>` = generated per version from `dataplane_template.sql`.
6. **Secrets.** Never commit secrets or `.env`. Secret Manager only; least-privilege SAs; no
   long-lived keys (Vertex + WIF use IAM).
7. **No PII in logs. DLP-redact** before any model sees a SOW or sensitive source.
8. **Model calls** go through the one wrapper `intelligence/gemini.py`; models **pinned by version**
   (`config/models.yaml`, never `-latest`); retry 429/5xx with backoff+jitter; MAX_TOKENS→chunk;
   SAFETY→review; 4xx no-retry; **G8 budget gate** + cost meter (alert 80% / throttle 90%).
   Hermetic mode never touches the network: embeddings come from the local MiniLM (preferred)
   or the token-hash stub (fallback) — both deterministic, both zero spend.
9. **Self-healing reused, not re-coded**: retries+backoff+jitter, idempotency keys, DLQ+poison,
   watchdog/reaper, integrity self-checks, graceful shutdown, auto-rollback, bounded-everything.
   Nothing silently dropped — failures queue to review (Change Flags) or are logged loudly.
10. **Human-in-the-loop.** Pause and present the exact command + expected effect before anything
    irreversible/costly/prod-affecting: enabling APIs, `terraform plan/apply`, creating Cloud SQL,
    SAs/IAM bindings, deploying, migrating a non-dev DB, secrets, or real model spend. The
    PreToolUse hook also blocks these (and destructive SQL, force-push, .env edits).
11. **Scope discipline (v1).** Internal only; single `is_admin` role; public sources only; no
    cross-pillar capability surface. Build to the prototype + specs; do not gold-plate.

## How the data flows (read this before touching matching/delivery)
1. **Provision** (`services/provision.py::bring_version_online`): parses/loads a catalogue version
   into a fresh `cat_<v>` schema (DROP CASCADE + rebuild, transactional). Seeds subcaps,
   capabilities (L2), categories (L1), use cases, platforms, personas, value-chain mapping,
   offerings; inherits enrichment cross-version via `subcap_xref` when a version is base-only.
2. **Carry** (`services/stories.py::carry_forward`): ingests the canonical corpus into
   `control.story` (client identity: `client_name` resolved per story; `project_key` is only the
   Jira code) and rebuilds `control.story_subcap_carry` for the version: native id-hit →
   nearest-neighbour (banded, dense-corroborated) → **relatedness gate** (below). Then use-case
   matching, story synthesis, subvertical rollups, offerings matching, KG mining, detectors —
   each best-effort, never blocking the carry.
3. **Relatedness gate** (`services/stories.py::_relatedness_gate` + `services/story_relatedness.py`):
   QAs NATIVE carries because source `sub_cap_id`s are measurably noisy. Lexical TF-IDF scores
   each story vs its assigned subcap and pillar siblings; clearly-misrouted carries are RE-ROUTED
   (requires ≥`min_reroute_terms` distinct shared discriminating terms — a single coincidental
   word never moves a story); wholesale dumping-ground subcaps (≥80% weak) get their orphans
   UNMAPPED (excluded from the analysis view). The trained matcher (see ML stack) may VETO a
   demotion only at near-certain precision; it self-disables when it cannot reach that bar.
   All knobs in `config/gates.yaml: matching.relatedness`.
4. **Analysis view** (`control.story_catalogue_link`, migration 0011/0012): Jira-only,
   `status IN (confirmed, review)` — every heatmap, count, drilldown and delivery tab reads THIS,
   so numbers reconcile everywhere. `unmapped` carries exist but never render.
5. **Deploy self-refresh** (`app/refresh.py`, run by the `cia-migrate` Job): alembic upgrade →
   re-provision + re-carry every provisioned version → re-run detectors. Marker-guarded: same
   image re-runs are no-ops. The Job gets 4Gi/2CPU (the corpus OOMs the 512Mi default).

## Services (backend/app/services/) — what each file owns
- `stories.py` — corpus ingest, carry-forward, nearest-neighbour pass, relatedness gate +
  trained-matcher veto, catalogue-ref links (author-curated story refs → `via='catalogue_ref'`),
  cross-version corpus inheritance. THE delivery-attribution pipeline.
- `story_relatedness.py` — deterministic TF-IDF relatedness scorer (`RelatednessIndex.classify`
  → fit/misrouted/review verdicts). Pure, no DB, no spend; the gate's lexical half.
- `story_insights.py` — per-subcap client grouping (by RESOLVED `client_name`) + greedy
  token-overlap story clustering for the delivery drilldown.
- `story_synthesis.py` — deterministic regex/rule NLP: raw Jira fields → structured facets
  (role/goal/AC/approach) + FACT-labelled third-person narrative. Never generative.
- `use_case_match.py` — per-subcap story→use-case attribution (TF-IDF + dense hybrid, single
  best match, floors in gates.yaml) feeding the Use Case Explorer's real per-UC counts.
- `use_case_gaps.py` — clusters unmatched delivery per subcap and proposes NEW use cases
  (gated G1–G8, human-approved via Change Flags).
- `offerings_match.py` — grounds the GTM offerings catalogue into subcaps by hybrid retrieval;
  `provision` seeds, this re-scores.
- `subverticals.py` — detects clients delivering outside the 9 modelled subverticals; each
  sufficiently-large, non-overlapping client becomes a gated candidate-subvertical Change Flag.
- `sv_rollups.py` — precomputed per-(entity × subvertical) delivery rollups for the SV lens.
- `sv_aliases.py` — config-driven canonicalisation of legacy SV codes/tiers (PEN→RIA etc.),
  applied at ingest, carry, read and in SQL. Deterministic; keep it that way.
- `value_chain.py` — value-chain stage derivation: dedupe/merge stage names (token Jaccard),
  canonical 8-bucket rollup (`config/value_chain.yaml` keyword→bucket map).
- `subcap_xref.py` — THE canonical cross-version subcap resolver (exact id → crosswalk → L2+desc
  → L2 → semantic cosine). Used by provision inheritance, read-fallback, story refs, VC cascade.
- `enrichment_seed.py` — read-time access to the committed v7 enrichment seed (deep-dive
  fallback for base-only versions; `story_refs_map()` = the author-curated exemplars).
- `enrichment_propagation.py` / `enrichment_relevance.py` — escalate approved use cases across
  versions; the necessity gate (fit + non-duplicate) before any enrichment lands.
- `kg.py` — knowledge-graph mining: structural co-occurrence, market-basket co-delivery
  (lift/PMI over client + story baskets), semantic cosine pairs, NLP directional relations —
  ALL as gated `pending_edge` proposals, never silent facts.
- `provision.py` / `workbooks.py` — version provisioning + xlsx parsing (pillar workbooks,
  VC-mapping, story catalog sheets; exact-alias header automap).
- `sow.py` — SOW clause→subcap matching pipeline (bands in gates.yaml; DLP before models).
- `trends.py` — multi-signal trend detection over gated evidence (velocity/diversity/novelty/
  persistence; thresholds in gates.yaml).
- `suggestions.py` / `change_flags.py` — the gated mutation lifecycle + the human-review inbox
  (approve re-gates server-side; nothing applies without G1–G8).
- `chat.py` — grounded RAG chat (retrieve → G5 grounding → cite; refuses when nothing retrieved).
- `digest.py` — quarterly synthesis + HMAC-signed exports. `clients.py` — client journey atlas.
- `evidence.py` / `benchmarks.py` / `sources.py` — news/benchmark evidence pipelines (map → gate
  → persist with ERS) + the source registry.
- `embeddings.py` — the idempotent one-shot that fills `cat_<v>.subcap.embedding` (batched,
  metered live; MiniLM/stub hermetic). `admins.py` / `users.py` — identity + prefs.

## Intelligence (backend/app/intelligence/) — models, gates, ML stack
- `gemini.py` — THE single model wrapper (safeguard 8). Live: Vertex google-genai, pinned tiers,
  retries, cost metering. Hermetic: deterministic stubs for ground/classify/infer; `embed()`
  prefers the LOCAL MiniLM and falls back to the token-hash vector.
- `local_embeddings.py` — sentence-transformers/all-MiniLM-L6-v2 via onnxruntime (no torch):
  `available()`, `encode(texts, pad_to=768)` (mean-pooled, L2-normalised, zero-padded —
  cosine-invariant), `cosine()`. Model files under `backend/models/minilm/` (env override
  `MINILM_DIR`), fetched by `scripts/fetch_minilm.py` (pinned revision + SHA-256). Absent model
  → everything degrades to the hash stub; nothing fails.
- `match_features.py` — the ONE feature contract shared by matcher training and runtime
  (`FEATURES`, `MatchFeaturizer`): MiniLM cosines vs subcap definition / use-case texts /
  author-curated exemplar stories, margins, per-story z-score, lexical TF-IDF, shared-term and
  name-overlap counts, exemplar-regime flags. Training excludes same-project exemplars
  (leakage guard); runtime uses all.
- `matcher_model.py` — runtime for the trained matcher: loads `config/matcher_model.json`
  (feature names, folded coefficients, intercept, thresholds, held-out metrics) → dot product +
  sigmoid. No sklearn at runtime. Feature-contract drift or a bad file disables it cleanly.
- `retrieval.py` — hybrid retrieval contract shared by chat/SOW/evidence/matchers: lexical
  ts_rank + optional dense HNSW cosine, merged/reranked. NOTE: evidence/sow/chat callers still
  default `use_dense=False`; flipping them requires recalibrating the ts_rank-scale floors.
- `gates.py` — every gate threshold as a typed accessor over `config/gates.yaml` (G1–G8 helpers,
  matching bands, relatedness config incl. `min_reroute_terms`/`use_model`, KG, trends,
  offerings, use-case floors). Config, not code — operators tune without a deploy.
- `cost_meter.py` — monthly spend vs envelope (G8). KNOWN GAP: fails open on DB outage.
- `model_config.py` — typed loader for `config/models.yaml` (pins, region, retry, dims, budget).
- `news.py` / `vendors.py` / `benchmarks.py` / `sow.py` — recorded hermetic fixtures + live
  enrichment paths for the evidence pipelines.

## ML stack & the golden benchmark (read before touching matching quality)
- **Labels**: the ONLY trustworthy story↔subcap labels are the catalogue authors' per-subcap
  story refs (`backend/seed/catalogue_v7.json.gz` `subcaps[].stories[].k`, 2,117 resolved pairs).
  The corpus `sub_cap_id` column is noisy (that's why the gate exists). Author curation used
  out-of-text knowledge — measured: the true subcap's median MiniLM rank is 112/851 — so
  pair-accuracy ≈98% from text alone is NOT reachable; do not chase it, and do not fake it.
- **Benchmark** (`scripts/build_golden_benchmark.py` → `backend/seed/golden_matches.json.gz`):
  author positives + clean cross-category negatives (lexical-hard / same-pillar / random),
  project-disjoint train/test split. Same-category negatives are deliberately excluded (39%
  measured label noise). Deterministic; re-running reproduces the identical file.
- **Trained matcher** (`scripts/train_matcher.py`, sklearn dev-only → `config/matcher_model.json`):
  standardized logistic regression, coefficients folded so runtime is pure math. Operating
  points: `threshold` = keep point (train keep-recall ≥98.5% → held-out keep-recall verified,
  currently 1.0000); `veto_threshold` = near-certain point (train precision ≥0.90, else 0.99 =
  self-disabled). CI lock: `tests/test_matcher_benchmark.py` recomputes held-out keep-recall
  from scratch and asserts ≥0.98 + stored-metric consistency.
- **Retraining workflow**: edit features in `match_features.py` (train + runtime share it) →
  `build_golden_benchmark.py` if labels changed → `train_matcher.py` → review printed held-out
  metrics + trade-off curve → commit the regenerated `config/matcher_model.json` + seed. The
  gate picks up a stronger model by config alone (veto activates when precision ≥0.90).

## Routers (backend/app/routers/) — HTTP surface
`catalogue.py` (the big one: subcap tree/detail/stories/delivery-drill/timeline, heatmap lenses,
value chain, platforms/vendors, use cases + matched-story drawers, KG + discovery, lifecycle),
`stories.py` (story library + drill), `chat.py` (SSE grounded chat), `evidence.py` (news/vendor/
benchmark feeds), `suggestions.py` + `governance.py` (gated apply/reject, change flags, gates log,
audit), `versions.py` (list/diff/revert), `sow.py`, `clients.py`, `digest.py`, `me.py`, `auth.py`,
`admin.py` (mapping studio, scans, embeddings build). Every list is version-keyed + paginated;
every AI value carries the trust envelope; errors use the `{"error":{"message"}}` envelope.

## Frontend map (frontend/src/)
- `pages/` — one file per surface: MissionControl (lens heatmaps + drill drawers), SubcapWorkbench
  (5-tab deep dive; Delivery tab shows carry badges), ValueChain (pipeline/radial/rollup),
  Platforms, UseCases (delivery-ranked + matched-story drawer), KnowledgeGraph (weighted edges +
  latent-discovery panel), StoryLibrary, SOW, Trace, News/Trends/Suggestions/Benchmarks, Digest,
  Lifecycle, Vendors, Clients, Versions/Diff/ChangeFlags/Gates/QA, Chat, WhatIf, Settings.
- `components/` — shared trust/UI primitives. Key: `StoryDetail.tsx` (ClientChip = resolved
  client name; CarryBadge = Review/Re-routed/match% from carry provenance; StoryQuality =
  composite+confidence+badge for `extra` slots), `DeliveryDrillPanel.tsx` (clients by RESOLVED
  name + project codes secondary; clusters; story lines), `SubcapPeek.tsx` (the shared quick-look
  drawer), `primitives.tsx` (Page/Seg/Chip/Bar/PillarDot/Claim/Tier), ReasoningModal, CommitModal.
- `api/client.ts` — the typed API contract (mirror backend Pydantic models; update BOTH sides).
- `state/` — Zustand UI store (pillar/sv/lens/version header state). `lib/` — helpers, events
  (`openPeek`/`openReasoning`/`go`), icons. `tokens.css` — the design system (DM Sans, teal
  #27bbaf, dark mode; identical to the prototype — do not re-theme).

## Testing (three tiers, all auto-skip cleanly)
- **Pure** (always runs): scorers, parsers, config, synthesis, relatedness (incl. the corpus-wide
  no-single-term-reroute invariant), story insights, model-contract checks.
- **needs_db** (`DATABASE_URL` set): provisioning, carry, endpoints, gated lifecycles. Module
  fixtures provision v7 + carry, so they're minutes-long; run against the compose Postgres.
- **needs_model** (MiniLM files present): `test_local_embeddings.py` (semantics, determinism,
  zero-pad invariance, absent-model fallback), `test_matcher_benchmark.py` (the ≥0.98 keep-recall
  lock, recomputed from scratch).
- PostToolUse hooks run ruff/black/mypy (backend) and eslint (frontend) on every edit and BLOCK
  until clean; line length is 100. PreToolUse blocks destructive SQL/deploy/secrets actions.

## Scripts (scripts/)
- `deploy_cloudrun.sh` — operator-run deploy: preflight → build (docker.io → GCR-mirror fallback
  via `try_retry`) → push by digest → `cia-migrate` Job (runs `app.refresh`, 4Gi/2CPU, 3600s) to
  completion → no-traffic deploy → tag-routed smoke → promote with auto-rollback.
- `doctor.sh` — operator-run GCP converge/heal: rederives config, heals DB credentials/ingress/
  org-policy, classify-and-heal migrate loop (auth/missing-db/transient/OOM ladder).
- `dev_up.sh` — idempotent local bootstrap (dockerd + Postgres + migrate + SPA build).
- `fetch_minilm.py` — pinned, SHA-verified MiniLM download (Dockerfile runs it; SKIP_MINILM=1).
- `build_golden_benchmark.py` / `train_matcher.py` — the ML benchmark + trainer (see ML stack).
- `regen_enrichment_from_catalogue.py` — rebuilds the enrichment seed from the base catalogue.
- `qa_walk.py` / `qa_visual.mjs` / `qa_transitions.mjs` — post-deploy contract walk + Playwright
  visual/auth-transition sweeps. `extract_prototype.py` — decodes the design prototype bundle.

## Versioning & git
- SemVer; Conventional Commits; annotated tags; maintained `CHANGELOG.md`.
- Trunk-based; `main` stays releasable. Never force-push; never rewrite shared history.
- Images tagged by git SHA, deployed by digest. App version + active catalogue version surface in
  the UI and `/healthz`.
- The workspace can be reclaimed between turns: COMMIT EARLY, PUSH EARLY; after any push failure,
  save `git bundle` insurance to the session scratchpad before ending a turn.

## Model pins (config/models.yaml)
classify → `gemini-3.1-flash-lite` · enrich/match/ground → `gemini-3.5-flash` ·
synthesis/adversarial → `gemini-3.1-pro-preview` (swap to GA via config) · embeddings →
`gemini-embedding-001` @768 (live) / local `all-MiniLM-L6-v2` @384→768 (hermetic, pinned in
`scripts/fetch_minilm.py`). All live calls via Vertex AI `us-central1`, IAM-based.

## Known follow-ups (from the full-script audit; prioritized, none blocking)
1. `cost_meter.py` fails OPEN (DB outage disables the G8 throttle) + non-UTC month boundary.
2. `jobs/schedule.py`: `replace(day>28)` ValueError; hourly branch silently ignores DOW/DOM;
   lru_cache vs model_config's re-read (inconsistent reload policies).
3. `qa_walk.py` crashes (URLError/KeyError) where it should record FAIL.
4. evidence/sow/chat retrieval still `use_dense=False` — flipping to the real MiniLM hybrid
   needs recalibrating the ts_rank-scale floors (`relevance_floor` 0.025/0.04) to cosine scale.
5. Recalibrate hash-era cosine floors to the MiniLM scale: `xref` 0.62/0.60, KG semantic 0.85,
   `enrichment_relevance` prefilter/overlap, use-case `sem_floor` 0.82.
6. `kg.py`: lift has no significance floor (min_count=3 can be chance); magic `_strength` ramp.
7. `trends.py` union-find chaining → embedding clustering (docstring already specifies it).
8. `value_chain.py` keyword bucketing → nearest-centroid over the 8 canonical stage embeddings.
9. `workbooks.py` exact-alias header automap → similarity automap (labels: the alias dict).
10. `regen_enrichment`: `assert` integrity check (stripped under -O) + in-place seed overwrite.
