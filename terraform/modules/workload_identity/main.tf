# workload_identity — keyless CI/CD. A Workload Identity Pool + a GitHub OIDC provider let GitHub
# Actions running in ONE repository mint short-lived Google credentials to impersonate cia-deployer.
#
# NO service-account keys are ever created. The attribute_condition pins the trust to the exact
# repository so no other repo (or fork) can assume the deployer identity.

terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 5.40, < 7.0"
    }
  }
}

resource "google_iam_workload_identity_pool" "github" {
  project                   = var.project_id
  workload_identity_pool_id = var.pool_id
  display_name              = "GitHub Actions"
  description               = "Keyless OIDC federation for CIA CI/CD (deploys via cia-deployer)."
}

resource "google_iam_workload_identity_pool_provider" "github" {
  project                            = var.project_id
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = var.provider_id
  display_name                       = "GitHub Actions OIDC"
  description                        = "Trusts GitHub Actions OIDC tokens from ${var.github_repo} only."

  # Map GitHub OIDC claims to Google STS attributes. attribute.repository is what the condition
  # (and the SA impersonation binding) filter on.
  attribute_mapping = {
    "google.subject"       = "assertion.sub"
    "attribute.repository" = "assertion.repository"
    "attribute.ref"        = "assertion.ref"
    "attribute.actor"      = "assertion.actor"
  }

  # HARD trust boundary: only tokens whose 'repository' claim equals the configured repo are
  # accepted. Without this, ANY GitHub repo's workflow could exchange a token against this pool.
  attribute_condition = "assertion.repository == '${var.github_repo}'"

  oidc {
    issuer_uri        = var.issuer_uri
    allowed_audiences = var.allowed_audiences
  }
}

# Let workflows from exactly this repo impersonate the deployer SA. The principalSet is scoped by
# the mapped attribute.repository, matching the provider's attribute_condition — belt and braces.
resource "google_service_account_iam_member" "deployer_wif" {
  service_account_id = var.deployer_sa_id
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.repository/${var.github_repo}"
}
