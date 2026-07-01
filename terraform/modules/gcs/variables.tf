variable "project_id" {
  description = "GCP project ID."
  type        = string
}

variable "region" {
  description = "Location for the buckets."
  type        = string
  default     = "us-central1"
}

variable "name_prefix" {
  description = "Prefix for bucket names (bucket names are globally unique). Typically '<project_id>-cia'."
  type        = string
}

variable "object_user_members" {
  description = "IAM members granted roles/storage.objectUser on EVERY bucket (typically cia-run + cia-jobs)."
  type        = list(string)
  default     = []
}

variable "raw_uploads_retention_days" {
  description = "Days after which raw upload objects are deleted."
  type        = number
  default     = 90
}

variable "exports_retention_days" {
  description = "Days after which signed export objects are deleted."
  type        = number
  default     = 365
}

variable "noncurrent_version_retention_days" {
  description = "Days to keep noncurrent (versioned) object generations before deletion."
  type        = number
  default     = 30
}

variable "force_destroy" {
  description = "Allow Terraform to delete non-empty buckets on destroy. Keep false in prod."
  type        = bool
  default     = false
}
