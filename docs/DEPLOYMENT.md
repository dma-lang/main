# Deployment guide — point-and-click in the Google Cloud Console

Set the whole thing up from the **Google Cloud Console** and the **Firebase Console** — no local
Docker, no image building, almost no command line. **Cloud Run builds the app straight from this
public GitHub repo** (it runs the `Dockerfile` for you with Cloud Build), so a deploy is: connect
the repo once, fill in a few fields, click Create.

**What gets created** (all in project `digital-maturity-assessor`, region `us-central1`):

| Piece | What it is | Console area |
|---|---|---|
| `cia` service | the app (FastAPI + the React UI) in one container, built from the repo | Cloud Run |
| `cia-migrate` job | runs the database migrations once | Cloud Run → Jobs |
| `cia-pg` | Postgres 16 (+ pgvector) — all the data lives here | SQL |
| 2 secrets | the DB connection string + an export-signing key | Secret Manager |
| sign-in | Google login restricted to `@zennify.com` | Firebase → Authentication |

Do the steps in order. Most are one-time per environment. Each step ends with a **Check** — look
at the Console and confirm it before moving on. The two named administrators
(`tom.hedgecoth@zennify.com`, `mishley.otiende@zennify.com`) are wired in at step 5 and seeded in
the database, so they can sign in and manage everyone else from the app afterwards.

