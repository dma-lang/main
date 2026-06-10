# Deployment runbook — Capability Intelligence Agent

This is the complete, operator-grade runbook: every configuration the app needs, the exact
commands that create it, and a **validation block after every step** — nothing is assumed to
work; everything is checked. Architecture: **one Cloud Run service** (FastAPI + built SPA in one
container) + **one Cloud Run Job** (`cia-migrate`, one-shot migrations) + **Cloud SQL Postgres 16
with pgvector** + Secret Manager + Vertex AI by IAM (no API keys anywhere).

- Project `digital-maturity-assessor` · region `us-central1` · service `cia` · job `cia-migrate`
- Every step is **idempotent**: re-running a `create` that already exists is a no-op or a clean
  "already exists" error you can ignore; the deploy script converges on re-run.
- Anything marked **HUMAN-GATED** is paid/irreversible/prod-affecting (CLAUDE.md §8/§10): an
  operator runs it deliberately. `terraform/` will codify §3 verbatim in a later stage; until
  then this runbook **is** the source of truth for configuration.

---

## 1. Step one — pull the GitHub repo in Cloud Shell (always first)

All deploys run from [Cloud Shell](https://shell.cloud.google.com) (gcloud + docker + git
preinstalled, acts as your identity, no laptop credentials, no JSON keys). The deploy script
deploys exactly what is committed — it refuses a dirty tree and stamps images with the git SHA —
so the pulled clone is the source of truth for every run.

```bash
# first time on this Cloud Shell home directory:
gh auth login                                  # or a GitHub PAT via git credential store
git clone https://github.com/dma-lang/main.git cia
cd cia

# EVERY subsequent deploy starts exactly here:
cd ~/cia
git fetch origin
git checkout main && git pull --ff-only       # or: git checkout <release-tag>
```

**Validate:**

```bash
git status --porcelain                # MUST print nothing (clean tree)
git log --oneline -1                  # the exact commit you are about to deploy
ls scripts/deploy_cloudrun.sh docs/DEPLOYMENT.md && echo REPO-OK
```

---

## 2. One-time per Cloud Shell session

```bash
export PROJECT_ID=digital-maturity-assessor REGION=us-central1
gcloud config set project "$PROJECT_ID"
gcloud auth list                       # confirm the ACTIVE account is the intended operator
```

**Validate:** `gcloud config get-value project` prints the project;
`gcloud projects describe "$PROJECT_ID" --format='value(lifecycleState)'` prints `ACTIVE`.

---

## 3. One-time environment bootstrap (HUMAN-GATED)

Run once per environment, in order. Skip any step whose validation already passes.

### 3.1 Enable APIs

```bash
gcloud services enable run.googleapis.com sqladmin.googleapis.com \
  secretmanager.googleapis.com aiplatform.googleapis.com \
  artifactregistry.googleapis.com cloudscheduler.googleapis.com \
  cloudtasks.googleapis.com storage.googleapis.com \
  identitytoolkit.googleapis.com vpcaccess.googleapis.com \
  servicenetworking.googleapis.com compute.googleapis.com
```

**Validate:**

```bash
for api in run sqladmin secretmanager aiplatform artifactregistry vpcaccess identitytoolkit; do
  gcloud services list --enabled --filter="name:${api}.googleapis.com" --format='value(name)' \
    | grep -q . && echo "OK  $api" || echo "MISSING  $api"
done
```

### 3.2 Service accounts + IAM (least privilege, no Owner/Editor, no `allUsers` on data)

```bash
for sa in cia-run cia-jobs cia-scheduler; do
  gcloud iam service-accounts create "$sa" --display-name "$sa" || true
done
RUN_SA="cia-run@${PROJECT_ID}.iam.gserviceaccount.com"
JOBS_SA="cia-jobs@${PROJECT_ID}.iam.gserviceaccount.com"
SCHED_SA="cia-scheduler@${PROJECT_ID}.iam.gserviceaccount.com"

# cia-run: the service — SQL client, secrets read, Vertex calls, GCS objects, telemetry
for role in roles/cloudsql.client roles/secretmanager.secretAccessor \
            roles/aiplatform.user roles/storage.objectUser \
            roles/logging.logWriter roles/monitoring.metricWriter roles/cloudtrace.agent; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member "serviceAccount:${RUN_SA}" --role "$role" --condition=None --quiet
done
# cia-jobs: the migrate job — same + nothing more
for role in roles/cloudsql.client roles/secretmanager.secretAccessor roles/logging.logWriter; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member "serviceAccount:${JOBS_SA}" --role "$role" --condition=None --quiet
done
# cia-scheduler: may only invoke (run.invoker is granted on the specific resources in 3.9)
```

