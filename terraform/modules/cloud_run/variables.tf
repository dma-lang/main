variable "project_id" {
  description = "GCP project ID."
  type        = string
}

variable "project_number" {
  description = "GCP project NUMBER (used to build the deterministic run.app URL and some IAM members)."
  type        = string
}

variable "region" {
  description = "Region for Cloud Run, Scheduler, and Tasks."
  type        = string
  default     = "us-central1"
}

# ---- Service identity + image ----
variable "service_name" {
  description = "Cloud Run service name."
  type        = string
  default     = "cia"
}

variable "run_sa_email" {
  description = "Service account email the Cloud Run SERVICE runs as (cia-run)."
  type        = string
}

variable "jobs_sa_email" {
  description = "Service account email the migration JOB runs as (cia-jobs)."
  type        = string
}

variable "scheduler_sa_email" {
  description = "Service account email Cloud Scheduler uses for OIDC-authenticated invocations (cia-scheduler)."
  type        = string
}

variable "image_digest" {
  description = "FULL image reference pinned by digest: <region>-docker.pkg.dev/<project>/<repo>/cia@sha256:... Deploys are by digest only."
  type        = string
}

# ---- Networking (private Cloud SQL) ----
variable "vpc_connector_id" {
  description = "Serverless VPC Access connector ID for private Cloud SQL egress."
  type        = string
}

variable "cloudsql_connection_name" {
  description = "Cloud SQL instance connection name (project:region:instance) mounted into the service + job."
  type        = string
}

variable "vpc_egress" {
  description = "VPC egress mode: 'private-ranges-only' (default) or 'all-traffic'."
  type        = string
  default     = "private-ranges-only"
}

# ---- Ingress + invocation policy ----
variable "ingress" {
  description = "Ingress setting: 'all', 'internal', or 'internal-and-cloud-load-balancing'."
  type        = string
  default     = "all"
}

variable "invoker_members" {
  description = "IAM members granted roles/run.invoker on the SERVICE (e.g. cia-scheduler). NEVER allUsers/allAuthenticatedUsers."
  type        = list(string)
  default     = []
}

# ---- Scaling + concurrency (sized to the SQL connection budget) ----
variable "min_instances" {
  description = "Minimum service instances (>= 2 for availability + warm pool)."
  type        = number
  default     = 2

  validation {
    condition     = var.min_instances >= 2
    error_message = "min_instances must be >= 2 (safeguard: warm, always-on service)."
  }
}

variable "max_instances" {
  description = "Maximum service instances. Keep (max_instances * per-instance DB pool) under the Cloud SQL connection budget."
  type        = number
  default     = 10
}

variable "concurrency" {
  description = "Max concurrent requests per instance."
  type        = number
  default     = 80
}

variable "cpu" {
  description = "vCPU per instance."
  type        = string
  default     = "1"
}

variable "memory" {
  description = "Memory per instance."
  type        = string
  default     = "1Gi"
}

variable "startup_cpu_boost" {
  description = "Give extra CPU during startup to speed cold starts."
  type        = bool
  default     = true
}

variable "request_timeout_seconds" {
  description = "Per-request timeout for the service."
  type        = number
  default     = 300
}

# ---- App configuration (non-secret env) ----
variable "service_base_url" {
  description = "Canonical public URL of the service (pins the OAuth round-trip). Wired to PUBLIC_BASE_URL. If empty, defaults to the deterministic run.app URL."
  type        = string
  default     = ""
}

variable "oauth_hosted_domain" {
  description = "Google Workspace hosted domain sign-in is restricted to (fails closed)."
  type        = string
  default     = "zennify.com"
}

variable "llm_mode" {
  description = "LLM_MODE for the service: 'live' (Vertex AI via ADC) or 'hermetic' (stubs, no spend)."
  type        = string
  default     = "live"
}

variable "auth_mode" {
  description = "AUTH_MODE: 'live' (Google OAuth, fails closed) or 'dev'. Never 'dev' in prod."
  type        = string
  default     = "live"
}

