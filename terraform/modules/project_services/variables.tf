variable "project_id" {
  description = "GCP project ID that hosts the CIA service."
  type        = string
}

variable "activate_apis" {
  description = "The set of Google Cloud APIs to enable on the project."
  type        = list(string)
  default = [
    "run.googleapis.com",                 # Cloud Run service + Jobs
    "sqladmin.googleapis.com",            # Cloud SQL (Postgres 16)
    "secretmanager.googleapis.com",       # Secret Manager (DB/HMAC/OAuth secrets)
    "aiplatform.googleapis.com",          # Vertex AI (Gemini via ADC, no keys)
    "artifactregistry.googleapis.com",    # Docker image registry (deploy by digest)
    "cloudscheduler.googleapis.com",      # Scheduled ingest/intelligence cadences
    "cloudtasks.googleapis.com",          # Async ingest queue + DLQ
    "storage.googleapis.com",             # GCS buckets (uploads/snapshots/exports/evidence)
    "iam.googleapis.com",                 # Service accounts + IAM
    "iamcredentials.googleapis.com",      # OIDC token minting for WIF + Scheduler OIDC
    "identitytoolkit.googleapis.com",     # Firebase Auth / Identity Platform
    "compute.googleapis.com",             # VPC / network primitives for private IP
    "servicenetworking.googleapis.com",   # Private Services Access (private Cloud SQL)
    "vpcaccess.googleapis.com",           # Serverless VPC Access connector
    "monitoring.googleapis.com",          # Uptime checks, alerts, dashboards
    "logging.googleapis.com",             # Log sinks + log-based metrics
    "cloudresourcemanager.googleapis.com" # Project/IAM policy management (TF dependency)
  ]
}

variable "disable_dependent_services" {
  description = "Whether to also disable services that depend on the given service on destroy."
  type        = bool
  default     = false
}

variable "disable_on_destroy" {
  description = "Whether to disable the APIs when this Terraform resource is destroyed. Kept false so a destroy never breaks a project shared with other workloads."
  type        = bool
  default     = false
}