> Tip: keep the [Cloud Console](https://console.cloud.google.com) on the `digital-maturity-assessor`
> project (top project picker) and the [Firebase Console](https://console.firebase.google.com) open
> in another tab — it's the **same project** in both.

---

## 1. Turn on the services (APIs)

You don't have to enable APIs by hand — the Console pops up an **"Enable API"** button the first
time you open each service (SQL, Cloud Run, Secret Manager, Vertex AI). Click it whenever it
appears. To do them all at once instead:

- Console → **APIs & Services → Enabled APIs & services → + Enable APIs and services**, and enable:
  **Cloud Run**, **Cloud SQL Admin**, **Secret Manager**, **Vertex AI**, **Artifact Registry**,
  **Cloud Build**, **Identity Toolkit** (Firebase Auth).

**Check:** each shows up under *Enabled APIs & services*.

---

## 2. Create the database (Cloud SQL)

Console → **SQL → Create instance → PostgreSQL**.

- **Choose edition: Enterprise** (NOT *Enterprise Plus* — Enterprise lets you pick a small/custom
  machine; Plus rejects it. This was the cause of the `Invalid Tier … for (ENTERPRISE_PLUS)` error).
- **Instance ID:** `cia-pg`
- **Password:** set any password for the built-in `postgres` user (you won't use it — write it down
  anyway).
- **Database version:** PostgreSQL 16 · **Region:** `us-central1` · single zone is fine.
- **Machine / preset:** the smallest is fine to start (e.g. *Lightweight*, or 2 vCPU / 8 GB).
- **Data Protection:** turn ON **Automated backups** and **Point-in-time recovery**.
- **Connections:** leave **Public IP** checked but **do not add any Authorized networks** — the app
  connects through the secure built-in Cloud SQL connector (step 5), not over the network, so the
  database stays unreachable from the internet.
- **Create instance** (takes a few minutes).

Then on the instance page:

- **Databases** tab → **Create database** → name it `cia` → Create.
- **Users** tab → **Add user account** → username `cia`, set a **password** → Add. **Copy this
  password** — you need it in step 3.
- On the instance **Overview**, copy the **Connection name** (looks like
  `digital-maturity-assessor:us-central1:cia-pg`).

**Check:** the instance shows **Runnable**; a `cia` database and a `cia` user are listed.

---

## 3. Store the two secrets (Secret Manager)

Console → **Security → Secret Manager → + Create secret** (do this twice).

**Secret 1 — the database connection string**
- **Name:** `cia-database-url`
- **Secret value:** one line, replacing `THE_PASSWORD` with the `cia` user password from step 2 and
  keeping your exact connection name:

  ```
  postgresql+asyncpg://cia:THE_PASSWORD@/cia?host=/cloudsql/digital-maturity-assessor:us-central1:cia-pg
  ```
- **Create secret.**

**Secret 2 — the export-signing key**
- **Name:** `cia-hmac-key`
- **Secret value:** any long random string (40+ characters — mash the keyboard, or use a password
  generator). It signs the quarterly-digest exports.
- **Create secret.**

**Check:** both secrets appear with **1 version**.

---

## 4. Turn on sign-in (Firebase Authentication)

Open the [Firebase Console](https://console.firebase.google.com) → pick **digital-maturity-assessor**
(it's the same GCP project; if Firebase isn't added yet, click **Add project → choose the existing
GCP project**).

- **Build → Authentication → Get started.**
- **Sign-in method** tab → **Google** → toggle **Enable** → set a support email → **Save**.
- **Project settings** (the gear, top-left) → **General** → scroll to **Your apps** → if there's no
  Web app, click **Web (`</>`)**, nickname it `CIA`, register it. Copy the **`apiKey`** value — this
  is your **Firebase Web API Key** for step 5.
- (You'll add the app's web address as an *Authorized domain* at the end of step 5.)

**Check:** Google shows **Enabled** under Sign-in method, and you have the Web API Key copied.

---

## 5. Deploy the app (Cloud Run, built from the repo)

Console → **Cloud Run → Create service**.

1. Choose **“Continuously deploy from a repository (source or function)”** → **Set up with Cloud
   Build**.
   - **Repository provider: GitHub** → authorize → pick **`dma-lang/main`** (it's public).
   - **Branch:** `^main$` · **Build type: Dockerfile** (path `/Dockerfile`) → **Save**.
2. **Service name:** `cia` · **Region:** `us-central1`.
3. **Authentication:** select **Allow unauthenticated invocations**. (Sign-in is enforced *inside*
   the app with Firebase and fails closed — leaving ingress open just lets the browser reach the
   login page.)
4. Expand **Containers, Volumes, Networking, Security** and set:
   - **Settings → Resources:** CPU `1`, Memory `1 GiB`. **Requests:** Max concurrent `40`, Request
     timeout `300`. **Autoscaling:** Min instances `1`, Max instances `8`.
   - **Variables & Secrets → + Add variable** (one per row):
     | Name | Value |
     |---|---|
     | `LLM_MODE` | `live` |
     | `AUTH_MODE` | `live` |
     | `FIREBASE_PROJECT_ID` | `digital-maturity-assessor` |
     | `FIREBASE_WEB_API_KEY` | *(the Web API Key from step 4)* |
     | `ADMIN_EMAILS` | `tom.hedgecoth@zennify.com,mishley.otiende@zennify.com` |
   - **Variables & Secrets → + Reference a secret** (twice):
     | Env name | Secret | Version |
     |---|---|---|
     | `DATABASE_URL` | `cia-database-url` | `latest` |
     | `HMAC_KEY` | `cia-hmac-key` | `latest` |
   - **Containers → Settings → Cloud SQL connections → Add connection** → choose **`cia-pg`**.
     (This is what makes `host=/cloudsql/…` in the secret work — the secure connector, no networking
     to configure.)
5. **Create.** Cloud Build builds the `Dockerfile` and deploys (first build ≈ 3–5 minutes; watch the
   build log if you like).
6. Copy the **service URL** (`https://cia-XXXX.run.app`). Back in **Firebase → Authentication →
   Settings → Authorized domains → Add domain** → paste the `cia-XXXX.run.app` host so Google
   sign-in is allowed there.

**Check:** the service shows a green tick and a URL. Opening the URL shows the **sign-in screen**
(it can't load data yet — that's steps 6–8).

---

## 6. Give the app its permissions (IAM)

The service runs as a service account that must read the secrets, reach Cloud SQL, and call Vertex
AI. Find its account and grant three roles:

- On the **Cloud Run → `cia` → Security** tab, note the **service account** (usually
  `PROJECT_NUMBER-compute@developer.gserviceaccount.com`).
- Console → **IAM & Admin → IAM** → find that account → pencil (**Edit principal**) → **+ Add
  another role**, add each of:
  - **Cloud SQL Client**
  - **Secret Manager Secret Accessor**
  - **Vertex AI User**
  - **Save.**
- Back on **Cloud Run → `cia` → Edit & deploy new revision → Deploy** (a no-change redeploy) so the
  running revision picks up the new permissions.

**Check:** Cloud Run → `cia` → **Logs** has no `permission denied` / secret-access errors after the
redeploy.

---

## 7. Run the database migration (one Cloud Run Job)

This creates the tables. It only needs to run once per environment (and again after an update that
adds tables).

Console → **Cloud Run → Jobs → Create job**.

- **Container image:** reuse the image Cloud Build just made — open **Cloud Run → `cia` → Revisions**,
  copy the **Image URL** (ends in `@sha256:…`) and paste it here.
- **Job name:** `cia-migrate` · **Region:** `us-central1`.
- **Container → Settings:**
  - **Container command:** `uv`
  - **Container arguments** (one per line): `run`, `python`, `-m`, `app.migrate`
- **Variables & Secrets → Reference a secret:** `DATABASE_URL` → `cia-database-url` → `latest`.
- **Container → Settings → Cloud SQL connections → Add connection** → **`cia-pg`**.
- **Security → Service account:** the same one you granted roles to in step 6.
- **Create**, then **Execute** (button at the top).

**Check:** the execution shows **Succeeded**; its logs end with `migration complete` (or
`already at head` if you run it again).

---

## 8. Load the catalogue (one click in the app)

The app is live but empty — it says so honestly. Load the data from inside the app, no command line:

1. Open the **service URL** and **sign in** with `tom.hedgecoth@zennify.com` or
   `mishley.otiende@zennify.com` (Google, `@zennify.com`).
2. Go to **Settings** (gear, top-right) → the **Catalogue setup** card.
3. Click **1 · Provision** (seeds ~851 sub-capabilities + their enrichment), then **2 · Carry
   stories** (loads the canonical 14,406-story delivery corpus and maps it on). Each shows a toast
   with the counts; both are safe to click again.
4. On **News watch / Trends / Benchmarks / Vendor intelligence**, click **Scan now** to fill them —
   or just leave it; the weekly/monthly schedulers do it automatically.

**Check:** the header shows `v7 · provisioned`; **Mission control** shows the four pillars with
real counts.

---

## You're done

Everything persists in Cloud SQL — it survives restarts, redeploys and new users. The two
administrators can now add or remove other admins from **Settings → Administrators** (no redeploy),
and turn each ingestion source on/off in **Settings → Ingestion source registry**.

## Updating later

Push to `main` (or merge a PR). Because the service is set to **continuously deploy from the repo**,
Cloud Run rebuilds and rolls out the new revision automatically. If the update **added database
tables**, run the **`cia-migrate`** job once more (Cloud Run → Jobs → `cia-migrate` → **Execute**)
— it's safe to run anytime and is a no-op when there's nothing to migrate.

**Roll back:** Cloud Run → `cia` → **Revisions** → pick a previous green revision → **Manage
traffic → 100%** to it.

---

## If something goes wrong

| What you see | Why | Fix |
|---|---|---|
| `Invalid Tier … for (ENTERPRISE_PLUS)` when creating the DB | the instance defaulted to Enterprise Plus | recreate it choosing **Enterprise** edition (step 2) |
| `databases/users create` says 403/404 on `cia-pg` | the instance above didn't finish creating | wait for the instance to be **Runnable**, then add the DB/user (step 2) |
| app loads but every action spins / errors; logs show DB errors | `DATABASE_URL` secret wrong, or the Cloud SQL connection / IAM not added | re-check step 3 value, the Cloud SQL connection (step 5), and the 3 roles (step 6); redeploy |
| sign-in popup says the domain isn't allowed | the Cloud Run URL isn't an authorized domain | Firebase → Authentication → Settings → **Authorized domains** → add it (step 5.6) |
| `403 account not permitted` after Google login | not a verified `@zennify.com` account | use a verified `@zennify.com` Google account |
| Mission control empty after deploy | catalogue not loaded yet | Settings → **Catalogue setup** → Provision, then Carry stories (step 8) |
| a scan button says "source disabled" | that source is turned off in the registry | Settings → **Ingestion source registry** → toggle it on |

---

## Appendix — the command-line / CI path (optional)

Prefer scripts or wiring CI? Everything above can also be done from the command line. The repo ships
a one-run, self-healing deploy script and a local-parity harness:

- **`scripts/deploy_cloudrun.sh`** — `PROJECT_ID=… REGION=… ./scripts/deploy_cloudrun.sh`: builds
  `linux/amd64` (falls back to the GCR mirror on a Docker Hub rate-limit), pushes by digest, runs
  the migrate job **to completion before** shifting traffic, deploys with `--no-traffic`, smoke-tests
  `/healthz`, then promotes — rolling traffic back automatically on any failure.
- **`scripts/qa_walk.py`** — `BASE=<service-url> TOKEN=<firebase-id-token> python3 scripts/qa_walk.py`:
  walks every surface and asserts the contract, the trust envelope, reasoning backlinks and the
  edge cases (add `STRICT=1` against a hermetic build for exact fixture counts).
- **`scripts/dev_up.sh`** — local stack (Docker + pgvector Postgres + migrations + SPA) for a
  no-cloud, no-spend run: `LLM_MODE=hermetic AUTH_MODE=dev` serves the whole app on `localhost`.

The one-time infrastructure (service accounts with least-privilege roles, Cloud SQL, secrets, the
VPC/private-IP option, schedulers) is the same set the Console steps create; Terraform will codify
it in a later stage. Until then, the Console steps above are the source of truth.