**Validate:**

```bash
gcloud iam service-accounts list --format='value(email)' | grep -E 'cia-(run|jobs|scheduler)'
gcloud projects get-iam-policy "$PROJECT_ID" \
  --flatten='bindings[].members' --filter="bindings.members:${RUN_SA}" \
  --format='value(bindings.role)' | sort
# expect exactly the seven cia-run roles listed above — anything more is a finding
```

### 3.3 Artifact Registry

```bash
gcloud artifacts repositories create cia --repository-format=docker \
  --location="$REGION" --description="CIA images (deployed by digest)" || true
gcloud auth configure-docker "${REGION}-docker.pkg.dev" --quiet
```

**Validate:** `gcloud artifacts repositories describe cia --location "$REGION"` succeeds.

### 3.4 Networking for private Cloud SQL (VPC connector)

```bash
gcloud compute addresses create google-managed-services-default \
  --global --purpose=VPC_PEERING --prefix-length=16 --network=default || true
gcloud services vpc-peerings connect --service=servicenetworking.googleapis.com \
  --ranges=google-managed-services-default --network=default || true
gcloud compute networks vpc-access connectors create cia-svpc \
  --region "$REGION" --network default --range 10.8.0.0/28 || true
```

**Validate:** `gcloud compute networks vpc-access connectors describe cia-svpc --region "$REGION"
--format='value(state)'` prints `READY`.

### 3.5 Cloud SQL — Postgres 16 + pgvector, private IP, backups + PITR

```bash
gcloud sql instances create cia-pg \
  --database-version=POSTGRES_16 --tier=db-custom-2-7680 --region="$REGION" \
  --network=default --no-assign-ip \
  --backup --backup-start-time=03:00 --enable-point-in-time-recovery \
  --maintenance-window-day=SUN --maintenance-window-hour=4
gcloud sql databases create cia --instance=cia-pg
APP_DB_PASSWORD="$(openssl rand -base64 24)"          # used once in 3.6, then discard the shell var
gcloud sql users create cia --instance=cia-pg --password="$APP_DB_PASSWORD"
PRIVATE_IP="$(gcloud sql instances describe cia-pg --format='value(ipAddresses[0].ipAddress)')"
```

pgvector ships with Cloud SQL PG16; migrations run `CREATE EXTENSION IF NOT EXISTS vector`.

**Validate:**

```bash
gcloud sql instances describe cia-pg \
  --format='value(state, settings.ipConfiguration.ipv4Enabled, settings.backupConfiguration.enabled, settings.backupConfiguration.pointInTimeRecoveryEnabled)'
# expect: RUNNABLE  False  True  True     (private-only, backups on, PITR on)
echo "$PRIVATE_IP"                                    # a 10.x address
```

### 3.6 Secret Manager — all runtime secrets (never in env files, never in images)

```bash
printf 'postgresql+asyncpg://cia:%s@%s:5432/cia' "$APP_DB_PASSWORD" "$PRIVATE_IP" \
  | gcloud secrets create cia-database-url --data-file=- || \
  printf 'postgresql+asyncpg://cia:%s@%s:5432/cia' "$APP_DB_PASSWORD" "$PRIVATE_IP" \
  | gcloud secrets versions add cia-database-url --data-file=-
openssl rand -base64 32 | gcloud secrets create cia-hmac-key --data-file=- || true
unset APP_DB_PASSWORD

for sa in "$RUN_SA" "$JOBS_SA"; do
  for s in cia-database-url cia-hmac-key; do
    gcloud secrets add-iam-policy-binding "$s" \
      --member "serviceAccount:${sa}" --role roles/secretmanager.secretAccessor --quiet
  done
done
```

**Validate:**

```bash
gcloud secrets versions list cia-database-url --format='value(name,state)' | head -1   # 1 ENABLED
gcloud secrets get-iam-policy cia-database-url --format='value(bindings.members)' \
  | tr ';' '\n' | grep -c cia-   # expect 2 (run + jobs); the operator does NOT keep accessor
```

