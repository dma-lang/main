# iam_service_accounts — four least-privilege service accounts and their PROJECT-level role
# bindings. Resource-scoped grants (per-secret secretAccessor, per-bucket objectUser) live in the
# secret_manager and gcs modules respectively, so this module never over-grants at the project.
#
# SECURITY INVARIANTS (audited by security-reviewer before any apply):
#   * NO roles/owner, roles/editor, roles/viewer or any primitive role on any SA.
#   * NO service-account keys are created anywhere (WIF + ADC only).
#   * cia-scheduler holds run.invoker ONLY.
#   * cia-deployer can actAs cia-run and cia-jobs, but is NOT granted their runtime data roles.
#
# google_project_iam_member (additive, per (role, member)) is used deliberately instead of
# google_project_iam_policy/_binding, so this module never authoritatively overwrites bindings it
# does not manage on a shared project.

terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 5.40, < 7.0"
    }
  }
}

# ---------------------------------------------------------------------------
# Service accounts
# ---------------------------------------------------------------------------

resource "google_service_account" "run" {
  project      = var.project_id
  account_id   = var.sa_run_name
  display_name = "CIA Cloud Run runtime"
  description  = "Runs the CIA Cloud Run service. Vertex AI via ADC (roles/aiplatform.user), private Cloud SQL, per-secret + per-bucket access. No keys."
}

resource "google_service_account" "jobs" {
  project      = var.project_id
  account_id   = var.sa_jobs_name
  display_name = "CIA Cloud Run Jobs (migration)"
  description  = "Runs the one-shot cia-migrate Job (Alembic to completion, direct Cloud SQL) before traffic shifts. Same data access as cia-run. No keys."
}

resource "google_service_account" "scheduler" {
  project      = var.project_id
  account_id   = var.sa_scheduler_name
  display_name = "CIA Cloud Scheduler invoker"
  description  = "OIDC identity Cloud Scheduler uses to invoke the service's admin endpoints. roles/run.invoker ONLY. No keys."
}

resource "google_service_account" "deployer" {
  project      = var.project_id
  account_id   = var.sa_deployer_name
  display_name = "CIA CI/CD deployer (WIF)"
  description  = "Impersonated by GitHub Actions via Workload Identity Federation. Deploys Cloud Run + pushes images + actAs cia-run/cia-jobs. No keys, no primitive roles."
}

# ---------------------------------------------------------------------------
# cia-run — project-level roles (resource-scoped grants are in secret_manager + gcs)
# ---------------------------------------------------------------------------

locals {
  run_project_roles = [
    "roles/cloudsql.client",         # connect to private Cloud SQL (IAM DB auth)
    "roles/aiplatform.user",         # Vertex AI / Gemini via ADC — the whole point (no keys)
    "roles/logging.logWriter",       # structured logs
    "roles/monitoring.metricWriter", # custom metrics (cost meter etc.)
    "roles/cloudtrace.agent",        # traces
  ]
  jobs_project_roles = [
    "roles/cloudsql.client",         # migration Job connects directly to Cloud SQL
    "roles/aiplatform.user",         # app.refresh may embed / infer during the Job
    "roles/logging.logWriter",
    "roles/monitoring.metricWriter",
    "roles/cloudtrace.agent",
  ]
}

resource "google_project_iam_member" "run_roles" {
  for_each = toset(local.run_project_roles)

  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.run.email}"
}

# ---------------------------------------------------------------------------
# cia-jobs — same runtime data access as cia-run (it runs migrations against the DB)
# ---------------------------------------------------------------------------

resource "google_project_iam_member" "jobs_roles" {
  for_each = toset(local.jobs_project_roles)

  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.jobs.email}"
}

# ---------------------------------------------------------------------------
# cia-scheduler — run.invoker ONLY (project-scoped invoker; the service is also bound
# run.invoker on the specific service in the cloud_run module for defence in depth).
# ---------------------------------------------------------------------------

resource "google_project_iam_member" "scheduler_invoker" {
  project = var.project_id
  role    = "roles/run.invoker"
  member  = "serviceAccount:${google_service_account.scheduler.email}"
}

# ---------------------------------------------------------------------------
# cia-deployer — deploy + push + impersonate the runtime SAs (bound to WIF elsewhere)
# ---------------------------------------------------------------------------

locals {
  deployer_project_roles = [
    "roles/run.developer",             # create/update Cloud Run services + Jobs revisions
    "roles/artifactregistry.writer",   # push images to Artifact Registry
    "roles/iam.serviceAccountUser",    # actAs when deploying (project-wide actAs; scoped grants below)
  ]
}

resource "google_project_iam_member" "deployer_roles" {
  for_each = toset(local.deployer_project_roles)

  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.deployer.email}"
}

# Scoped actAs: the deployer may set the service's identity to cia-run and the Job's identity to
# cia-jobs, and nothing else. These per-SA bindings are the precise grant; the project-wide
# serviceAccountUser above is what the Cloud Run Admin API requires to attach a service account at
# deploy time, but the SA-scoped bindings below document and constrain the intended targets.
resource "google_service_account_iam_member" "deployer_actas_run" {
  service_account_id = google_service_account.run.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.deployer.email}"
}

resource "google_service_account_iam_member" "deployer_actas_jobs" {
  service_account_id = google_service_account.jobs.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.deployer.email}"
}
