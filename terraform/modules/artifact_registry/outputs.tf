output "repository_id" {
  description = "Artifact Registry repository ID."
  value       = google_artifact_registry_repository.docker.repository_id
}

output "repository_url" {
  description = "Base image path: <region>-docker.pkg.dev/<project>/<repo>. Append '/<image>@<digest>'."
  value       = "${google_artifact_registry_repository.docker.location}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.docker.repository_id}"
}
