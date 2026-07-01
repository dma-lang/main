output "instance_name" {
  description = "Cloud SQL instance name."
  value       = google_sql_database_instance.pg.name
}

output "connection_name" {
  description = "Instance connection name (project:region:instance) — used by the Cloud SQL connector / socket path."
  value       = google_sql_database_instance.pg.connection_name
}

output "private_ip_address" {
  description = "Private IP of the Cloud SQL instance (reachable only inside the VPC)."
  value       = google_sql_database_instance.pg.private_ip_address
}

output "database_name" {
  description = "Application database name."
  value       = google_sql_database.app.name
}

output "database_user" {
  description = "Application database user name."
  value       = google_sql_user.app.name
}

output "vpc_network_id" {
  description = "The VPC network ID (for reference / peering)."
  value       = google_compute_network.vpc.id
}

output "vpc_connector_id" {
  description = "Serverless VPC Access connector ID — attach to Cloud Run for private DB egress."
  value       = google_vpc_access_connector.connector.id
}

output "vpc_connector_name" {
  description = "Serverless VPC Access connector short name."
  value       = google_vpc_access_connector.connector.name
}
