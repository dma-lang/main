# CIA — prod environment root. Wires every module. APPLY ORDER matters: project_services is a hard
# dependency of everything else (an API must be on before its resources exist), so downstream
# modules depend_on it explicitly.
#
# Nothing here contains a secret VALUE. The sm module creates secret RESOURCES; values are added
# out-of-band by the operator (terraform/README.md).

# ---------------------------------------------------------------------------
# 0. Enable APIs FIRST.
# ---------------------------------------------------------------------------

module "project_services" {
  source     = "../../modules/project_services"
  project_id = var.project_id
}

# ---------------------------------------------------------------------------
# 1. Service accounts + least-privilege project roles.
# ---------------------------------------------------------------------------

module "iam_service_accounts" {
  source     = "../../modules/iam_service_accounts"
  project_id = var.project_id

  depends_on = [module.project_services]
}

# ---------------------------------------------------------------------------
# 2. Workload Identity Federation (keyless CI/CD → cia-deployer).
# ---------------------------------------------------------------------------

module "workload_identity" {
  source         = "../../modules/workload_identity"
  project_id     = var.project_id
  github_repo    = var.github_repo
  deployer_sa_id = module.iam_service_accounts.deployer_sa_id

  depends_on = [module.project_services]
}

# ---------------------------------------------------------------------------
# 3. Private Cloud SQL (VPC + PSA + connector + PG16).
# ---------------------------------------------------------------------------

module "cloudsql" {
  source            = "../../modules/cloudsql"
  project_id        = var.project_id
  region            = var.region
  tier              = var.db_tier
  availability_type = var.db_availability_type
  database_name     = var.db_name
  database_user     = var.db_user

  depends_on = [module.project_services]
}

# ---------------------------------------------------------------------------
# 4. Secret RESOURCES (values added out-of-band). Access → cia-run + cia-jobs only.
# ---------------------------------------------------------------------------

module "secret_manager" {
  source     = "../../modules/sm"
  project_id = var.project_id
  region     = var.region

  accessor_members = [
    "serviceAccount:${module.iam_service_accounts.run_sa_email}",
    "serviceAccount:${module.iam_service_accounts.jobs_sa_email}",
  ]

  depends_on = [module.project_services]
}

# ---------------------------------------------------------------------------
# 5. Artifact Registry (deploy by digest). Push→deployer, pull→run/jobs.
# ---------------------------------------------------------------------------

module "artifact_registry" {
  source     = "../../modules/artifact_registry"
  project_id = var.project_id
  region     = var.region

  writer_members = ["serviceAccount:${module.iam_service_accounts.deployer_sa_email}"]
  reader_members = [
    "serviceAccount:${module.iam_service_accounts.run_sa_email}",
    "serviceAccount:${module.iam_service_accounts.jobs_sa_email}",
  ]

  depends_on = [module.project_services]
}

# ---------------------------------------------------------------------------
# 6. GCS buckets (private, enforced no-public, versioned, lifecycle). objectUser→run/jobs.
# ---------------------------------------------------------------------------

module "gcs" {
  source      = "../../modules/gcs"
  project_id  = var.project_id
  region      = var.region
  name_prefix = "${var.project_id}-cia"

  object_user_members = [
    "serviceAccount:${module.iam_service_accounts.run_sa_email}",
    "serviceAccount:${module.iam_service_accounts.jobs_sa_email}",
  ]

  depends_on = [module.project_services]
}

# ---------------------------------------------------------------------------
# 7. Cloud Run service + migration Job + Scheduler + Tasks.
# ---------------------------------------------------------------------------

