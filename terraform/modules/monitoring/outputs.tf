output "notification_channel_id" {
  description = "Resource id of the email notification channel."
  value       = google_monitoring_notification_channel.email.id
}

output "uptime_check_id" {
  description = "The uptime check config id."
  value       = google_monitoring_uptime_check_config.healthz.uptime_check_id
}

output "error_metric_name" {
  description = "The log-based error metric name."
  value       = google_logging_metric.app_errors.name
}
