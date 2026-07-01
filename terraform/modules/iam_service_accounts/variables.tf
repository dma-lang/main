variable "project_id" {
  description = "GCP project ID."
  type        = string
}

variable "sa_run_name" {
  description = "Account ID (local part) of the Cloud Run runtime service account."
  type        = string
  default     = "cia-run"
}

variable "sa_jobs_name" {
  description = "Account ID of the Cloud Run Jobs (migration) service account."
  type        = string
  default     = "cia-jobs"
}

variable "sa_scheduler_name" {
  description = "Account ID of the Cloud Scheduler invoker service account."
  type        = string
  default     = "cia-scheduler"
}

variable "sa_deployer_name" {
  description = "Account ID of the CI/CD deployer service account (impersonated via WIF, no keys)."
  type        = string
  default     = "cia-deployer"
}
