variable "project_id" {
  description = "GCP project ID that owns the Workload Identity pool."
  type        = string
}

variable "pool_id" {
  description = "Workload Identity Pool ID."
  type        = string
  default     = "github-actions-pool"
}

variable "provider_id" {
  description = "Workload Identity Pool OIDC provider ID."
  type        = string
  default     = "github-actions-oidc"
}

variable "github_repo" {
  description = "The single GitHub repository allowed to impersonate the deployer SA, as 'owner/repo' (e.g. dma-lang/main)."
  type        = string
}

variable "deployer_sa_id" {
  description = "Fully-qualified resource name of the deployer service account to impersonate (from iam_service_accounts)."
  type        = string
}

variable "issuer_uri" {
  description = "OIDC issuer for GitHub Actions tokens."
  type        = string
  default     = "https://token.actions.githubusercontent.com"
}

variable "allowed_audiences" {
  description = "Optional explicit OIDC audiences. Empty => the provider accepts the default STS audience (recommended)."
  type        = list(string)
  default     = []
}
