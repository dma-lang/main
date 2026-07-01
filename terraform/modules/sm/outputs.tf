output "secret_ids" {
  description = "Map of logical name => created Secret Manager secret_id."
  value       = { for k, s in google_secret_manager_secret.this : k => s.secret_id }
}

output "secret_resource_ids" {
  description = "Map of logical name => full Secret Manager resource id (projects/.../secrets/...)."
  value       = { for k, s in google_secret_manager_secret.this : k => s.id }
}
