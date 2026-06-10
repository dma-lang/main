# Deployment guide — Capability Intelligence Agent

One Cloud Run service (FastAPI + built SPA in a single container), one Cloud Run **Job** for the
one-shot migration, Cloud SQL Postgres 16 + pgvector, Secret Manager, Vertex AI by IAM. The app
deploys **in one run** with `scripts/deploy_cloudrun.sh` (self-healing; see below). Infra is
Terraform's job (`terraform/`, security-reviewed before any apply) — the deploy script never
creates infrastructure, never edits IAM, never touches secrets.

## 0. Local verification (no cloud, no spend)

```bash
scripts/dev_up.sh                      # docker + pgvector Postgres + both DBs migrated + SPA
cd backend && DATABASE_URL=postgresql+asyncpg://cia:cia@localhost:5432/cia \
  LLM_MODE=hermetic AUTH_MODE=dev STATIC_DIR=$PWD/../frontend/dist \
  uv run uvicorn app.main:app --port 8092
# checks: ruff/black/mypy/pytest (backend) · eslint/tsc/vitest/build (frontend)
```

Container parity check (exactly what Cloud Run runs):

```bash
docker buildx build --platform linux/amd64 -t cia:dev .
# behind a rate-limited/proxied network, fall back to the mirrored official bases:
#   --build-arg NODE_IMAGE=mirror.gcr.io/library/node:20-bookworm-slim \
#   --build-arg PYTHON_IMAGE=mirror.gcr.io/library/python:3.12-slim-bookworm
docker run --rm --network host -e DATABASE_URL=... cia:dev uv run python -m app.migrate
docker run --rm --network host -e PORT=8093 -e DATABASE_URL=... cia:dev   # then GET /healthz
```

## 1. Prerequisites (one-time, human-gated — CLAUDE.md §8/§10)

| What | How | Why |
|---|---|---|
| Infra | `terraform apply` in `terraform/envs/<env>` after `security-reviewer` audit | SAs, Cloud SQL (private IP + backups/PITR), Artifact Registry, Secret Manager, the `cia-migrate` Job, Scheduler/Tasks |
| Operator auth | `gcloud auth login` + `roles/run.developer`, `roles/artifactregistry.writer` | the deploy script acts as you (or as `cia-deployer` via WIF in CI) |
| Secrets | `DATABASE_URL`, HMAC key, Firebase config in Secret Manager, mounted by Terraform | never in env files or images |

## 2. Service environment (set by Terraform on the service)

| Var | Prod value | Notes |
|---|---|---|
| `DATABASE_URL` | from Secret Manager | asyncpg DSN to Cloud SQL (private IP) |
| `LLM_MODE` | `live` | hermetic = deterministic stubs, zero spend |
| `AUTH_MODE` | `live` (default) | **decoupled from LLM_MODE — auth fails closed unless `dev` is set explicitly**; the cost switch can never disable authentication |
| `FIREBASE_PROJECT_ID` | project id | ID-token verification; `@zennify.com` fails closed |
| `ADMIN_EMAILS` | comma list | verified emails granted `is_admin` |
| `PORT` | injected by Cloud Run | the app binds `0.0.0.0:$PORT` |
| `STATIC_DIR` | *(unset)* | defaults to the baked SPA at `/app/static`, resolved against the app root (cwd-independent) |

## 3. Deploy — one run

```bash
PROJECT_ID=digital-maturity-assessor REGION=us-central1 ./scripts/deploy_cloudrun.sh
# optional canary: CANARY_PERCENT=10 PROJECT_ID=... ./scripts/deploy_cloudrun.sh
```

What the script does, in order — every step idempotent and retried (2/4/8/16s backoff), so a
re-run after any transient failure converges instead of duplicating:

1. **Preflight, fail-fast**: gcloud/docker present, clean git tree, right project, active account,
   required APIs enabled, the migrate Job exists, docker auth configured.
2. **Build** `linux/amd64` from the committed tree; on a Docker Hub 429 it **falls back to the
   GCR mirror of the same pinned base images** (`ARG NODE_IMAGE/PYTHON_IMAGE`). pnpm is pinned via
   `package.json#packageManager` (reproducible); optional corporate-proxy CAs go in `build-ca/`.
3. **Push** to Artifact Registry, then resolve and use the **immutable digest** — tags are never
   deployed.
4. **Migrate to completion** *before any traffic moves*: the `cia-migrate` Job runs
   `python -m app.migrate` (advisory lock on a direct connection, `lock_timeout 30s`, at-head
   no-op, transactional DDL). Re-running is a no-op; two racing runs cannot double-migrate.
5. **Deploy with `--no-traffic`** — the new revision exists but serves nothing.
6. **Smoke the new revision** through a tag-routed URL (`/healthz` must report `status:ok` +
   `db:ok`). Smoke failure leaves 100 % of traffic on the previous revision and exits nonzero.
7. **Promote** (optionally via `CANARY_PERCENT`), re-verify `/healthz`; **any failure rolls
   traffic back to the previous revision automatically**.

### Rollback

Cloud Run keeps prior revisions; the script auto-rolls-back on a failed promote. Manual:

```bash
gcloud run services update-traffic cia --region us-central1 --to-revisions <prev-revision>=100
```

Schema: migrations are expand/contract and additively reversible (`alembic downgrade` is CI-tested
per revision), but **revisions roll back without rolling back schema** — that is the point of
expand/contract.

### Catalogue data

A fresh environment serves an empty control plane honestly (`catalogue_version: null`, designed
empty states). Provision the catalogue once per environment (admin, idempotent):
`POST /api/admin/provision/v7` → `POST /api/admin/carry-forward/v7` → run the scans from Settings
(or let the schedulers fire). Data persists in Cloud SQL across deploys and revisions — deploys
never touch data.

## 4. Verified end-to-end (this is simulated in QA, not assumed)

The QA run exercises the full sequence locally with the production image: fresh DB → containerized
`app.migrate` (chain 0001→0007, idempotent re-run no-op) → service boot on `$PORT` → `/healthz`
`status:ok/db:ok` → SPA + favicon served → **`/api/me` 401 in hermetic LLM mode (fail-closed auth
proven in-container)** → SIGTERM graceful drain. Backend: 77 tests; frontend: lint/type/test/build;
27-route browser sweep with zero console/network errors.

## Known footguns (already engineered around)

- **Docker Hub 429**: use the mirror build-args (the script falls back automatically).
- **Corporate/sandbox TLS proxy**: drop the proxy CA PEM at `build-ca/extra-ca.crt` (gitignored);
  both build stages trust it; `UV_NATIVE_TLS` makes uv honor the system store.
- **Migrations on startup**: never — the app boots read-only against whatever schema exists; the
  Job owns DDL (CLAUDE.md safeguard 5).
- **`AUTH_MODE=dev` anywhere reachable**: never — it exists for local dev and tests only.