locals {
  # Secret Manager secret_id => the ENV VAR the app reads. Keeps app env <-> secrets explicit.
  # Keys are the ENV names; values are the secret_ids created by the sm module.
  secret_env = {
    DATABASE_URL               = module.secret_manager.secret_ids["database_url"]
    HMAC_KEY                   = module.secret_manager.secret_ids["hmac_export_key"]
    GOOGLE_OAUTH_CLIENT_ID     = module.secret_manager.secret_ids["oauth_client_id"]
    GOOGLE_OAUTH_CLIENT_SECRET = module.secret_manager.secret_ids["oauth_client_secret"]
  }

  # config/schedules.yaml, mapped to the service's existing admin endpoints. $${version} is
  # substituted with var.scheduler_target_version by the cloud_run module. Crons are UTC (the
  # module sets time_zone = Etc/UTC), matching schedules.yaml.
  scheduler_jobs = {
    jira_ingest = {
      cron          = "0 * * * *"
      path_template = "/api/admin/carry-forward/$${version}"
      description   = "Hourly canonical Jira story ingest + carry-forward (webhook is the primary trigger; this is the safety poll)."
    }
    news_scan = {
      cron          = "0 6 * * 1"
      path_template = "/api/admin/evidence/scan/news/$${version}"
      description   = "Weekly grounded-search news fetch -> classify -> map -> gate (Mon 06:00 UTC)."
    }
    embeddings_build = {
      cron          = "40 6 * * 1"
      path_template = "/api/admin/embeddings/build/$${version}"
      description   = "Weekly fill of the vector(768) space — embed un-embedded subcaps (Mon 06:40 UTC)."
    }
    trend_detect = {
      cron          = "30 6 * * 1"
      path_template = "/api/admin/trends/scan/$${version}"
      description   = "Weekly multi-signal trend detection over the last 8 weeks (Mon 06:30 UTC)."
    }
    unscoped_subvertical_detect = {
      cron          = "45 6 * * 1"
      path_template = "/api/admin/change-flags/scan-subverticals/$${version}"
      description   = "Weekly scan for delivery outside the 9 subverticals -> gated candidate (Mon 06:45 UTC)."
    }
    kg_structural_propose = {
      cron          = "50 6 * * 1"
      path_template = "/api/admin/kg/propose/$${version}"
      description   = "Weekly KG Layer-B discovery -> dashed pending_edge proposals (Mon 06:50 UTC)."
    }
    use_case_gap_detect = {
      cron          = "55 6 * * 1"
      path_template = "/api/admin/use-case-gaps/$${version}"
      description   = "Weekly scan for use cases implied by delivery but absent -> gated (Mon 06:55 UTC)."
    }
    vendor_scan = {
      cron          = "0 7 * * 1"
      path_template = "/api/admin/evidence/scan/vendor/$${version}"
      description   = "Weekly vendor-development ingest -> 8-type classification -> subcap impact (Mon 07:00 UTC)."
    }
    benchmark_scan = {
      cron          = "0 8 1 * *"
      path_template = "/api/admin/evidence/scan/benchmarks/$${version}"
      description   = "Monthly benchmark ingest -> bootstrap CI -> adversarial verdict (1st 08:00 UTC)."
    }
    monthly_cycle = {
      cron          = "0 9 1 * *"
      path_template = "/api/admin/suggestions/propose/$${version}"
      description   = "Monthly consultant cycle — gather signal, run G1-G8, stage suggestions (1st 09:00 UTC)."
    }
    quarterly_digest = {
      cron          = "0 10 1 1,4,7,10 *"
      path_template = "/api/admin/digest/generate"
      description   = "Quarterly strategic digest (synthesis + adversarial + signed export) (1st Jan/Apr/Jul/Oct 10:00 UTC)."
    }
    reconciliation = {
      cron          = "0 3 * * *"
      path_template = "/api/admin/change-flags/scan/$${version}"
      description   = "Daily data-integrity self-checks: re-derive counts, re-gate drifted rows (03:00 UTC)."
    }
  }
}

module "cloud_run" {
  source         = "../../modules/cloud_run"
  project_id     = var.project_id
  project_number = var.project_number
  region         = var.region

  service_name       = "cia"
  run_sa_email       = module.iam_service_accounts.run_sa_email
  jobs_sa_email      = module.iam_service_accounts.jobs_sa_email
  scheduler_sa_email = module.iam_service_accounts.scheduler_sa_email

  image_digest = var.image_digest

  vpc_connector_id         = module.cloudsql.vpc_connector_id
  cloudsql_connection_name = module.cloudsql.connection_name

  ingress          = var.ingress
  min_instances    = var.min_instances
  max_instances    = var.max_instances
  concurrency      = var.concurrency
  service_base_url = var.service_base_url

  llm_mode            = var.llm_mode
  auth_mode           = var.auth_mode
  oauth_hosted_domain = var.oauth_hosted_domain

  secret_env = local.secret_env

  # Scheduler invokes the service; grant that SA run.invoker on THIS service (defence in depth on
  # top of the project-level binding in iam_service_accounts).
  invoker_members = ["serviceAccount:${module.iam_service_accounts.scheduler_sa_email}"]

  scheduler_target_version = var.scheduler_target_version
  scheduler_jobs           = local.scheduler_jobs

  depends_on = [
    module.project_services,
    module.cloudsql,
    module.secret_manager,
    module.artifact_registry,
  ]
}

# ---------------------------------------------------------------------------
# 8. Firebase / Identity Platform (mostly a documented manual step; TF where possible).
# ---------------------------------------------------------------------------

module "firebase" {
  source     = "../../modules/firebase"
  project_id = var.project_id

  manage_identity_platform_config = var.manage_identity_platform_config
  authorized_domains = compact([
    "${var.project_id}.firebaseapp.com",
    replace(replace(module.cloud_run.public_base_url, "https://", ""), "/", ""),
  ])

  depends_on = [module.project_services]
}

# ---------------------------------------------------------------------------
# 9. Monitoring — uptime check, error metric, budget alert.
# ---------------------------------------------------------------------------

module "monitoring" {
  source     = "../../modules/monitoring"
  project_id = var.project_id

  # Host (no scheme) of the service for the uptime check.
  service_host = replace(replace(module.cloud_run.public_base_url, "https://", ""), "/", "")

  alert_email              = var.alert_email
  create_budget            = var.create_budget
  billing_account          = var.billing_account
  monthly_budget_amount    = var.monthly_budget
  budget_threshold_percent = 0.8

  depends_on = [module.project_services, module.cloud_run]
}
