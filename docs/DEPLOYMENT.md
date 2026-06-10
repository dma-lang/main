# Deployment guide — Capability Intelligence Agent

Deploy from **Cloud Shell** with the commands in **Path A** (recommended — copy-paste blocks, each
followed by a check). Prefer clicking? **Path B** does the same setup in the Google Cloud Console.
Both end in the same place:

| Piece | What it is |
|---|---|
| `cia` Cloud Run service | the app (FastAPI + React UI) in one container, built from this repo |
| `cia-migrate` Cloud Run job | runs database migrations once, before traffic |
| `cia-pg` Cloud SQL | Postgres 16 (+ pgvector) — all data lives here |
| 2 secrets | DB connection string + export-signing key |
| Firebase sign-in | Google login, restricted to `@zennify.com`, fails closed |

Command blocks are **paste-safe**: no comments inside multi-line commands (that's what broke
earlier — bash treats text after a `\` line-break comment as new commands). Notes sit above each
block. Every step is idempotent; "already exists" on a re-run is fine.

---

# Path A — Cloud Shell (commands)

## A1. Get the repo

The repo is public — no GitHub auth. Cloud Shell usually has it already (Open in Cloud Shell);
otherwise clone it.

```bash
cd ~/cia 2>/dev/null || git clone https://github.com/dma-lang/main.git ~/cia
cd ~/cia
git pull --ff-only
```

Check: `git log --oneline -1` shows the commit you're deploying.

## A2. Project + region (each new Cloud Shell session)

```bash
export PROJECT_ID=digital-maturity-assessor
export REGION=us-central1
gcloud config set project "$PROJECT_ID"
gcloud config set run/region "$REGION"
```

Check: `gcloud config get-value project` prints the project.

## A3. Enable the services

```bash
gcloud services enable run.googleapis.com sqladmin.googleapis.com \
  secretmanager.googleapis.com aiplatform.googleapis.com \
  artifactregistry.googleapis.com cloudbuild.googleapis.com \
  identitytoolkit.googleapis.com
```

Check: command exits without error (it's a no-op when already enabled).

## A4. Create the database

`--edition=enterprise` is required — the custom tier is invalid on Enterprise Plus (that was the
`Invalid Tier … for (ENTERPRISE_PLUS)` error). No VPC setup is needed: the app reaches the DB via
the built-in Cloud SQL connector, and with no authorized networks the DB is still unreachable from
the internet. The create takes a few minutes — let it finish before the next commands.

```bash
gcloud sql instances create cia-pg \
  --edition=enterprise \
  --database-version=POSTGRES_16 \
  --tier=db-custom-2-7680 \
  --region="$REGION" \
  --backup \
  --backup-start-time=03:00 \
  --enable-point-in-time-recovery
```

```bash
gcloud sql databases create cia --instance=cia-pg
APP_DB_PASSWORD="$(openssl rand -base64 24)"
gcloud sql users create cia --instance=cia-pg --password="$APP_DB_PASSWORD"
SQL_CONN="$(gcloud sql instances describe cia-pg --format='value(connectionName)')"
echo "$SQL_CONN"
```

Check: instance is RUNNABLE and the connection name printed
(`digital-maturity-assessor:us-central1:cia-pg`):

```bash
gcloud sql instances describe cia-pg --format='value(state, settings.edition)'
```

## A5. Store the two secrets

The DSN uses the Cloud SQL unix socket (`?host=/cloudsql/…`) — no IPs, no networking.

```bash
printf 'postgresql+asyncpg://cia:%s@/cia?host=/cloudsql/%s' "$APP_DB_PASSWORD" "$SQL_CONN" \
  | gcloud secrets create cia-database-url --data-file=-
openssl rand -base64 32 | gcloud secrets create cia-hmac-key --data-file=-
unset APP_DB_PASSWORD
```

Check:

```bash
gcloud secrets versions list cia-database-url --format='value(name,state)'
```

## A6. Turn on sign-in (Firebase — browser, one time)

One console toggle (no CLI exists for it): open the
[Firebase Console](https://console.firebase.google.com) → project **digital-maturity-assessor**
(add Firebase to the existing GCP project if prompted) → **Build → Authentication → Get started**
→ **Sign-in method → Google → Enable → Save**.

Nothing to copy: the app ships with this project's **public Firebase web config hardcoded**
(apiKey, authDomain, appId, …) and serves it to the browser via `/api/config`. If you rotate the
web key later, either commit the new value in `backend/app/settings.py` or override it without a
code change by adding `FIREBASE_WEB_API_KEY` as an env var on the service.

## A7. Deploy the app from source

Cloud Build builds the repo's Dockerfile for you — no local Docker. First deploy takes ~5 minutes
and may ask to create an Artifact Registry repo (answer Y).

```bash
gcloud run deploy cia \
  --source . \
  --region "$REGION" \
  --allow-unauthenticated \
  --add-cloudsql-instances "$SQL_CONN" \
  --set-secrets "DATABASE_URL=cia-database-url:latest,HMAC_KEY=cia-hmac-key:latest" \
  --set-env-vars "LLM_MODE=live" \
  --min-instances 1 \
  --max-instances 8 \
  --cpu 1 \
  --memory 1Gi \
  --concurrency 40 \
  --timeout 300
```

Notes: `--allow-unauthenticated` only opens the door to the login page — sign-in is enforced inside
the app and fails closed (`AUTH_MODE` defaults to `live`). The Firebase web config and the two
admin emails (`tom.hedgecoth@zennify.com`, `mishley.otiende@zennify.com`) are **hardcoded
defaults** — no env vars needed. To override later, add env vars on the service, e.g.
`ADMIN_EMAILS=a@zennify.com;b@zennify.com` (`;` or `,` both work) or `FIREBASE_WEB_API_KEY=…`.

```bash
URL="$(gcloud run services describe cia --region "$REGION" --format='value(status.url)')"
echo "$URL"
```

Check: `curl -s "$URL/healthz"` returns `"status":"ok"` (db may read `down` until A9 runs the
migration — that's expected on a fresh database).

Finally, allow Google sign-in on that URL: Firebase Console → **Authentication → Settings →
Authorized domains → Add domain** → the `cia-….run.app` host.

## A8. Give the app its permissions

The service runs as the project's default compute service account; it needs three roles.

```bash
RUNTIME_SA="$(gcloud run services describe cia --region "$REGION" --format='value(spec.template.spec.serviceAccountName)')"
test -n "$RUNTIME_SA" || RUNTIME_SA="$(gcloud iam service-accounts list --filter='displayName:Compute Engine default' --format='value(email)')"
echo "$RUNTIME_SA"
```

```bash
gcloud projects add-iam-policy-binding "$PROJECT_ID" --member "serviceAccount:$RUNTIME_SA" --role roles/cloudsql.client --condition=None
gcloud projects add-iam-policy-binding "$PROJECT_ID" --member "serviceAccount:$RUNTIME_SA" --role roles/secretmanager.secretAccessor --condition=None
gcloud projects add-iam-policy-binding "$PROJECT_ID" --member "serviceAccount:$RUNTIME_SA" --role roles/aiplatform.user --condition=None
```

Check: re-run `curl -s "$URL/healthz"` — no permission errors in
`gcloud run services logs read cia --region "$REGION" --limit 20`.

## A9. Run the database migration (one-shot job)

The job reuses the exact image A7 built and runs `python -m app.migrate` to completion (advisory
lock; re-runs are no-ops).

```bash
IMAGE="$(gcloud run services describe cia --region "$REGION" --format='value(spec.template.spec.containers[0].image)')"
gcloud run jobs create cia-migrate \
  --image "$IMAGE" \
  --region "$REGION" \
  --add-cloudsql-instances "$SQL_CONN" \
  --set-secrets "DATABASE_URL=cia-database-url:latest" \
  --command uv \
  --args run,python,-m,app.migrate \
  --max-retries 1 \
  --task-timeout 600
gcloud run jobs execute cia-migrate --region "$REGION" --wait
```

Check: the execution ends **Succeeded**; `curl -s "$URL/healthz"` now shows `"db":"ok"`.

## A10. Load the catalogue (in the app — no commands)

Open `$URL`, sign in as `tom.hedgecoth@zennify.com` or `mishley.otiende@zennify.com`, go to
**Settings → Catalogue setup**, click **1 · Provision** then **2 · Carry stories** (idempotent,
shows counts). Optionally hit **Scan now** on News/Trends/Benchmarks/Vendor, or let the schedulers
fill them.

Check: the header shows `v7`; Mission control shows the four pillars with real counts.

## A11. Updating later

```bash
cd ~/cia
git pull --ff-only
gcloud run deploy cia --source . --region "$REGION"
```

If the update added database tables, point the job at the new image and run it once:

```bash
IMAGE="$(gcloud run services describe cia --region "$REGION" --format='value(spec.template.spec.containers[0].image)')"
gcloud run jobs update cia-migrate --image "$IMAGE" --region "$REGION"
gcloud run jobs execute cia-migrate --region "$REGION" --wait
```

Roll back: `gcloud run services update-traffic cia --region "$REGION" --to-revisions REVISION=100`
(list revisions with `gcloud run revisions list --service cia --region "$REGION"`).

---

# Path B — Google Cloud Console (point-and-click)

Same result as Path A, no terminal. Keep the Cloud Console on project `digital-maturity-assessor`.

1. **APIs** — enable on first use when prompted, or APIs & Services → Enable: Cloud Run, Cloud SQL
   Admin, Secret Manager, Vertex AI, Artifact Registry, Cloud Build, Identity Toolkit.
2. **SQL → Create instance → PostgreSQL** — **edition: Enterprise** (not Enterprise Plus),
   ID `cia-pg`, PostgreSQL 16, region `us-central1`, small machine, **backups + point-in-time
   recovery ON**, no authorized networks. Then on the instance: **Databases → Create** `cia`;
   **Users → Add** `cia` with a password (copy it); copy the **Connection name** from Overview.
3. **Security → Secret Manager → Create secret** twice: `cia-database-url` with the one-line value
   `postgresql+asyncpg://cia:THE_PASSWORD@/cia?host=/cloudsql/CONNECTION_NAME`, and `cia-hmac-key`
   with a long random string.
4. **Firebase Console → Authentication** — Get started → Sign-in method → **Google → Enable**.
   (No key to copy — the app's public web config is hardcoded and served via `/api/config`.)
5. **Cloud Run → Create service → "Continuously deploy from a repository"** → Set up with Cloud
   Build → GitHub → **`dma-lang/main`** (public) → branch `^main$` → **Dockerfile**. Service `cia`,
   region `us-central1`, **Allow unauthenticated**. Under *Containers, Volumes, Networking,
   Security*: CPU 1 / 1 GiB, concurrency 40, timeout 300, min 1 / max 8 instances; **Variables**:
   just `LLM_MODE=live` (auth mode, the Firebase web config and the two admin emails are
   hardcoded defaults); **Reference secrets**: `DATABASE_URL` → `cia-database-url:latest`, `HMAC_KEY` →
   `cia-hmac-key:latest`; **Cloud SQL connections → Add** `cia-pg`. **Create**, copy the URL, and
   add its host under Firebase → Authentication → Settings → **Authorized domains**. (Bonus of this
   path: every push to `main` redeploys automatically.)
6. **IAM** — IAM & Admin → IAM → edit the service's runtime service account (shown on the service's
   Security tab) → add **Cloud SQL Client**, **Secret Manager Secret Accessor**, **Vertex AI User**.
   Then Cloud Run → `cia` → Edit & deploy new revision → Deploy (no changes) to pick them up.
7. **Cloud Run → Jobs → Create job** — image = the `cia` service's current image (copy from its
   Revisions tab), name `cia-migrate`, command `uv`, arguments `run`,`python`,`-m`,`app.migrate`,
   secret `DATABASE_URL` → `cia-database-url:latest`, Cloud SQL connection `cia-pg`, same service
   account. **Create → Execute**; wait for **Succeeded**.
