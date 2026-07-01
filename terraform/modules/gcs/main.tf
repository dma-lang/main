# gcs — four private buckets for the CIA data lifecycle.
#
#   raw_uploads   — operator-uploaded raw sources (SOWs etc.) before DLP redaction/ingest
#   snapshots     — per-version data-plane snapshots (cat_<v> exports)
#   exports       — signed exports (F12); HMAC-signed, time-limited
#   evidence      — evidence bodies backing AI conclusions (provenance)
#
# EVERY bucket is locked down identically:
#   * uniform_bucket_level_access = true   (no per-object ACLs; IAM only)
#   * public_access_prevention   = "enforced"  (can NEVER be made public, even by mistake)
#   * versioning enabled + lifecycle rules (retention + noncurrent cleanup)
# cia-run/cia-jobs get roles/storage.objectUser PER BUCKET (no project-level storage role).

terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 5.40, < 7.0"
    }
  }
}

locals {
  # logical key => { suffix, retention_days (0 = no age-delete rule) }
  buckets = {
    raw_uploads = { suffix = "raw-uploads", retention_days = var.raw_uploads_retention_days }
    snapshots   = { suffix = "snapshots", retention_days = 0 }
    exports     = { suffix = "exports", retention_days = var.exports_retention_days }
    evidence    = { suffix = "evidence", retention_days = 0 }
  }
}

resource "google_storage_bucket" "this" {
  for_each = local.buckets

  project                     = var.project_id
  name                        = "${var.name_prefix}-${each.value.suffix}"
  location                    = var.region
  force_destroy               = var.force_destroy
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"

  versioning {
    enabled = true
  }

  # Age-based deletion of CURRENT objects (only for buckets that set retention_days > 0).
  dynamic "lifecycle_rule" {
    for_each = each.value.retention_days > 0 ? [1] : []
    content {
      condition {
        age = each.value.retention_days
      }
      action {
        type = "Delete"
      }
    }
  }

  # Always prune old NONCURRENT versions so versioning does not grow unbounded.
  lifecycle_rule {
    condition {
      age                = var.noncurrent_version_retention_days
      with_state         = "ARCHIVED"
      num_newer_versions = 3
    }
    action {
      type = "Delete"
    }
  }

  labels = {
    app       = "cia"
    managed   = "terraform"
    component = each.key
  }
}

# Per-bucket objectUser for the runtime + jobs identities. Flatten (bucket x member).
locals {
  bucket_grants = {
    for pair in setproduct(keys(local.buckets), var.object_user_members) :
    "${pair[0]}::${pair[1]}" => {
      bucket_key = pair[0]
      member     = pair[1]
    }
  }
}

resource "google_storage_bucket_iam_member" "object_users" {
  for_each = local.bucket_grants

  bucket = google_storage_bucket.this[each.value.bucket_key].name
  role   = "roles/storage.objectUser"
  member = each.value.member
}