### 3.7 Auth — Firebase / Identity Platform (`@zennify.com`, fails closed)

In the console (one-time UI steps, no CLI equivalent): enable **Identity Platform** for the
project → add the **Google** sign-in provider → restrict the OAuth consent screen to the
workspace → add the Cloud Run service domain to **Authorized domains** once it exists (3.8).
Create a **Web app** to obtain the web API key for the SPA login (used by the frontend login
page when it lands; the backend needs only the project id).

App-side configuration (set in 3.8): `AUTH_MODE=live` (default — fail-closed),
`FIREBASE_PROJECT_ID=$PROJECT_ID`, `ADMIN_EMAILS=<comma-separated verified @zennify.com emails>`.

**Validate:**

```bash
curl -s "https://identitytoolkit.googleapis.com/v1/projects/${PROJECT_ID}/config" \
  -H "Authorization: Bearer $(gcloud auth print-access-token)" | head -c 200
# 200 + JSON config => Identity Platform enabled. Token-level validation happens in §8.2.
```

### 3.8 Cloud Run service — first-time create (every flag, explained)

```bash
gcloud run deploy cia \
  --region "$REGION" \
  --image "us-docker.pkg.dev/cloudrun/container/hello" \  # placeholder; §5 deploys the real digest
  --service-account "$RUN_SA" \
  --vpc-connector cia-svpc --vpc-egress private-ranges-only \   # private path to Cloud SQL
  --set-secrets "DATABASE_URL=cia-database-url:latest,HMAC_KEY=cia-hmac-key:latest" \
  --set-env-vars "LLM_MODE=live,AUTH_MODE=live,FIREBASE_PROJECT_ID=${PROJECT_ID},ADMIN_EMAILS=dma@zennify.com" \
  --min-instances 2 --max-instances 8 \      # min 2 = no cold starts; max = SQL connection budget
  --cpu 1 --memory 1Gi --concurrency 40 --timeout 300 \
  --cpu-boost \                              # faster cold start when scaling
  --allow-unauthenticated                    # ingress is public; AUTH is app-level Firebase, fails closed
gcloud run services update cia --region "$REGION" \
  --update-labels app=cia                    # startup probe: Cloud Run probes the container port;
                                             # the app serves /healthz for the smoke + monitoring
```

Why `--allow-unauthenticated`: this is an internal tool whose authentication is **in the app**
(Firebase ID tokens, domain-restricted, fails closed — proven by test). Locking ingress to IAM
would break browser access for users without proxy infrastructure. `/healthz` is intentionally
public for probes; it exposes no data beyond versions/status.

**Validate:**

```bash
gcloud run services describe cia --region "$REGION" \
  --format='value(status.url, spec.template.spec.serviceAccountName)'
URL="$(gcloud run services describe cia --region "$REGION" --format='value(status.url)')"
curl -s "$URL/healthz"        # placeholder image: may 404 — the real check follows the §5 deploy
```

### 3.9 Migration Job — `cia-migrate` (runs to completion BEFORE traffic, never on startup)

```bash
gcloud run jobs create cia-migrate \
  --region "$REGION" \
  --image "us-docker.pkg.dev/cloudrun/container/hello" \   # placeholder; §5 points it at the real digest
  --service-account "$JOBS_SA" \
  --vpc-connector cia-svpc --vpc-egress private-ranges-only \
  --set-secrets "DATABASE_URL=cia-database-url:latest" \
  --command sh --args -c,"uv run python -m app.migrate" \
  --max-retries 1 --task-timeout 600 || true
```

**Validate:** `gcloud run jobs describe cia-migrate --region "$REGION" --format='value(name)'`.
Full behavioral validation happens on the first §5 deploy (logs show the alembic chain, then
`already at head; nothing to do` on re-run).

### 3.10 Schedulers (Stage-4 — prepared, not yet wired)

Cadences are **declared in `config/schedules.yaml`** and surfaced per-source in Settings (the
registry shows cron + next run). The Cloud Scheduler → Cloud Run Job wiring for live scans lands
with Stage 4 (live Vertex ingest); until then scans are triggered from the Settings UI / admin
API by an admin, and the **persisted source registry enables/disables each source** regardless
of trigger path. The prepared pattern (do not run before Stage 4):

