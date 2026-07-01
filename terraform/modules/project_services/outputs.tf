output "enabled_apis" {
  description = "The set of APIs enabled by this module (service identifiers)."
  value       = [for s in google_project_service.apis : s.service]
}

# Downstream modules depend_on this so Terraform provisions resources only after their API is on.
output "services" {
  description = "The google_project_service resources keyed by API, for explicit depends_on wiring."
  value       = google_project_service.apis
}
