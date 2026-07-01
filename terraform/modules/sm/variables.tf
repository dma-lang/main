variable "project_id" {
  description = "GCP project ID."
  type        = string
}

variable "region" {
  description = "Region for the secret's user-managed replica."
  type        = string
  default     = "us-central1"
}

variable "secret_ids" {
  description = "Map of logical name => Secret Manager secret ID. Values are added OUT-OF-BAND (never in Terraform)."
  type        = map(string)
  default = {
    database_url        = "database-url"                 # full SQLAlchemy DATABASE_URL (private IP)
    db_password         = "db-password"                  # DB user password (if using URL-less path)
    hmac_export_key     = "hmac-export-key"              # HMAC key for signed exports (F12)
    oauth_client_id     = "firebase-oauth-client-id"     # Google OAuth client id
    oauth_client_secret = "firebase-oauth-client-secret" # Google OAuth client secret
  }
}

variable "accessor_members" {
  description = "IAM members granted roles/secretmanager.secretAccessor on EVERY secret (cia-run + cia-jobs only)."
  type        = list(string)
}
