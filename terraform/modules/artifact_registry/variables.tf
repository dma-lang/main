variable "project_id" {
  description = "GCP project ID."
  type        = string
}

variable "region" {
  description = "Region (location) for the Artifact Registry repository."
  type        = string
  default     = "us-central1"
}

variable "repository_id" {
  description = "Artifact Registry Docker repository ID (matches REPO_AR in the deploy script)."
  type        = string
  default     = "cia"
}

variable "writer_members" {
  description = "IAM members granted roles/artifactregistry.writer (push). Typically cia-deployer only."
  type        = list(string)
  default     = []
}

variable "reader_members" {
  description = "IAM members granted roles/artifactregistry.reader (pull). Cloud Run runtime + jobs SAs pull by digest."
  type        = list(string)
  default     = []
}

variable "immutable_tags" {
  description = "Reject overwriting an existing tag. Deploys are by digest, so tags are informational and immutable."
  type        = bool
  default     = true
}

variable "keep_recent_versions" {
  description = "Cleanup policy: number of most-recent image versions to keep."
  type        = number
  default     = 20
}
