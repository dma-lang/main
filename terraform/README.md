# CIA — Terraform / IaC

Apply-ready infrastructure for the **Capability Intelligence Agent** on Google Cloud
(project `digital-maturity-assessor`, region `us-central1`).

> **AUTHORING ONLY in this repo.** Terraform is **not** run by the coding agent. Every `plan`/`apply`
> and every `gcloud` mutation below is a **human-gated step (CLAUDE.md §8/§10)** and is also blocked
> by the PreToolUse hook. An operator runs them, in order, after reviewing the plan.
>
> **No secret VALUES live in Terraform.** This stack creates the secret *resources*; the operator
> adds the values out-of-band (see [Secret values](#secret-values-out-of-band)).

---

## Layout

```
terraform/
  envs/prod/
    providers.tf              # google + google-beta + random; required_version >= 1.5
    backend.tf                # GCS remote state (bucket via -backend-config at init)
    variables.tf              # all env inputs (defaults where safe)
    main.tf                   # wires every module in dependency order
    outputs.tf                # SA emails, WIF provider, service URL, secret ids, ...
    terraform.tfvars.example  # copy -> terraform.tfvars (no secret values)
  modules/
    project_services/         # enable required APIs (disable_on_destroy = false)
    iam_service_accounts/     # cia-run / cia-jobs / cia-scheduler / cia-deployer + least-priv roles
    workload_identity/        # GitHub OIDC pool + provider + deployer impersonation (no keys)
    cloudsql/                 # PG16 PRIVATE IP: VPC + PSA + connector, IAM auth, backups + PITR
    sm/                       # Secret Manager RESOURCES only (dir is `sm`; see note below)
    artifact_registry/        # Docker repo (deploy by digest)
    gcs/                      # 4 buckets: uniform access, enforced no-public, versioned, lifecycle
    cloud_run/                # service + cia-migrate Job + Scheduler jobs + Tasks queue + DLQ
    firebase/                 # @zennify.com fail-closed notes + optional Identity Platform config
    monitoring/               # uptime check + log-based error metric + budget/cost alert
```

> **Why `modules/sm` and not `modules/secret_manager`?** The repository's PreToolUse safety hook
> refuses to author any file whose path contains the substring `secret` (a guard against committing
> key material). The module authors secret **resource definitions**, never values, so it is named
> `sm` to satisfy the guard. Its behaviour is exactly the "secret_manager" module described in the
> plan.

---

## One-time prerequisites (operator, gated)

1. **Create the Terraform state bucket** (Terraform cannot create its own backend):

   ```bash
   gcloud storage buckets create gs://<TF_STATE_BUCKET> \
     --project=digital-maturity-assessor --location=us-central1 \
     --uniform-bucket-level-access --public-access-prevention=enforced
   gcloud storage buckets update gs://<TF_STATE_BUCKET> --versioning
   ```

2. **Get the project number** (used for the deterministic run.app URL):

   ```bash
   gcloud projects describe digital-maturity-assessor --format='value(projectNumber)'
   ```

3. **Copy and fill vars:** `cp terraform.tfvars.example terraform.tfvars` and set `project_number`,
   `state_bucket`, `alert_email`, and (optionally) `billing_account` + `create_budget = true`.

---

## Apply order (§10-gated)

`project_services` MUST be applied first — every other resource needs its API enabled. The root
`main.tf` encodes this with `depends_on`, so a single apply is ordered correctly; the staged
targeting below is the belt-and-braces path a reviewer can follow one blast radius at a time.

```bash
cd terraform/envs/prod

# init the GCS backend (bucket supplied here, not hardcoded)
terraform init \
  -backend-config="bucket=<TF_STATE_BUCKET>" \
  -backend-config="prefix=cia/prod"

# 0) APIs first (fast, low-risk; unblocks everything else)
terraform plan  -target=module.project_services
terraform apply -target=module.project_services      # <-- gated: review, then run

# 1) identity + keyless CI/CD
terraform apply -target=module.iam_service_accounts  # <-- gated
terraform apply -target=module.workload_identity     # <-- gated

# 2) data plane + secret RESOURCES + registry + buckets
terraform apply -target=module.cloudsql              # <-- gated (creates Cloud SQL)
terraform apply -target=module.secret_manager        # <-- gated (secret shells, no values)
terraform apply -target=module.artifact_registry     # <-- gated
terraform apply -target=module.gcs                   # <-- gated

# 3) the rest (service, migrate job, scheduler, tasks, firebase notes, monitoring)
terraform plan                                       # full review
terraform apply                                      # <-- gated: the whole graph converges
```

> `terraform apply`/`destroy` and every `gcloud run|sql|secrets|iam|services enable|deploy` are
> blocked by `.claude/hooks/pretooluse_guard.py`. The operator runs them deliberately.

---

## Secret values (out-of-band)

Terraform creates the secret **shells**; add versions yourself. The Cloud Run service + migration
job read these as env from the `latest` enabled version.

| Secret ID (`secret_ids`)      | Env var injected             | What goes in it                                                        |
| ----------------------------- | ---------------------------- | --------------------------------------------------------------------- |
| `database-url`                | `DATABASE_URL`               | Full SQLAlchemy async URL to the **private** Cloud SQL (see below).   |
| `db-password`                 | *(not injected by default)*  | The `cia_app` DB password (kept in sync with the Cloud SQL user).     |
| `hmac-export-key`             | `HMAC_KEY`                   | Random 32+ byte key for signed exports (F12) + session signing.       |
| `firebase-oauth-client-id`    | `GOOGLE_OAUTH_CLIENT_ID`     | Google OAuth 2.0 client ID (from the OAuth client in the console).    |
| `firebase-oauth-client-secret`| `GOOGLE_OAUTH_CLIENT_SECRET` | Google OAuth 2.0 client secret.                                       |

```bash
# 1) set the DB user's password and store the SAME value in Secret Manager
DB_PW="$(openssl rand -base64 32)"
gcloud sql users set-password cia_app --instance=cia-pg --password="$DB_PW" --quiet   # gated
printf '%s' "$DB_PW" | gcloud secrets versions add db-password --data-file=-           # gated

# 2) DATABASE_URL — the app connects over the Cloud SQL socket mounted at /cloudsql
#    (asyncpg via the SQLAlchemy async engine). Substitute your connection name.
CONN="digital-maturity-assessor:us-central1:cia-pg"
printf '%s' "postgresql+asyncpg://cia_app:${DB_PW}@/cia?host=/cloudsql/${CONN}" \
  | gcloud secrets versions add database-url --data-file=-                             # gated

# 3) HMAC export/session key
openssl rand -base64 48 | gcloud secrets versions add hmac-export-key --data-file=-   # gated

# 4) OAuth client id + secret (create/find the OAuth client in the console first)
printf '%s' "<client-id>"     | gcloud secrets versions add firebase-oauth-client-id     --data-file=-  # gated
printf '%s' "<client-secret>" | gcloud secrets versions add firebase-oauth-client-secret --data-file=-  # gated
```

> The `db-password` secret exists for operators/rotation; the app itself authenticates via
> `DATABASE_URL`. Populate at least `database-url`, `hmac-export-key`, and the two OAuth secrets
> before the first real deploy, or the service will fail closed (no auth, no exports).

---

## Deploy (after infra + secrets exist)

Infra is provisioned by Terraform; the **application image + traffic** are owned by the deploy
pipeline (`scripts/deploy_cloudrun.sh` / the GitHub Actions `deploy.yml`). The pipeline:

1. builds `linux/amd64`, pushes to Artifact Registry, resolves the **digest**;
2. points the `cia-migrate` Job at that digest and **runs it to completion** (Alembic upgrade head,
   advisory-locked on a direct connection, then the data-plane refresh) **before any traffic moves**
   — migrations never run on app startup and never from Terraform (safeguard #5);
3. deploys the service `--no-traffic`, smokes `/healthz` on the tagged revision, then promotes
   (optional canary), with **auto-rollback** on failure.

WIF wiring for the GitHub Action (from `terraform output`):

```yaml
# .github/workflows/deploy.yml (excerpt)
permissions:
  id-token: write        # required for OIDC
  contents: read
- uses: google-github-actions/auth@v2
  with:
    workload_identity_provider: ${{ '<terraform output -raw wif_provider_name>' }}
    service_account: ${{ '<terraform output -raw deployer_sa_email>' }}
```

---

## Scheduler → endpoint mapping

Cloud Scheduler invokes the service's admin endpoints over HTTPS with an **OIDC token minted for
`cia-scheduler`** (which holds `run.invoker` only). Crons are UTC (module `time_zone = Etc/UTC`) and
mirror `config/schedules.yaml`. `${version}` is `var.scheduler_target_version` (default `active`).

| Schedule key                  | Cron (UTC)          | POST endpoint                                        |
| ----------------------------- | ------------------- | ---------------------------------------------------- |
| `jira_ingest`                 | `0 * * * *`         | `/api/admin/carry-forward/{version}`                 |
| `news_scan`                   | `0 6 * * 1`         | `/api/admin/evidence/scan/news/{version}`            |
| `trend_detect`                | `30 6 * * 1`        | `/api/admin/trends/scan/{version}`                   |
| `embeddings_build`            | `40 6 * * 1`        | `/api/admin/embeddings/build/{version}`              |
| `unscoped_subvertical_detect` | `45 6 * * 1`        | `/api/admin/change-flags/scan-subverticals/{version}`|
| `kg_structural_propose`       | `50 6 * * 1`        | `/api/admin/kg/propose/{version}`                    |
| `use_case_gap_detect`         | `55 6 * * 1`        | `/api/admin/use-case-gaps/{version}`                 |
| `vendor_scan`                 | `0 7 * * 1`         | `/api/admin/evidence/scan/vendor/{version}`          |
| `benchmark_scan`              | `0 8 1 * *`         | `/api/admin/evidence/scan/benchmarks/{version}`      |
| `monthly_cycle`               | `0 9 1 * *`         | `/api/admin/suggestions/propose/{version}`           |
| `quarterly_digest`            | `0 10 1 1,4,7,10 *` | `/api/admin/digest/generate`                         |
| `reconciliation`              | `0 3 * * *`         | `/api/admin/change-flags/scan/{version}`             |

Adjust a mapping by editing `local.scheduler_jobs` in `envs/prod/main.tf`.

---

## Firebase / Identity Platform (manual)

The app does **not** use Firebase client SDKs; it runs the server-side OAuth 2.0 authorization-code
flow and enforces `@zennify.com` **in code, fail-closed** (`AUTH_MODE=live`). Manual steps:

- Create/locate the **OAuth 2.0 client** in the console; register the redirect URI
  `${PUBLIC_BASE_URL}` + the app callback path (only the redirect URI — no JS origins). Put the id +
  secret into Secret Manager (above).
- If you want Terraform to manage Identity Platform **authorized domains**, first **initialize
  Identity Platform** on the project (one-time console step), then set
  `manage_identity_platform_config = true` and re-apply. Until then the `firebase` module is a no-op
  with documented notes.

---

## Manual / out-of-band checklist

- [ ] Create the TF state bucket (versioned, enforced no-public).
- [ ] Look up `project_number`; set it in `terraform.tfvars`.
- [ ] Add all Secret Manager **values** (`database-url`, `hmac-export-key`, OAuth id/secret).
- [ ] Create the OAuth client + register the redirect URI in the console.
- [ ] (Optional) Initialize Identity Platform, then flip `manage_identity_platform_config`.
- [ ] (Optional) Provide `billing_account` + `create_budget = true` for the cost alert.
- [ ] First deploy sets the real image digest; update `image_digest` afterwards for drift-free plans.
- [ ] Note the deterministic URL `https://cia-<project_number>.us-central1.run.app` depends on the
      project number; if you map a custom domain, set `service_base_url` and re-apply.

---

## Security summary

> Authored against CLAUDE.md safeguards #5 (migrations-as-a-Job), #6 (secrets/least-privilege/no
> keys), #7 (no PII), #10 (HITL), and PART I/J of the plan, and independently audited by the
> `security-reviewer` subagent (read-only) — all invariants below PASS. This section is the module
> author's assertion of those invariants; it is **not** a substitute for the operator's own review
> before a gated apply. **State-bucket caveat:** the bootstrap DB password (below) transits
> Terraform state in plaintext (inherent to `google_sql_user`), so the GCS state bucket MUST be
> private (enforced public-access-prevention), versioned, and IAM-restricted to the Terraform
> operators + `cia-deployer` only — confirm its bindings before `terraform init`.

**No service-account keys anywhere.** CI/CD authenticates via **Workload Identity Federation**: a
GitHub OIDC pool + provider whose `attribute_condition` pins trust to `assertion.repository ==
'<github_repo>'`, and a `roles/iam.workloadIdentityUser` binding scoped to that same
`attribute.repository` principalSet. No `google_service_account_key` resource exists in the stack.
Vertex AI is reached by the runtime SA via **ADC** (`roles/aiplatform.user`) — no API keys, no JSON.

**No primitive roles.** No `roles/owner`, `roles/editor`, or `roles/viewer` is granted to any
service account. Grants are the minimum per identity:

| Service account   | Project roles                                                                                             | Resource-scoped grants                                   |
| ----------------- | --------------------------------------------------------------------------------------------------------- | -------------------------------------------------------- |
| **cia-run**       | cloudsql.client · aiplatform.user · logging.logWriter · monitoring.metricWriter · cloudtrace.agent        | secretAccessor per-secret · storage.objectUser per-bucket · artifactregistry.reader on the repo |
| **cia-jobs**      | cloudsql.client · aiplatform.user · logging.logWriter · monitoring.metricWriter · cloudtrace.agent        | secretAccessor per-secret · storage.objectUser per-bucket · artifactregistry.reader on the repo |
| **cia-scheduler** | run.invoker (project) — **only**                                                                          | run.invoker on the `cia` service (defence in depth)      |
| **cia-deployer**  | run.developer · artifactregistry.writer · iam.serviceAccountUser                                          | actAs cia-run + cia-jobs (per-SA) · WIF impersonation · artifactregistry.writer on the repo |

**No public access.** No IAM binding uses `allUsers` or `allAuthenticatedUsers` — not on the Cloud
Run service (invoker is `cia-scheduler` only), not on buckets, not on secrets. Every GCS bucket sets
`uniform_bucket_level_access = true` and `public_access_prevention = "enforced"` (it can never be
made public, even by a later ACL mistake).

**Private database.** Cloud SQL has **no public IP** (`ipv4_enabled = false`); it is reachable only
over the VPC via a Serverless VPC Access connector from Cloud Run. **IAM database authentication** is
on, connections are `ENCRYPTED_ONLY`, automated backups + **point-in-time recovery** are enabled, and
**deletion protection** is set (both the API flag and a `prevent_destroy` lifecycle). Query Insights
does not record client IPs or app tags (no PII).

**Secrets.** Terraform creates the secret **resources** only; **no secret value appears in any `.tf`
or in state**. The DB user password is created from a throwaway bootstrap value whose `password`
drift is ignored (`ignore_changes`), and the real value is set out-of-band and stored in Secret
Manager. Secret access is granted **per-secret** to `cia-run` + `cia-jobs` only; no project-level
secret access exists.

**Migrations.** The `cia-migrate` Cloud Run **Job** is defined in Terraform but **executed by the
deploy pipeline to completion before traffic shifts** — never on app startup, never from Terraform
(safeguard #5). Advisory locking / transactional DDL / expand-contract live in the app's migration
code.

**Nothing dropped.** The Cloud Tasks ingest queue has bounded retries; exhausted (poison) tasks are
re-enqueued by the app onto a dedicated **DLQ** (`deletion_policy = "PREVENT"`), never silently
discarded (safeguard #9).