variable "extra_env" {
  description = "Additional plain (non-secret) environment variables for the service."
  type        = map(string)
  default     = {}
}

# ---- Secret env references (Secret Manager secret IDs) ----
variable "secret_env" {
  description = <<-EOT
    Map of ENV_VAR_NAME => Secret Manager secret_id to inject as secret-backed env into the service
    and migration job. Example:
      {
        DATABASE_URL               = "database-url"
        HMAC_KEY                   = "hmac-export-key"
        GOOGLE_OAUTH_CLIENT_ID     = "firebase-oauth-client-id"
        GOOGLE_OAUTH_CLIENT_SECRET = "firebase-oauth-client-secret"
      }
    Values are read from the 'latest' enabled version at runtime; no values live in Terraform.
  EOT
  type        = map(string)
  default     = {}
}

# ---- Migration Job ----
variable "migrate_job_name" {
  description = "Cloud Run Job name for the one-shot migration/refresh (matches MIGRATE_JOB in the deploy script)."
  type        = string
  default     = "cia-migrate"
}

variable "migrate_command" {
  description = "Entrypoint (argv[0]) for the migration job container."
  type        = list(string)
  default     = ["uv"]
}

variable "migrate_args" {
  description = "Args for the migration job. Default runs app.refresh (alembic upgrade head, advisory-locked, THEN data-plane refresh) to completion before traffic shifts."
  type        = list(string)
  default     = ["run", "python", "-m", "app.refresh"]
}

variable "migrate_task_timeout_seconds" {
  description = "Task timeout for the migration/refresh job (refresh does more than a bare migration)."
  type        = number
  default     = 1800
}

variable "migrate_max_retries" {
  description = "Max retries for the migration job task (idempotent + advisory-locked, so retry is safe)."
  type        = number
  default     = 1
}

# ---- Probes ----
variable "healthz_path" {
  description = "Startup/readiness probe path (gates traffic)."
  type        = string
  default     = "/healthz"
}

variable "livez_path" {
  description = "Liveness probe path (restarts a hung instance)."
  type        = string
  default     = "/livez"
}

# ---- Cloud Scheduler → admin endpoints ----
variable "scheduler_target_version" {
  description = "Catalogue version the scheduled admin endpoints target (e.g. 'v7' or 'active')."
  type        = string
  default     = "active"
}

variable "scheduler_timezone" {
  description = "Time zone for Cloud Scheduler cron expressions. schedules.yaml crons are authored in UTC."
  type        = string
  default     = "Etc/UTC"
}

variable "scheduler_jobs" {
  description = <<-EOT
    Map of scheduler job key => { cron, path_template, description }. path_template may contain the
    literal $${version} placeholder, replaced with scheduler_target_version. Mirrors
    config/schedules.yaml. Each job POSTs to the service admin endpoint using OIDC as cia-scheduler.
  EOT
  type = map(object({
    cron          = string
    path_template = string
    description   = string
  }))
  default = {}
}

variable "scheduler_attempt_deadline" {
  description = "Cloud Scheduler HTTP attempt deadline (max wait for the endpoint)."
  type        = string
  default     = "320s"
}

# ---- Cloud Tasks (async ingest queue + DLQ) ----
variable "tasks_queue_name" {
  description = "Cloud Tasks queue name for async ingest."
  type        = string
  default     = "cia-ingest"
}

variable "tasks_dlq_name" {
  description = "Cloud Tasks dead-letter queue name."
  type        = string
  default     = "cia-ingest-dlq"
}

variable "tasks_max_dispatches_per_second" {
  description = "Max task dispatch rate."
  type        = number
  default     = 5
}

variable "tasks_max_concurrent_dispatches" {
  description = "Max concurrent task dispatches."
  type        = number
  default     = 10
}

variable "tasks_max_attempts" {
  description = "Max delivery attempts before a task is dead-lettered (routed to DLQ, never dropped)."
  type        = number
  default     = 5
}
