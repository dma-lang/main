variable "project_id" {
  description = "GCP project ID."
  type        = string
}

variable "region" {
  description = "Region for the Cloud SQL instance and VPC connector."
  type        = string
  default     = "us-central1"
}

variable "instance_name" {
  description = "Cloud SQL instance name."
  type        = string
  default     = "cia-pg"
}

variable "database_version" {
  description = "Cloud SQL database engine version (Postgres 16)."
  type        = string
  default     = "POSTGRES_16"
}

variable "tier" {
  description = "Cloud SQL machine tier (e.g. db-custom-2-7680 = 2 vCPU / 7.5GB). Right-size to load."
  type        = string
  default     = "db-custom-2-7680"
}

variable "disk_size_gb" {
  description = "Initial data disk size in GB (autoresize is enabled)."
  type        = number
  default     = 20
}

variable "disk_type" {
  description = "Data disk type."
  type        = string
  default     = "PD_SSD"
}

variable "availability_type" {
  description = "REGIONAL (HA, failover replica) or ZONAL. Prod defaults to REGIONAL."
  type        = string
  default     = "REGIONAL"
}

variable "database_name" {
  description = "Application database name."
  type        = string
  default     = "cia"
}

variable "database_user" {
  description = "Application database user (password comes from Secret Manager, set out-of-band)."
  type        = string
  default     = "cia_app"
}

variable "deletion_protection" {
  description = "Guard against accidental instance deletion. Keep true in prod."
  type        = bool
  default     = true
}

variable "backup_start_time" {
  description = "Daily automated backup start time (HH:MM, UTC)."
  type        = string
  default     = "03:00"
}

variable "backup_retention_count" {
  description = "Number of automated backups to retain."
  type        = number
  default     = 30
}

variable "transaction_log_retention_days" {
  description = "Days of transaction logs to retain for point-in-time recovery (PITR)."
  type        = number
  default     = 7
}

variable "network_name" {
  description = "Name of the VPC network to create for private connectivity."
  type        = string
  default     = "cia-vpc"
}

variable "private_ip_range_name" {
  description = "Name of the reserved global range used for Private Services Access."
  type        = string
  default     = "cia-psa-range"
}

variable "private_ip_prefix_length" {
  description = "Prefix length of the PSA reserved range (a /16 gives Google room to allocate)."
  type        = number
  default     = 16
}

variable "connector_name" {
  description = "Serverless VPC Access connector name (max 25 chars)."
  type        = string
  default     = "cia-connector"
}

variable "connector_ip_cidr_range" {
  description = "The /28 the VPC connector uses. Must not overlap other subnets in the VPC."
  type        = string
  default     = "10.8.0.0/28"
}

variable "connector_min_instances" {
  description = "Minimum VPC connector instances."
  type        = number
  default     = 2
}

variable "connector_max_instances" {
  description = "Maximum VPC connector instances."
  type        = number
  default     = 4
}

variable "connector_machine_type" {
  description = "VPC connector machine type."
  type        = string
  default     = "e2-micro"
}

variable "query_insights_enabled" {
  description = "Enable Cloud SQL Query Insights."
  type        = bool
  default     = true
}