```bash
# pattern per schedules.yaml entry (example: news_scan, Monday 06:00 UTC)
gcloud scheduler jobs create http cia-news-scan --location "$REGION" \
  --schedule "0 6 * * 1" --time-zone Etc/UTC \
  --uri "https://run.googleapis.com/v2/projects/${PROJECT_ID}/locations/${REGION}/jobs/cia-scan-news:run" \
  --oauth-service-account-email "$SCHED_SA"
```

---

## 4. Configuration matrix (single source of truth)

| Variable | Where it lives | Dev value | Prod value | Set by | Rotation |
|---|---|---|---|---|---|
| `DATABASE_URL` | Secret Manager `cia-database-url` | `postgresql+asyncpg://cia:cia@localhost:5432/cia` | asyncpg DSN → private IP | §3.6 | new secret version + redeploy |
| `HMAC_KEY` | Secret Manager `cia-hmac-key` | unset (exports unsigned in dev) | random 32B | §3.6 | new version + redeploy |
| `LLM_MODE` | service env | `hermetic` | `live` | §3.8 | — |
| `AUTH_MODE` | service env | `dev` (explicit, local only) | `live` (default) | §3.8 | — **never `dev` on anything reachable**; decoupled from LLM_MODE so the cost switch can never disable auth |
| `FIREBASE_PROJECT_ID` | service env | unset | project id | §3.8 | — |
| `ADMIN_EMAILS` | service env | unset (dev identity is admin) | comma-separated verified emails | §3.8 | redeploy |
| `PORT` | injected by Cloud Run | 8092 (manual) | injected | platform | — |
| `STATIC_DIR` | service env | `<repo>/frontend/dist` | unset → baked `/app/static` (cwd-independent) | — | — |
| Model pins | `config/models.yaml` (in image) | hermetic stubs | pinned versions, never `-latest` | commit | PR + deploy |
| Cadences | `config/schedules.yaml` (in image) | same | same | commit | PR + deploy |
| Gate thresholds | `config/gates.yaml` (in image) | same | same | commit (recalibration writes config, not code) | PR + deploy |
| Source on/off | `control.ingest_source` (DB) | Settings UI / `PATCH /api/admin/sources/{key}` | same | admin, audited | persisted; enforced before every fetch |
| User prefs | `control.users.preferences` (DB) | per user | per user | the app | persisted across sessions/devices |

---

## 5. Routine deploy — one run, self-healing

From the repo root pulled in §1 (HUMAN-GATED — paid actions):

```bash
PROJECT_ID=$PROJECT_ID REGION=$REGION ./scripts/deploy_cloudrun.sh
# staged rollout: CANARY_PERCENT=10 PROJECT_ID=... ./scripts/deploy_cloudrun.sh
```

The script (every step retried 2/4/8/16s, idempotent, converges on re-run):

1. **Preflight, fail-fast** — gcloud/docker present, **clean git tree**, right project, active
   account, APIs enabled, `cia-migrate` exists, docker auth. A failed preflight changes nothing.
2. **Build** `linux/amd64` from the committed tree; Docker Hub 429 → automatic fallback to the
   GCR mirror of the same pinned bases. pnpm pinned via `packageManager`; corporate-proxy CAs go
   in `build-ca/` (gitignored).
3. **Push** to Artifact Registry; resolve the **immutable digest** — tags are never deployed.
4. **Migrate to completion** — updates `cia-migrate` to the digest and executes it with `--wait`.
   Advisory lock on a direct connection + `lock_timeout 30s` + at-head no-op: re-runs and races
   are safe; a failed migration rolls back transactionally and **no traffic has moved**.
5. **Deploy `--no-traffic`** — the new revision exists, serves nothing.
6. **Smoke the new revision** via a tag-routed URL: `/healthz` must return `status:ok` **and**
   `db:ok`. Failure leaves 100% of traffic on the previous revision; exit nonzero.
7. **Promote** (optional canary % first), re-verify `/healthz`; any failure **auto-rolls traffic
   back** to the previous revision.

---

## 6. First-time data provisioning (per environment, idempotent)

A fresh environment is honest about emptiness (`catalogue_version: null`, designed empty states).
Provision once (admin Firebase token — mint one per §8.2):

