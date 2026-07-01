output "bucket_names" {
  description = "Map of logical name => bucket name."
  value       = { for k, b in google_storage_bucket.this : k => b.name }
}

output "bucket_urls" {
  description = "Map of logical name => gs:// URL."
  value       = { for k, b in google_storage_bucket.this : k => b.url }
}
