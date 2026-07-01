# ---------------------------------------------------------------------------
# Core project / location
# ---------------------------------------------------------------------------

variable "project_id" {
  description = "GCP project ID that hosts CIA."
  type        = string
  default     = "digital-maturity-assessor"
}

variable "project_number" {
  description = "GCP project NUMBER. Used to construct the deterministic run.app URL and some IAM members. Find it with: gcloud projects describe <project_id> --format='value(projectNumber)'."
  type        = string
}

variable "region" {
  description = "Primary region for all regional resources."
  type        = string
  default     = "us-central1"
}

variable "state_bucket" {
  description = "GCS bucket holding Terraform remote state (also supplied via -backend-config at init). Documented here for reference/outputs."
  type        = string
}

# ---------------------------------------------------------------------------
# CI/CD (Workload Identity Federation)
# ---------------------------------------------------------------------------

variable "github_repo" {
  description = "The single GitHub repository allowed to deploy, as 'owner/repo' (e.g. dma-lang/main)."
  type        = string
  default     = "dma-lang/main"
}

# ---------------------------------------------------------------------------
# Cloud Run service
# ---------------------------------------------------------------------------

variable "image_digest" {
  description = "FULL container image reference pinned by digest (…/cia@sha256:…). Deploys are by digest only. A placeholder public image is fine for the first apply; the deploy pipeline replaces the running image."
  type        = string
}

variable "service_base_url" {
  description = "Canonical public URL of the service (pins the OAuth round-trip → PUBLIC_BASE_URL). If empty, the module derives the deterministic run.app URL from service name + project number."
  type        = string
  default     = ""
}

variable "llm_mode" {
  description = "LLM_MODE for the service: 'live' (Vertex AI via ADC) or 'hermetic'."
  type        = string
  default     = "live"
}

variable "auth_mode" {
  description = "AUTH_MODE: 'live' (fails closed on @zennify.com). Never 'dev' in prod."
  type        = string
  default     = "live"
}

variable "oauth_hosted_domain" {
  description = "Google Workspace hosted domain sign-in is restricted to."
  type        = string
  default     = "zennify.com"
}

variable "ingress" {
  description = "Cloud Run ingress: 'all', 'internal', or 'internal-and-cloud-load-balancing'."
  type        = string
  default     = "all"
}

variable "min_instances" {
  description = "Minimum Cloud Run instances (>= 2)."
  type        = number
  default     = 2
}

variable "max_instances" {
  description = "Maximum Cloud Run instances. Keep (max_instances * per-instance DB pool) under the Cloud SQL connection budget."
  type        = number
  default     = 10
}

variable "concurrency" {
  description = "Max concurrent requests per instance."
  type        = number
  default     = 80
}

# ---------------------------------------------------------------------------
# Cloud SQL
# ---------------------------------------------------------------------------

variable "db_tier" {
  description = "Cloud SQL machine tier."
  type        = string
  default     = "db-custom-2-7680"
}

variable "db_availability_type" {
  description = "REGIONAL (HA) or ZONAL."
  type        = string
  default     = "REGIONAL"
}

variable "db_name" {
  description = "Application database name."
  type        = string
  default     = "cia"
}

variable "db_user" {
  description = "Application database user."
  type        = string
  default     = "cia_app"
}

# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------

variable "scheduler_target_version" {
  description = "Catalogue version the scheduled admin endpoints target (e.g. 'v7' or 'active')."
  type        = string
  default     = "active"
}

# ---------------------------------------------------------------------------
# Monitoring / budget
# ---------------------------------------------------------------------------

variable "alert_email" {
  description = "Email for uptime/error/budget alerts."
  type        = string
}

variable "billing_account" {
  description = "Billing account ID for the budget (XXXXXX-XXXXXX-XXXXXX). Leave empty to skip the budget."
  type        = string
  default     = ""
}

variable "monthly_budget" {
  description = "Monthly budget amount (USD) for the cost alert (alerts at 80%)."
  type        = number
  default     = 2000
}

variable "create_budget" {
  description = "Whether to create the billing budget (needs billing_account + billingbudgets API)."
  type        = bool
  default     = false
}

# ---------------------------------------------------------------------------
# Firebase / Identity Platform
# ---------------------------------------------------------------------------

variable "manage_identity_platform_config" {
  description = "Manage Identity Platform authorized_domains via TF (requires Identity Platform initialized first — see README)."
  type        = bool
  default     = false
}