```bash
URL="$(gcloud run services describe cia --region "$REGION" --format='value(status.url)')"
AUTH="Authorization: Bearer $TOKEN"
curl -sX POST -H "$AUTH" "$URL/api/admin/provision/v7"          # ~851 subcaps + enrichment
curl -sX POST -H "$AUTH" "$URL/api/admin/carry-forward/v7"      # 14,406 stories; ~13.6k confirmed
curl -sX POST -H "$AUTH" "$URL/api/admin/evidence/scan/news/v7"
curl -sX POST -H "$AUTH" "$URL/api/admin/trends/scan/v7"
curl -sX POST -H "$AUTH" "$URL/api/admin/evidence/scan/benchmarks/v7"
curl -sX POST -H "$AUTH" "$URL/api/admin/evidence/scan/vendor/v7"
```

**Validate:** each call returns its stats JSON (`provisioned/carried/fetched/mapped/flagged…`);
re-running any of them is a no-op (`deduped=N, created=0`). Data persists in Cloud SQL across
deploys, revisions, sessions and users — deploys never touch data.

---

## 7. Post-deploy validation — tiered, scripted, exact

### 7.1 T0 — probes (seconds)

```bash
curl -s "$URL/healthz"   # {"status":"ok","app_version":"<semver>","catalogue_version":"v7","llm_mode":"live","db":"ok"}
curl -s "$URL/livez"     # {"status":"alive"}
curl -s -o /dev/null -w '%{http_code}\n' "$URL/api/me"   # 401 — auth FAILS CLOSED without a token
curl -s "$URL/" | grep -o 'assets/index-[^"]*\.js'        # SPA served from the image
```

### 7.2 T1 — the QA walk (the committed harness; ~30s)