8. **Load the catalogue in the app** — open the URL, sign in as one of the named admins,
   **Settings → Catalogue setup**: **1 · Provision**, then **2 · Carry stories**.

---

# If something goes wrong

| What you see | Why | Fix |
|---|---|---|
| `Invalid Tier … for (ENTERPRISE_PLUS)` creating the DB | instance defaulted to Enterprise Plus | recreate with `--edition=enterprise` (A4) / choose Enterprise (B2) |
| `databases/users create` → 403/404 on `cia-pg` | the instance create above failed or hasn't finished | wait for RUNNABLE, then re-run those (idempotent) |
| `-bash: --some-flag: command not found` while pasting | a comment after a `\` line-continuation split the command | use the blocks in this guide verbatim — they contain no inline comments |
| `healthz` shows `"db":"down"` | migration not run yet, wrong secret, or missing Cloud SQL connection/IAM | run A9; re-check A5 value, A7 `--add-cloudsql-instances`, A8 roles |
| sign-in popup: domain not authorized | Cloud Run URL not added in Firebase | Authentication → Settings → Authorized domains (end of A7 / B5) |
| `403 account not permitted` after Google login | not a verified `@zennify.com` account | use a verified `@zennify.com` Google account |
| Mission control empty | catalogue not loaded | Settings → Catalogue setup (A10 / B8) |
| a Scan button returns "source disabled" | source switched off in the registry | Settings → Ingestion source registry → toggle on |
| `/api/me` returns 200 without a token | `AUTH_MODE=dev` set on the service | remove the env var and redeploy — production must be `live` |

---

# Appendix — automation & local parity (optional)

- **`scripts/deploy_cloudrun.sh`** — the scripted A7–A9 + canary/rollback for CI: builds
  linux/amd64 (GCR-mirror fallback on Docker Hub rate limits), pushes by digest, runs the migrate
  job **before** traffic, deploys `--no-traffic`, smoke-tests `/healthz`, promotes, and rolls
  traffic back automatically on failure. `PROJECT_ID=… REGION=… ./scripts/deploy_cloudrun.sh`
- **`scripts/qa_walk.py`** — post-deploy validation: walks every surface, asserts contracts, trust
  envelopes, reasoning backlinks, edge cases. `BASE=$URL TOKEN=<firebase-id-token> python3
  scripts/qa_walk.py` (`STRICT=1` on hermetic builds for exact fixture counts).
- **`scripts/dev_up.sh`** — full local stack (Docker + pgvector Postgres + migrations + SPA),
  hermetic and free: run the app with `LLM_MODE=hermetic AUTH_MODE=dev` on localhost.

Terraform will codify this setup in a later stage; until then this guide is the source of truth.
