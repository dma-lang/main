output "identity_platform_managed" {
  description = "Whether Terraform is managing the Identity Platform config in this apply."
  value       = var.manage_identity_platform_config
}
