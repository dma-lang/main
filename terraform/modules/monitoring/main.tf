# monitoring — uptime check on /healthz, a log-based error metric with an alert, and a monthly
# budget/cost alert at the configured threshold (default 80%).

terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 5.40, < 7.0"
    }
  }
}

# ---------------------------------------------------------------------------
# Notification channel (email)
# ---------------------------------------------------------------------------

resource "google_monitoring_notification_channel" "email" {
  project      = var.project_id
  display_name = "CIA on-call email"
  type         = "email"

  labels = {
    email_address = var.alert_email
  }
}

# ---------------------------------------------------------------------------
# Uptime check on the public /healthz
# ---------------------------------------------------------------------------

resource "google_monitoring_uptime_check_config" "healthz" {
  project      = var.project_id
  display_name = "CIA /healthz uptime"
  timeout      = "10s"
  period       = var.uptime_period

  http_check {
    path         = var.healthz_path
    port         = 443
    use_ssl      = true
    validate_ssl = true
  }

  monitored_resource {
    type = "uptime_url"
    labels = {
      project_id = var.project_id
      host       = var.service_host
    }
  }

  # Confirm the app reports healthy, not merely that the port answers.
  content_matchers {
    content = "\"status\":\"ok\""
    matcher = "CONTAINS_STRING"
  }
}

resource "google_monitoring_alert_policy" "uptime" {
  project      = var.project_id
  display_name = "CIA /healthz uptime failing"
  combiner     = "OR"

  conditions {
    display_name = "healthz uptime check not passing"

    condition_threshold {
      filter          = "metric.type=\"monitoring.googleapis.com/uptime_check/check_passed\" AND resource.type=\"uptime_url\" AND metric.label.check_id=\"${google_monitoring_uptime_check_config.healthz.uptime_check_id}\""
      duration        = "300s"
      comparison      = "COMPARISON_LT"
      threshold_value = 1

      aggregations {
        alignment_period     = "300s"
        per_series_aligner   = "ALIGN_FRACTION_TRUE"
        cross_series_reducer = "REDUCE_MEAN"
        group_by_fields      = ["resource.label.host"]
      }
    }
  }

  notification_channels = [google_monitoring_notification_channel.email.id]
}

# ---------------------------------------------------------------------------
# Log-based error metric + alert (counts ERROR+ log entries from the service)
# ---------------------------------------------------------------------------

resource "google_logging_metric" "app_errors" {
  project = var.project_id
  name    = "cia_app_errors"
  filter  = "resource.type=\"cloud_run_revision\" AND severity>=ERROR"

  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
    unit        = "1"
  }
}

resource "google_monitoring_alert_policy" "errors" {
  project      = var.project_id
  display_name = "CIA elevated error rate"
  combiner     = "OR"

  conditions {
    display_name = "app ERROR log rate high"

    condition_threshold {
      filter          = "metric.type=\"logging.googleapis.com/user/${google_logging_metric.app_errors.name}\" AND resource.type=\"cloud_run_revision\""
      duration        = "300s"
      comparison      = "COMPARISON_GT"
      threshold_value = 5

      aggregations {
        alignment_period   = "300s"
        per_series_aligner = "ALIGN_SUM"
      }
    }
  }

  notification_channels = [google_monitoring_notification_channel.email.id]
}

# ---------------------------------------------------------------------------
# Monthly budget / cost alert (80% by default). Gated by create_budget because it needs a billing
# account and the billingbudgets API — the app SAs never get billing roles.
# ---------------------------------------------------------------------------

resource "google_billing_budget" "monthly" {
  count = var.create_budget ? 1 : 0

  billing_account = var.billing_account
  display_name    = "CIA monthly budget"

  budget_filter {
    projects = ["projects/${var.project_id}"]
  }

  amount {
    specified_amount {
      currency_code = var.budget_currency
      units         = tostring(var.monthly_budget_amount)
    }
  }

  threshold_rules {
    threshold_percent = var.budget_threshold_percent
    spend_basis       = "CURRENT_SPEND"
  }

  # Also alert at 100% (forecasted) so the run-up is visible before overspend.
  threshold_rules {
    threshold_percent = 1.0
    spend_basis       = "FORECASTED_SPEND"
  }

  all_updates_rule {
    monitoring_notification_channels = [google_monitoring_notification_channel.email.id]
    disable_default_iam_recipients   = false
  }
}
