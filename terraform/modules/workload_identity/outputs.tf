output "pool_name" {
  description = "Full resource name of the Workload Identity Pool."
  value       = google_iam_workload_identity_pool.github.name
}

output "provider_name" {
  description = "Full resource name of the OIDC provider — pass to the GitHub Action 'workload_identity_provider' input."
  value       = google_iam_workload_identity_pool_provider.github.name
}

output "provider_id" {
  description = "The short provider ID."
  value       = google_iam_workload_identity_pool_provider.github.workload_identity_pool_provider_id
}
