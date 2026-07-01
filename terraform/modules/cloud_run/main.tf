# cloud_run — the CIA service, the one-shot migration Job, Cloud Scheduler jobs, and the Cloud
# Tasks ingest queue (+ DLQ).
#
# Safeguard alignment:
#   * Image is deployed BY DIGEST (var.image_digest).
#   * min_instances >= 2, startup CPU boost, startup probe on /healthz GATES traffic (§16).
#   * Private Cloud SQL only: VPC connector + private-ranges egress; DB creds from Secret Manager.
#   * LLM_MODE=live => the app builds a Vertex client and uses ADC (cia-run has aiplatform.user);
#     NO API keys anywhere. Secret-backed env for DB URL / HMAC / OAuth from Secret Manager.
#   * The migration Job (cia-jobs) runs alembic to completion BEFORE traffic shifts; Terraform
#     defines it but the deploy pipeline (scripts/deploy_cloudrun.sh) EXECUTES it — Terraform never
#     runs migrations (safeguard #5).
#   * Scheduler invokes admin endpoints via OIDC as cia-scheduler (run.invoker only).
#   * NO allUsers / allAuthenticatedUsers invoker binding anywhere.

terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 5.40, < 7.0"
    }
    google-beta = {
      source  = "hashicorp/google-beta"
      version = ">= 5.40, < 7.0"
    }
  }
}

locals {
  # Deterministic run.app URL; used as PUBLIC_BASE_URL default when service_base_url is empty.
  default_run_url  = "https://${var.service_name}-${var.project_number}.${var.region}.run.app"
  public_base_url  = var.service_base_url != "" ? var.service_base_url : local.default_run_url
  vpc_egress_value = var.vpc_egress == "all-traffic" ? "ALL_TRAFFIC" : "PRIVATE_RANGES_ONLY"

  # Plain (non-secret) environment for the service.
  base_env = merge(
    {
      LLM_MODE                   = var.llm_mode
      AUTH_MODE                  = var.auth_mode
      PORT                       = "8080"
      PUBLIC_BASE_URL            = local.public_base_url
      GOOGLE_OAUTH_HOSTED_DOMAIN = var.oauth_hosted_domain
      APP_ENV                    = "prod"
    },
    var.extra_env,
  )
}

# ---------------------------------------------------------------------------
# The Cloud Run SERVICE (v2)
# ---------------------------------------------------------------------------

resource "google_cloud_run_v2_service" "service" {
  project  = var.project_id
  name     = var.service_name
  location = var.region
  ingress  = var.ingress == "internal" ? "INGRESS_TRAFFIC_INTERNAL_ONLY" : (var.ingress == "internal-and-cloud-load-balancing" ? "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER" : "INGRESS_TRAFFIC_ALL")

  # Terraform manages infra; the deploy pipeline manages the running image + traffic split. Ignore
  # image/traffic drift so `terraform apply` never fights a canary/rollback done by the deployer.
  deletion_protection = true

  template {
    service_account       = var.run_sa_email
    execution_environment = "EXECUTION_ENVIRONMENT_GEN2" # gen2 required for VPC connector + probes

    scaling {
      min_instance_count = var.min_instances
      max_instance_count = var.max_instances
    }

    max_instance_request_concurrency = var.concurrency
    timeout                          = "${var.request_timeout_seconds}s"

    # Private Cloud SQL egress via the serverless VPC connector.
    vpc_access {
      connector = var.vpc_connector_id
      egress    = local.vpc_egress_value
    }

    containers {
      image = var.image_digest

      ports {
        container_port = 8080
      }

      resources {
        limits = {
          cpu    = var.cpu
          memory = var.memory
        }
        cpu_idle          = false # keep CPU allocated (min_instances warm pool)
        startup_cpu_boost = var.startup_cpu_boost
      }

      # Plain env.
      dynamic "env" {
        for_each = local.base_env
        content {
          name  = env.key
          value = env.value
        }
      }

      # Secret-backed env from Secret Manager ('latest' enabled version). Values never in TF/state.
      dynamic "env" {
        for_each = var.secret_env
        content {
          name = env.key
          value_source {
            secret_key_ref {
              secret  = env.value
              version = "latest"
            }
          }
        }
      }

      # Startup probe: gates traffic — a revision receives traffic only after /healthz is 200.
      startup_probe {
        initial_delay_seconds = 5
        period_seconds        = 5
        timeout_seconds       = 3
        failure_threshold     = 30 # up to ~150s for cold boot + DB connect
        http_get {
          path = var.healthz_path
          port = 8080
        }
      }

      # Liveness probe: restarts a hung instance.
      liveness_probe {
        initial_delay_seconds = 15
        period_seconds        = 30
        timeout_seconds       = 5
        failure_threshold     = 3
        http_get {
          path = var.livez_path
          port = 8080
        }
      }

      # Mount the Cloud SQL socket so the app can reach it at /cloudsql/<connection_name>.
      volume_mounts {
        name       = "cloudsql"
        mount_path = "/cloudsql"
      }
    }

    # Mount the Cloud SQL instance (socket) into the service.
    volumes {
      name = "cloudsql"
      cloud_sql_instance {
        instances = [var.cloudsql_connection_name]
      }
    }
  }

  lifecycle {
    ignore_changes = [
      # Deploy pipeline owns the running image + traffic; do not let TF overwrite a canary/rollback.
      template[0].containers[0].image,
      client,
      client_version,
    ]
  }
}