Mint a test ID token (test user created in the Identity Platform console; the web API key is the
SPA's public key):

```bash
TOKEN="$(curl -s "https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key=${WEB_API_KEY}" \
  -H 'Content-Type: application/json' \
  -d '{"email":"qa-bot@zennify.com","password":"<test user pwd>","returnSecureToken":true}' \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["idToken"])')"

BASE="$URL" TOKEN="$TOKEN" python3 scripts/qa_walk.py     # expect: ALL CHECKS PASSED
```

The walk asserts, endpoint by endpoint: probes; identity + **preference persistence**; catalogue
reads (4 pillars, tree, detail, stories, platforms, use cases, lifecycle); the **trust envelope
on every AI value** across News/Trends/Benchmarks/Vendor; **reasoning backlinks resolving from
every surface**; grounded chat + **G5 refusal**; governance (suggestions, change-flag queue,
gates log, QA metrics, audit log, **source registry with active origins**); and the edge cases
(unprovisioned version → 404 envelope, unwired kind → 400, malformed UUID → 422 never 500).
Hermetic environments add `STRICT=1` for exact fixture counts.

### 7.3 T2 — browser fidelity (minutes)

Open the service URL and sign in (domain-restricted). Walk the sidebar top to bottom — all 27
routes must render either live data or their **designed** empty/placeholder state, with zero
console errors and zero failed requests (DevTools → Console + Network). Spot-check the trust
envelope: any AI value → chips (Mag/Tier/Claim/ERS) + **Reasoning** opens the chain modal with
steps + gate checks. Toggle dark mode; switch a preference; **hard-reload** — the preference
survives (server-persisted, not localStorage).

### 7.4 T3 — governance invariants (the product's #1 guarantee)

```bash
curl -s -H "$AUTH" "$URL/api/gates" | python3 -m json.tool | head   # per-gate distribution, no empty log
curl -s -H "$AUTH" "$URL/api/qa/metrics"                            # gate_pass_rate, chains, spend (admin)
curl -s -H "$AUTH" "$URL/api/change-flags?status=open"              # gate failures QUEUED, never dropped
curl -s -H "$AUTH" "$URL/api/audit-log" | head -c 400               # append-only actions present
```

Then one full gated mutation: AI suggestions → Apply on a pending suggestion → confirm the
server **re-gated** (the apply response carries gate results), the catalogue changed, and a new
`audit_log` row exists. Reject must require a reason.

### 7.5 T4 — operational checks

```bash
gcloud run services logs read cia --region "$REGION" --limit 50    # no ERROR-level entries
gcloud run jobs executions list --job cia-migrate --region "$REGION" --limit 3   # SUCCEEDED
gcloud sql backups list --instance cia-pg --limit 3                # backups materializing
gcloud monitoring uptime list-configs 2>/dev/null | head           # if uptime checks configured
```

---

## 8. Operations

**Rollback (traffic):** the script auto-rolls-back on failed smoke/promote. Manual:
`gcloud run services update-traffic cia --region $REGION --to-revisions <prev>=100`.
**Schema stance:** expand/contract; revisions roll back **without** rolling back schema (every
migration is additive + CI-tested for downgrade, but downgrade is a break-glass tool, not a
rollback step).
**Scale knobs:** `--max-instances` is the SQL-connection budget (pool per instance × instances <
Cloud SQL max_connections); raise both together.
**Logs:** `gcloud run services logs read cia --region $REGION` (or Logs Explorer,
`resource.type=cloud_run_revision`). The app logs the resolved SPA dir + file count at startup —
a stale/wrong build is visible, never silent.
**Cost:** QA dashboard (admin) surfaces spend vs the envelope; G8 + the cost meter
alert at 80% / throttle at 90%.
**Backups/PITR drill:** restore the latest backup to a scratch instance quarterly; point a
scratch service at it; run `BASE=<scratch> python3 scripts/qa_walk.py`.

---

## 9. Troubleshooting

| Symptom | Likely cause | Fix | Re-validate |
|---|---|---|---|
| `healthz` → `db: down` | wrong `DATABASE_URL` secret / VPC connector missing | check secret version; `vpc-access connectors describe cia-svpc` | §7.1 |
| `/api/me` → 200 without token | `AUTH_MODE=dev` leaked into the service env | remove it (`gcloud run services update cia --remove-env-vars AUTH_MODE`) | §7.1 (expect 401) |
| 403 `account not permitted` on login | non-domain or unverified email | use `@zennify.com` verified account | §7.2 |
| build fails with Docker Hub 429 | unauthenticated pull rate limit | the script auto-falls-back to `mirror.gcr.io`; or pre-pull bases | §5 |
| build fails `SELF_SIGNED_CERT_IN_CHAIN` | TLS-intercepting proxy | drop the proxy CA at `build-ca/extra-ca.crt` | §5 |
| migrate job times out on lock | another migration holds the advisory lock | wait/kill the stale execution; re-run (idempotent) | §3.9 |
| scan returns 409 | source disabled in the registry | Settings → enable (audited) or `PATCH /api/admin/sources/{key}` | §6 |
| catalogue empty after deploy | fresh environment | §6 provisioning (idempotent) | §7.2 |
| SPA stale after deploy | browser cache | hard reload; bundles are content-hashed | §7.3 |

---

## Appendix A — local verification (no cloud, no spend)

```bash
scripts/dev_up.sh                      # docker + pgvector Postgres + both DBs migrated + SPA
cd backend && DATABASE_URL=postgresql+asyncpg://cia:cia@localhost:5432/cia \
  LLM_MODE=hermetic AUTH_MODE=dev STATIC_DIR=$PWD/../frontend/dist \
  uv run uvicorn app.main:app --port 8092
BASE=http://localhost:8092 STRICT=1 python3 scripts/qa_walk.py   # ALL CHECKS PASSED
# suites: backend ruff/black/mypy/pytest · frontend eslint/tsc/vitest/build
```

## Appendix B — container parity (exactly what Cloud Run runs)

```bash
docker buildx build --platform linux/amd64 -t cia:dev .
# rate-limited/proxied networks:
#   --build-arg NODE_IMAGE=mirror.gcr.io/library/node:20-bookworm-slim \
#   --build-arg PYTHON_IMAGE=mirror.gcr.io/library/python:3.12-slim-bookworm
docker run --rm --network host -e DATABASE_URL=<dsn> cia:dev uv run python -m app.migrate
docker run -d --rm --name cia-local --network host -e PORT=8093 -e DATABASE_URL=<dsn> cia:dev
curl -s http://localhost:8093/healthz                 # status ok / db ok
curl -s -o /dev/null -w '%{http_code}' http://localhost:8093/api/me   # 401 — fails closed
docker stop -t 10 cia-local                           # graceful SIGTERM drain
```

This exact sequence is exercised in QA on every increment — fresh DB → containerized migrate
(idempotent re-run) → boot on `$PORT` → probes → fail-closed auth → drain.
