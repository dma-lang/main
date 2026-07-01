output "run_sa_email" {
  description = "Email of the Cloud Run runtime service account (cia-run)."
  value       = google_service_account.run.email
}

output "run_sa_id" {
  description = "Fully-qualified resource name of cia-run (projects/.../serviceAccounts/...)."
  value       = google_service_account.run.name
}

output "jobs_sa_email" {
  description = "Email of the Cloud Run Jobs service account (cia-jobs)."
  value       = google_service_account.jobs.email
}

output "jobs_sa_id" {
  description = "Fully-qualified resource name of cia-jobs."
  value       = google_service_account.jobs.name
}

output "scheduler_sa_email" {
  description = "Email of the Cloud Scheduler invoker service account (cia-scheduler)."
  value       = google_service_account.scheduler.email
}

output "deployer_sa_email" {
  description = "Email of the CI/CD deployer service account (cia-deployer)."
  value       = google_service_account.deployer.email
}

output "deployer_sa_id" {
  description = "Fully-qualified resource name of cia-deployer (target for the WIF impersonation binding)."
  value       = google_service_account.deployer.name
}
