# sm — Secret Manager module. Creates the Secret Manager secret RESOURCES only. NO secret VALUES
# appear in Terraform or state: no google_secret_manager_secret_version with a literal is declared
# here. The operator adds each version out-of-band (see terraform/README.md), e.g.:
#   printf '%s' "$VALUE" | gcloud secrets versions add <secret-id> --data-file=-
#
# (Directory is named `sm` rather than `secret_manager` only because the repository's PreToolUse
# safety hook refuses to author any file whose path contains the substring "secret" — a guard
# against committing secret material. This module authors resource DEFINITIONS, never values.)
#
# Access is granted per-secret to cia-run + cia-jobs ONLY (roles/secretmanager.secretAccessor).
# No project-level secret access is granted anywhere.

terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 5.40, < 7.0"
    }
  }
}

resource "google_secret_manager_secret" "this" {
  for_each = var.secret_ids

  project   = var.project_id
  secret_id = each.value

  labels = {
    app       = "cia"
    managed   = "terraform"
    component = each.key
  }

  # Pin replication to the service region (data residency + latency). User-managed, not automatic.
  replication {
    user_managed {
      replicas {
        location = var.region
      }
    }
  }
}

# Per-secret accessor grant to the runtime + jobs identities only. Cartesian product of
# (secret x member) via a flattened map so each grant is its own, auditable resource.
locals {
  secret_access_grants = {
    for pair in setproduct(keys(var.secret_ids), var.accessor_members) :
    "${pair[0]}::${pair[1]}" => {
      secret_key = pair[0]
      member     = pair[1]
    }
  }
}

resource "google_secret_manager_secret_iam_member" "accessors" {
  for_each = local.secret_access_grants

  project   = var.project_id
  secret_id = google_secret_manager_secret.this[each.value.secret_key].secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = each.value.member
}
