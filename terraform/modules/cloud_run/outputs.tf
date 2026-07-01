output "service_name" {
  description = "Cloud Run service name."
  value       = google_cloud_run_v2_service.service.name
}

output "service_uri" {
  description = "The Cloud Run-assigned service URL."
  value       = google_cloud_run_v2_service.service.uri
}

output "public_base_url" {
  description = "The canonical base URL wired into the service (PUBLIC_BASE_URL / OAuth pin)."
  value       = local.public_base_url
}

output "migrate_job_name" {
  description = "Name of the one-shot migration Cloud Run Job."
  value       = google_cloud_run_v2_job.migrate.name
}

output "scheduler_job_names" {
  description = "Names of the created Cloud Scheduler jobs."
  value       = [for j in google_cloud_scheduler_job.jobs : j.name]
}

output "tasks_queue_name" {
  description = "Cloud Tasks ingest queue name."
  value       = google_cloud_tasks_queue.ingest.name
}

output "tasks_dlq_name" {
  description = "Cloud Tasks dead-letter queue name."
  value       = google_cloud_tasks_queue.dlq.name
}
