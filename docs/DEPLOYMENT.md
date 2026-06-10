# Deployment guide — Capability Intelligence Agent

Written for a **first-time deployer**: every step says where to click or what to paste, what you
should see, and how to check it worked before moving on. You deploy from **Cloud Shell** (Path A —
recommended). Path B does the same setup by clicking in the Google Cloud Console.

**What you end up with** (project `digital-maturity-assessor`, region `us-central1`):

| Piece | What it is |
|---|---|
| `cia` Cloud Run service | the app — backend + UI in one container, built from this repo |
| `cia-migrate` Cloud Run job | creates/updates the database tables (run once) |
| `cia-pg` Cloud SQL instance | Postgres 16 — all the data lives here, survives everything |
| 2 secrets | the database connection string + an export-signing key |
| Firebase sign-in | "Sign in with Google", restricted to `@zennify.com` |

Three things to know before you start:

1. **Command blocks are paste-safe.** Copy a whole grey block and paste it into Cloud Shell as
   one. There are never comments inside a multi-line command (comments after a `\` break bash —
   that caused the earlier `-bash: --flag: command not found` errors).
2. **Everything is re-runnable.** If a command says something *already exists*, that's fine —
   move on.
3. **Almost no configuration to type.** The app ships with the Firebase web config and the two
   administrators (`tom.hedgecoth@zennify.com`, `mishley.otiende@zennify.com`) built in.

---

# Path A — Cloud Shell, step by step

Open [https://shell.cloud.google.com](https://shell.cloud.google.com). A terminal opens at the
bottom of the browser. Make sure the yellow project name in the prompt says
`(digital-maturity-assessor)` — if not, run
`gcloud config set project digital-maturity-assessor` first.

## A1. Get the repo

The repo is **public** — there is no GitHub login, token, or permission step. This block clones it
if it's missing and updates it if it's already there:

```bash
[ -d ~/cia/.git ] || git clone https://github.com/dma-lang/main.git ~/cia
cd ~/cia
git pull --ff-only
```

**Check — you must see the app's files before continuing:**

```bash
ls Dockerfile backend frontend config scripts
```

If `ls` prints those five names, you're in the right place. If it errors, your `~/cia` folder is
broken (e.g. an old empty folder) — move it aside and re-run A1:

```bash
mv ~/cia ~/cia.bak
```

> Deploying from a folder without these files is what causes the
> `zipfile is empty … source fetch container exited with non-zero status` build error: gcloud
> uploads whatever folder you're standing in, and an empty folder makes an empty (22-byte) zip.

## A2. Point the session at the project (every new Cloud Shell session)

```bash
export PROJECT_ID=digital-maturity-assessor
export REGION=us-central1
gcloud config set project "$PROJECT_ID"
gcloud config set run/region "$REGION"
```

**Check:** `gcloud config get-value project` prints `digital-maturity-assessor`.

## A3. Turn on the Google services

```bash
gcloud services enable run.googleapis.com sqladmin.googleapis.com \
  secretmanager.googleapis.com aiplatform.googleapis.com \
  artifactregistry.googleapis.com cloudbuild.googleapis.com \
  identitytoolkit.googleapis.com
```

**Check:** the command finishes without an error (takes ~1 minute the first time; instant after).

## A4. Create the database

Notes first: `--edition=enterprise` is required — without it the project may default to
*Enterprise Plus*, which rejects this machine size (that was the
`Invalid Tier … for (ENTERPRISE_PLUS)` error). The create takes **5–10 minutes**; wait for it to
finish before pasting the next block.

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

When it returns, create the app's database and user (the password is generated for you and used
once in A5 — you never need to remember it):

```bash
gcloud sql databases create cia --instance=cia-pg
APP_DB_PASSWORD="$(openssl rand -base64 24)"
gcloud sql users create cia --instance=cia-pg --password="$APP_DB_PASSWORD"
SQL_CONN="$(gcloud sql instances describe cia-pg --format='value(connectionName)')"
echo "$SQL_CONN"
```

**Check:** the last line printed `digital-maturity-assessor:us-central1:cia-pg`, and:

```bash
gcloud sql instances describe cia-pg --format='value(state, settings.edition)'
```

prints `RUNNABLE ENTERPRISE`.

## A5. Store the two secrets

The app reads its database address and signing key from Secret Manager — never from files.
(The connection string uses Cloud Run's built-in secure tunnel to Cloud SQL, so there is no
networking to configure and the database is not exposed to the internet.)

```bash
printf 'postgresql+asyncpg://cia:%s@/cia?host=/cloudsql/%s' "$APP_DB_PASSWORD" "$SQL_CONN" \
  | gcloud secrets create cia-database-url --data-file=-
openssl rand -base64 32 | gcloud secrets create cia-hmac-key --data-file=-
unset APP_DB_PASSWORD
```

**Check:**

```bash
gcloud secrets list --filter='name:cia-' --format='value(name)'
```

prints `cia-database-url` and `cia-hmac-key`.

## A6. Turn on "Sign in with Google" (Firebase — in the browser, once)

This is the only step done by clicking, because Google offers no command for it. Follow exactly:

1. Open a new browser tab at **[https://console.firebase.google.com](https://console.firebase.google.com)**
   (sign in with your `@zennify.com` Google account if asked).
2. **Find the project card named `digital-maturity-assessor`** and click it.
   - *Don't see it?* Firebase hasn't been attached to the Google Cloud project yet. Click
     **Create a project** (sometimes labelled **Add project**) → on the first screen, **type**
     `digital-maturity-assessor` — it appears in the dropdown as an *existing Google Cloud
     project* with a small cloud icon — select it → click **Continue** → accept the terms →
     if asked about **Google Analytics**, either choice is fine (Disable is simplest) →
     **Add Firebase** → wait → **Continue**. You land on the project's overview page.
3. In the **left sidebar**, find **Authentication**:
   - It's usually inside the collapsible **Build** group — click **Build** to expand it, then
     **Authentication**.
   - *No "Build" group visible?* The sidebar sometimes shows shortcuts only. Click
     **All products** at the bottom of the sidebar (or the grid icon), then click
     **Authentication** in the product list.
4. On the Authentication page, click the blue **Get started** button (only shown the first time).
5. You're now on the **Sign-in method** tab. Under *Sign-in providers*, click **Google**
   (if you instead see an **Add new provider** button, click it, then pick **Google**).
6. Flip the **Enable** toggle on. In **Support email for project**, pick your email from the
   dropdown. Click **Save**.

**Check:** the Sign-in method list now shows **Google — Enabled**.

(Nothing to copy anywhere: the app already contains this project's public Firebase web settings
and serves them to the browser itself. One more Firebase visit happens at the end of A7.)

## A7. Build & deploy the app — one command

First, prove you're in the right folder and the upload will contain the app (this prevents the
empty-zip build failure):

```bash
cd ~/cia
ls Dockerfile backend frontend config
gcloud meta list-files-for-upload . | wc -l
```

The `ls` must print the four names and the count should be roughly **80–120** (the number of
files sent to the builder; bulky build artifacts and spec documents are excluded by
`.gcloudignore`). If the count is near zero or `ls` fails — go back to A1.

Now deploy. Google's builder runs this repo's `Dockerfile` for you (you don't install anything):

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

What to expect while it runs:

- If it asks **“Deploying from source requires an Artifact Registry Docker repository … Do you
  want to continue (Y/n)?”** — answer **Y**.
- It prints `Building using Dockerfile`, uploads the sources, and streams a Cloud Build log link.
  The **first build takes about 5–8 minutes** (it compiles the UI and installs the backend).
- It ends with `Service [cia] revision [cia-00001-xxx] has been deployed` and a **Service URL**.

Why these flags, in one line each: `--allow-unauthenticated` only lets browsers *reach the login
page* — sign-in itself is enforced inside the app and fails closed; the Firebase settings and the
two admins are already built in, so `LLM_MODE=live` is the only variable you set.

Save and check the URL:

```bash
URL="$(gcloud run services describe cia --region "$REGION" --format='value(status.url)')"
echo "$URL"
curl -s "$URL/healthz"
```

**Check:** the health line shows `"status":"ok"`. (`"db":"down"` is expected right now — the
tables don't exist until A9.)

Last bit of A7 — allow Google sign-in on the new address: back in the **Firebase Console →
Authentication → Settings tab → Authorized domains → Add domain** → paste the host part of your
URL (e.g. `cia-abc123-uc.a.run.app`, without `https://`) → **Add**.

## A8. Give the app its permissions

The service runs as the project's default service account; grant it the three roles it needs
(read secrets, reach Cloud SQL, call Vertex AI):

```bash
PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"
RUNTIME_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
gcloud projects add-iam-policy-binding "$PROJECT_ID" --member "serviceAccount:$RUNTIME_SA" --role roles/cloudsql.client --condition=None
gcloud projects add-iam-policy-binding "$PROJECT_ID" --member "serviceAccount:$RUNTIME_SA" --role roles/secretmanager.secretAccessor --condition=None
gcloud projects add-iam-policy-binding "$PROJECT_ID" --member "serviceAccount:$RUNTIME_SA" --role roles/aiplatform.user --condition=None
```

**Check:** each command prints the updated policy without an error.

## A9. Create the tables (run the migration job once)

This reuses the exact image A7 just built and runs the database migration to completion. Safe to
run again anytime — when there's nothing to do it says so and exits.

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

**Check:** the execution ends **Succeeded**, and now:

```bash
curl -s "$URL/healthz"
```

shows `"db":"ok"`.

## A10. Load the data (in the app — two clicks)

1. Open the Service URL in your browser. You see the sign-in screen.
2. Click **Sign in with Google** and use `tom.hedgecoth@zennify.com` or
   `mishley.otiende@zennify.com` (other verified `@zennify.com` accounts can sign in too — they
   just aren't admins until added).
3. Click the **gear icon** (top-right) to open **Settings**.
4. In the **Catalogue setup** card: click **1 · Provision** and wait for the toast
   (~851 sub-capabilities seeded), then click **2 · Carry stories** and wait
   (loads the 14,406-story delivery corpus). Both are safe to click again.
5. Optional now / automatic later: open **News watch**, **Trends**, **Benchmarks**,
   **Vendor intelligence** and press **Scan now** on each — or let the weekly/monthly schedules
   fill them.

**Check:** the top bar shows `v7`; **Mission control** shows four pillar tiles with real numbers;
**Settings → Administrators** lists the two admins (you can add more there — no redeploy).

## A11. Updating the app later

```bash
cd ~/cia
git pull --ff-only
gcloud run deploy cia --source . --region "$REGION"
```

If the update added database tables (release notes will say so), refresh the job image and run it
once:

```bash
IMAGE="$(gcloud run services describe cia --region "$REGION" --format='value(spec.template.spec.containers[0].image)')"
gcloud run jobs update cia-migrate --image "$IMAGE" --region "$REGION"
gcloud run jobs execute cia-migrate --region "$REGION" --wait
```

Roll back to a previous version: `gcloud run revisions list --service cia --region "$REGION"`,
pick a green one, then
`gcloud run services update-traffic cia --region "$REGION" --to-revisions THAT_REVISION=100`.

---

# Path B — the same setup, clicking in the Cloud Console

1. **APIs** — the Console offers an **Enable** button the first time you open each product; click
   it when prompted (or APIs & Services → *+ Enable APIs and services* → enable Cloud Run, Cloud
   SQL Admin, Secret Manager, Vertex AI, Artifact Registry, Cloud Build, Identity Toolkit).
2. **SQL → Create instance → PostgreSQL** — Edition **Enterprise** (not Enterprise Plus); ID
   `cia-pg`; PostgreSQL 16; region `us-central1`; a small machine is fine; under *Data protection*
   enable **Automated backups** and **Point-in-time recovery**; leave *Connections* as default
   (do **not** add authorized networks). Create (5–10 min). Then on the instance page:
   **Databases → Create database** `cia`; **Users → Add user account** `cia` + a password you
   copy; **Overview → copy the Connection name**.
3. **Security → Secret Manager → + Create secret** twice:
   `cia-database-url` = one line
   `postgresql+asyncpg://cia:THE_PASSWORD@/cia?host=/cloudsql/THE_CONNECTION_NAME`;
   `cia-hmac-key` = any long random string (40+ characters).
4. **Firebase sign-in** — follow **A6 above** word for word (it is browser-only in both paths).
5. **Cloud Run → Create service** → choose **“Continuously deploy from a repository”** → *Set up
   with Cloud Build* → provider **GitHub** → authorize → repository **`dma-lang/main`** → branch
   `^main$` → build type **Dockerfile** → Save. Service name `cia`, region `us-central1`,
   **Allow unauthenticated invocations**. Expand *Containers, Volumes, Networking, Security*:
   CPU `1`, Memory `1 GiB`, concurrency `40`, timeout `300`, min `1` / max `8` instances;
   **Variables**: add `LLM_MODE` = `live` (that's the only one);
   **Secrets exposed as environment variables**: `DATABASE_URL` → `cia-database-url:latest`,
   `HMAC_KEY` → `cia-hmac-key:latest`; **Cloud SQL connections → Add connection → `cia-pg`**.
   **Create** — the first build takes 5–8 minutes. Copy the URL and add its host under
   Firebase → Authentication → Settings → **Authorized domains**. (This path also redeploys
   automatically on every push to `main`.)
6. **IAM** — IAM & Admin → IAM → find `PROJECT_NUMBER-compute@developer.gserviceaccount.com` →
   pencil icon → add roles **Cloud SQL Client**, **Secret Manager Secret Accessor**,
   **Vertex AI User** → Save. Then Cloud Run → `cia` → *Edit & deploy new revision* → Deploy
   (no changes) so the revision picks the roles up.
7. **Cloud Run → Jobs → Create job** — image = the `cia` service's current image (copy the full
   image URL from the service's **Revisions** tab); name `cia-migrate`; region `us-central1`;
   *Container* → **command** `uv`, **arguments** `run`, `python`, `-m`, `app.migrate` (one per
   line); *Variables & secrets* → expose `DATABASE_URL` from `cia-database-url:latest`;
   *Connections* → add Cloud SQL `cia-pg`. **Create**, then **Execute** and wait for *Succeeded*.
8. **Load the data** — exactly **A10 above**.

---

# If something goes wrong

| What you see | Why | Fix |
|---|---|---|
| build fails: `zipfile is empty` / `source fetch container exited with non-zero status: 1` | the deploy ran from a folder that isn't the repo (gcloud uploaded an empty folder) | `cd ~/cia`, run the A1 + A7 checks (`ls Dockerfile …`, file count ≈150–200), then deploy again |
| `Invalid Tier … for (ENTERPRISE_PLUS)` creating the DB | instance defaulted to Enterprise Plus | use `--edition=enterprise` (A4) / pick Enterprise (B2) |
| `databases/users create` → 403/404 on `cia-pg` | the instance create failed or hasn't finished | wait for `RUNNABLE`, re-run those commands (safe) |
| `-bash: --some-flag: command not found` while pasting | a comment after a `\` split the command | paste the blocks from this guide verbatim — they contain no inline comments |
| `healthz` shows `"db":"down"` | migration not run yet, wrong secret value, or missing Cloud SQL connection / IAM role | run A9; re-check the A5 secret, the `--add-cloudsql-instances` flag, the A8 roles |
| sign-in popup: *domain not authorized* | the service URL isn't in Firebase's authorized domains | Firebase → Authentication → Settings → Authorized domains → add the `…run.app` host |
| `403 account not permitted` after Google sign-in | not a verified `@zennify.com` account | sign in with a verified `@zennify.com` Google account |
| Mission control is empty | data not loaded yet | A10: Settings → Catalogue setup → Provision, then Carry stories |
| a Scan button says "source disabled" | that source is switched off | Settings → Ingestion source registry → toggle it on |
| `/api/me` answers 200 without a token | `AUTH_MODE=dev` was set on the service | remove that env var and redeploy — production must not set it |

---

# Appendix — automation & local parity (optional)

- **`scripts/deploy_cloudrun.sh`** — scripted deploy for CI: digest-pinned image, migrate-before-
  traffic, `--no-traffic` smoke test, canary, automatic traffic rollback.
  `PROJECT_ID=… REGION=… ./scripts/deploy_cloudrun.sh`
- **`scripts/qa_walk.py`** — post-deploy validation of every surface (contracts, trust envelope,
  reasoning links, edge cases): `BASE=$URL TOKEN=<firebase-id-token> python3 scripts/qa_walk.py`
- **`scripts/dev_up.sh`** — full local stack (Docker + Postgres/pgvector + migrations + UI),
  hermetic and free: run with `LLM_MODE=hermetic AUTH_MODE=dev`.

Terraform will codify this setup in a later stage; until then this guide is the source of truth.
