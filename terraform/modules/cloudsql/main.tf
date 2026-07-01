# cloudsql — PostgreSQL 16 on PRIVATE IP only.
#
# Network topology:
#   VPC (cia-vpc) ──▶ Private Services Access (reserved range + servicenetworking peering)
#                 └─▶ Serverless VPC Access connector ──▶ Cloud Run reaches the DB's private IP
#
# Safeguards baked in:
#   * ipv4_enabled = false  → NO public IP on the database (private only).
#   * IAM database authentication enabled (cloudsql.iam_authentication = on).
#   * Automated backups + binary logging → point-in-time recovery (PITR).
#   * deletion_protection (both the API flag and the resource meta lifecycle).
#
# NOTE: the pgvector extension is NOT created here. The application's Alembic migration
# (control.*) runs `CREATE EXTENSION IF NOT EXISTS vector` as part of the schema, per CLAUDE.md
# safeguard #5 (migrations run in the cia-migrate Job, never in Terraform, never on app startup).

terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 5.40, < 7.0"
    }
    random = {
      source  = "hashicorp/random"
      version = ">= 3.5"
    }
  }
}

# ---------------------------------------------------------------------------
# Private network for the DB (VPC + Private Services Access + VPC connector)
# ---------------------------------------------------------------------------

resource "google_compute_network" "vpc" {
  project                 = var.project_id
  name                    = var.network_name
  auto_create_subnetworks = false
  description             = "Private network for CIA Cloud SQL + serverless VPC access."
}

# Reserved range Google uses to allocate the private service (Cloud SQL) IPs.
resource "google_compute_global_address" "private_ip_range" {
  project       = var.project_id
  name          = var.private_ip_range_name
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  prefix_length = var.private_ip_prefix_length
  network       = google_compute_network.vpc.id
}

# The servicenetworking peering that makes the Cloud SQL private IP reachable inside the VPC.
resource "google_service_networking_connection" "private_vpc" {
  network                 = google_compute_network.vpc.id
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.private_ip_range.name]

  # Let Terraform tear the peering down cleanly on destroy.
  deletion_policy = "ABANDON"
}

# Serverless VPC Access connector: Cloud Run egresses through this to reach the private DB IP.
resource "google_vpc_access_connector" "connector" {
  project        = var.project_id
  name           = var.connector_name
  region         = var.region
  ip_cidr_range  = var.connector_ip_cidr_range
  network        = google_compute_network.vpc.name
  min_instances  = var.connector_min_instances
  max_instances  = var.connector_max_instances
  machine_type   = var.connector_machine_type
}

# ---------------------------------------------------------------------------
# The Cloud SQL instance (PRIVATE IP, IAM auth, backups + PITR, deletion protection)
# ---------------------------------------------------------------------------

resource "google_sql_database_instance" "pg" {
  project             = var.project_id
  name                = var.instance_name
  region              = var.region
  database_version    = var.database_version
  deletion_protection = var.deletion_protection

  depends_on = [google_service_networking_connection.private_vpc]

  settings {
    tier                        = var.tier
    availability_type           = var.availability_type
    disk_size                   = var.disk_size_gb
    disk_type                   = var.disk_type
    disk_autoresize             = true
    deletion_protection_enabled = var.deletion_protection

    ip_configuration {
      ipv4_enabled                                  = false # NO public IP — private only.
      private_network                               = google_compute_network.vpc.id
      enable_private_path_for_google_cloud_services = true
      ssl_mode                                      = "ENCRYPTED_ONLY"
    }

    backup_configuration {
      enabled                        = true
      start_time                     = var.backup_start_time
      point_in_time_recovery_enabled = true # PITR via WAL archiving (Postgres); retention below
      transaction_log_retention_days = var.transaction_log_retention_days
      location                       = var.region

      backup_retention_settings {
        retained_backups = var.backup_retention_count
        retention_unit   = "COUNT"
      }
    }

    # IAM database authentication — no passwords in the connection path for IAM principals.
    database_flags {
      name  = "cloudsql.iam_authentication"
      value = "on"
    }

    insights_config {
      query_insights_enabled  = var.query_insights_enabled
      record_application_tags = false # never record app tags (avoid leaking identifiers)
      record_client_address   = false # no PII (client IPs) in Query Insights
    }

    maintenance_window {
      day          = 7 # Sunday
      hour         = 4
      update_track = "stable"
    }
  }

  lifecycle {
    prevent_destroy = true # belt-and-braces alongside deletion_protection
  }
}

resource "google_sql_database" "app" {
  project   = var.project_id
  name      = var.database_name
  instance  = google_sql_database_instance.pg.name
  charset   = "UTF8"
  collation = "en_US.UTF8"
}

# ---------------------------------------------------------------------------
# Application DB user.
# The password is NOT stored in Terraform state as a literal: it is generated and written into the
# Secret Manager 'db-password' secret out-of-band by the operator (see terraform/README.md). Here
# we create the user WITHOUT setting a plaintext password in HCL. The operator sets/rotates the
# password with `gcloud sql users set-password` and stores the same value in Secret Manager, so the
# secret and the DB stay in sync and no secret value ever lands in .tf or state.
#
# (Alternatively the app can authenticate as an IAM DB user; the password user is provisioned for
# the SQLAlchemy DATABASE_URL path the app uses today.)
# ---------------------------------------------------------------------------

resource "random_password" "db_bootstrap" {
  length  = 32
  special = false

  # This bootstrap value is only used to CREATE the user resource; the operator immediately rotates
  # it and stores the real value in Secret Manager. Rotating out-of-band does not cause drift here
  # because we ignore password changes below.
  #
  # SECURITY NOTE: `google_sql_user` requires a password at create time, so this bootstrap value
  # DOES transit Terraform state in plaintext (inherent to the resource type — not a leak in code).
  # Because of this the GCS remote-state bucket MUST be private + versioned + IAM-restricted (see
  # terraform/README.md). If you prefer ZERO password in state, provision the app identity as an IAM
  # database user instead (type = "CLOUD_IAM_SERVICE_ACCOUNT", no password) and connect via IAM auth;
  # the password user is kept here because the app's DATABASE_URL path uses it today.
  keepers = {
    instance = google_sql_database_instance.pg.name
  }
}

resource "google_sql_user" "app" {
  project  = var.project_id
  name     = var.database_user
  instance = google_sql_database_instance.pg.name
  password = random_password.db_bootstrap.result

  # The real password lives in Secret Manager and is rotated by the operator; ignore drift so
  # Terraform never resets it (and never needs the real value in state going forward).
  lifecycle {
    ignore_changes = [password]
  }
}
