variable "project_id" {
  description = "GCP project ID (same project hosts Identity Platform / Firebase Auth)."
  type        = string
}

variable "authorized_domains" {
  description = "Domains allowed to complete the OAuth redirect (the run.app host + any custom domain). NOT the sign-in email restriction — that is enforced in-app by GOOGLE_OAUTH_HOSTED_DOMAIN."
  type        = list(string)
  default     = []
}

variable "manage_identity_platform_config" {
  description = "Whether to manage the google_identity_platform_config resource. Requires Identity Platform to be initialized on the project first (a one-time console/manual step)."
  type        = bool
  default     = false
}
