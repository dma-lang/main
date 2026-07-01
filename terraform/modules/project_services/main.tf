# project_services — enable exactly the APIs the CIA platform needs, one resource per API.
#
# disable_on_destroy defaults to false (see variables.tf): the project may be shared, and
# tearing down this Terraform must never yank an API out from under another workload. Each API
# is its own resource so the plan is explicit and drift is per-API.

terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 5.40, < 7.0"
    }
  }
}

resource "google_project_service" "apis" {
  for_each = toset(var.activate_apis)

  project = var.project_id
  service = each.value

  disable_dependent_services = var.disable_dependent_services
  disable_on_destroy         = var.disable_on_destroy
}
