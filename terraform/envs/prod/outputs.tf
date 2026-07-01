# ---------------------------------------------------------------------------
# Service accounts (SA -> role matrix is documented in terraform/README.md)
# ---------------------------------------------------------------------------

output "run_sa_email" {
  description = "cia-run service account email."
  value       = module.iam_service_accounts.run_sa_email
}

output "jobs_sa_email" {
  description = "cia-jobs service account email."
  value       = module.iam_service_accounts.jobs_sa_email
}

output "scheduler_sa_email" {
  description = "cia-scheduler service account email."
  value       = module.iam_service_accounts.scheduler_sa_email
}

output "deployer_sa_email" {
  description = "cia-deployer service account email (impersonated via WIF)."
  value       = module.iam_service_accounts.deployer_sa_email
}

# ---------------------------------------------------------------------------
# Workload Identity Federation (feed these into the GitHub Actions deploy workflow)
# ---------------------------------------------------------------------------

output "wif_provider_name" {
  description = "Full WIF provider resource name -> google-github-actions/auth 'workload_identity_provider'."
  value       = module.workload_identity.provider_name
}

output "wif_pool_name" {
  description = "Full WIF pool resource name."
  value       = module.workload_identity.pool_name
}

# ---------------------------------------------------------------------------
# Cloud Run
# ---------------------------------------------------------------------------

output "service_uri" {
  description = "Cloud Run-assigned service URL."
  value       = module.cloud_run.service_uri
}

output "public_base_url" {
  description = "Canonical base URL wired into the service (PUBLIC_BASE_URL / OAuth pin)."
  value       = module.cloud_run.public_base_url
}

output "migrate_job_name" {
  description = "One-shot migration Cloud Run Job name (executed by the deploy pipeline BEFORE traffic shifts)."
  value       = module.cloud_run.migrate_job_name
}

output "scheduler_job_names" {
  description = "Created Cloud Scheduler job names."
  value       = module.cloud_run.scheduler_job_names
}

output "tasks_queue_name" {
  description = "Cloud Tasks ingest queue name."
  value       = module.cloud_run.tasks_queue_name
}

output "tasks_dlq_name" {
  description = "Cloud Tasks dead-letter queue name."
  value       = module.cloud_run.tasks_dlq_name
}

# ---------------------------------------------------------------------------
# Data plane
# ---------------------------------------------------------------------------

output "cloudsql_connection_name" {
  description = "Cloud SQL instance connection name (project:region:instance)."
  value       = module.cloudsql.connection_name
}

output "cloudsql_private_ip" {
  description = "Private IP of Cloud SQL (VPC-internal only; no public IP)."
  value       = module.cloudsql.private_ip_address
}

output "artifact_registry_url" {
  description = "Base image path for pushes/deploys (append '/cia@<digest>')."
  value       = module.artifact_registry.repository_url
}

output "gcs_bucket_names" {
  description = "Map of logical bucket name => bucket name."
  value       = module.gcs.bucket_names
}

output "secret_ids" {
  description = "Map of logical secret name => Secret Manager secret_id (add VALUES out-of-band)."
  value       = module.secret_manager.secret_ids
}