# Invoker bindings (e.g. cia-scheduler). NEVER allUsers / allAuthenticatedUsers.
resource "google_cloud_run_v2_service_iam_member" "invokers" {
  for_each = toset(var.invoker_members)

  project  = var.project_id
  location = google_cloud_run_v2_service.service.location
  name     = google_cloud_run_v2_service.service.name
  role     = "roles/run.invoker"
  member   = each.value
}

# ---------------------------------------------------------------------------
# The one-shot migration/refresh JOB (cia-jobs). Terraform DEFINES it; the deploy pipeline runs it
# to completion BEFORE shifting traffic (safeguard #5 — never on app startup, never from Terraform).
# ---------------------------------------------------------------------------

resource "google_cloud_run_v2_job" "migrate" {
  project  = var.project_id
  name     = var.migrate_job_name
  location = var.region

  deletion_protection = false

  template {
    template {
      service_account       = var.jobs_sa_email
      execution_environment = "EXECUTION_ENVIRONMENT_GEN2"
      timeout               = "${var.migrate_task_timeout_seconds}s"
      max_retries           = var.migrate_max_retries

      vpc_access {
        connector = var.vpc_connector_id
        egress    = local.vpc_egress_value
      }

      containers {
        image   = var.image_digest
        command = var.migrate_command
        args    = var.migrate_args

        resources {
          limits = {
            cpu    = "2"
            memory = "2Gi"
          }
        }

        # Same DB / config env as the service so the migration connects to private Cloud SQL.
        dynamic "env" {
          for_each = local.base_env
          content {
            name  = env.key
            value = env.value
          }
        }

        dynamic "env" {
          for_each = var.secret_env
          content {
            name = env.key
            value_source {
              secret_key_ref {
                secret  = env.value
                version = "latest"
              }
            }
          }
        }

        volume_mounts {
          name       = "cloudsql"
          mount_path = "/cloudsql"
        }
      }

      volumes {
        name = "cloudsql"
        cloud_sql_instance {
          instances = [var.cloudsql_connection_name]
        }
      }
    }
  }

  lifecycle {
    # The deploy pipeline updates the job image (by digest) at deploy time; don't fight it.
    ignore_changes = [
      template[0].template[0].containers[0].image,
      template[0].template[0].containers[0].args,
      client,
      client_version,
    ]
  }
}

# ---------------------------------------------------------------------------
# Cloud Scheduler → the service's admin endpoints (OIDC as cia-scheduler).
# One job per config/schedules.yaml entry (wired via var.scheduler_jobs from the env root).
# ---------------------------------------------------------------------------

resource "google_cloud_scheduler_job" "jobs" {
  for_each = var.scheduler_jobs

  project     = var.project_id
  region      = var.region
  name        = "cia-${each.key}"
  description = each.value.description
  schedule    = each.value.cron
  time_zone   = var.scheduler_timezone

  attempt_deadline = var.scheduler_attempt_deadline

  retry_config {
    retry_count          = 3
    min_backoff_duration = "10s"
    max_backoff_duration = "300s"
    max_doublings        = 3
  }

  http_target {
    http_method = "POST"
    uri         = "${local.public_base_url}${replace(each.value.path_template, "$${version}", var.scheduler_target_version)}"

    headers = {
      "Content-Type" = "application/json"
    }

    # OIDC token minted for cia-scheduler; audience = the service URL so Cloud Run accepts it.
    oidc_token {
      service_account_email = var.scheduler_sa_email
      audience              = local.public_base_url
    }
  }
}

# ---------------------------------------------------------------------------
# Cloud Tasks — async ingest queue + a dead-letter queue. Nothing is dropped: when a task exhausts
# `max_attempts` on the ingest queue the app enqueues it onto the DLQ for review (safeguard #9).
#
# NOTE: Cloud Tasks has no server-side "dead_letter_queue" pointer (unlike Pub/Sub). The DLQ is a
# separate queue here; the application's resilience layer (backend/app/resilience/) re-enqueues a
# poison task onto it after the ingest queue's bounded retries are exhausted. Terraform provisions
# both queues; the routing is enforced in code.
# ---------------------------------------------------------------------------

resource "google_cloud_tasks_queue" "dlq" {
  project         = var.project_id
  location        = var.region
  name            = var.tasks_dlq_name
  deletion_policy = "PREVENT" # keep captured poison tasks; deleting the DLQ would lose them
}

resource "google_cloud_tasks_queue" "ingest" {
  project  = var.project_id
  location = var.region
  name     = var.tasks_queue_name

  rate_limits {
    max_dispatches_per_second = var.tasks_max_dispatches_per_second
    max_concurrent_dispatches = var.tasks_max_concurrent_dispatches
  }

  retry_config {
    max_attempts       = var.tasks_max_attempts
    min_backoff        = "5s"
    max_backoff        = "300s"
    max_doublings      = 4
    max_retry_duration = "0s" # unlimited by wall-clock; bounded by max_attempts
  }
}
