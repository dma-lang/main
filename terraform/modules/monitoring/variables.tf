variable "project_id" {
  description = "GCP project ID."
  type        = string
}

variable "service_host" {
  description = "Hostname (no scheme) of the Cloud Run service for the uptime check, e.g. cia-123456789.us-central1.run.app."
  type        = string
}

variable "healthz_path" {
  description = "Path the uptime check probes."
  type        = string
  default     = "/healthz"
}

variable "uptime_period" {
  description = "How often the uptime check runs."
  type        = string
  default     = "300s"
}

variable "alert_email" {
  description = "Email address for the alert + budget notification channel."
  type        = string
}

variable "billing_account" {
  description = "Billing account ID (XXXXXX-XXXXXX-XXXXXX) the budget is attached to. Required for the budget resource."
  type        = string
  default     = ""
}

variable "monthly_budget_amount" {
  description = "Monthly budget amount (currency units) for the cost alert."
  type        = number
  default     = 2000
}

variable "budget_currency" {
  description = "Currency code for the budget amount."
  type        = string
  default     = "USD"
}

variable "budget_threshold_percent" {
  description = "Fraction of budget at which to alert (0.8 = 80%)."
  type        = number
  default     = 0.8
}

variable "create_budget" {
  description = "Whether to create the billing budget. Needs billing_account set and billingbudgets.googleapis.com enabled."
  type        = bool
  default     = false
}
