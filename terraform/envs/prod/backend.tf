# Remote state in GCS. The bucket must ALREADY EXIST (create it once, manually, with versioning
# enabled and public access prevention enforced — see terraform/README.md) BEFORE `terraform init`.
# Terraform does not create its own state bucket (chicken-and-egg), so it is not defined in code.
#
# The bucket name is supplied at init time via `-backend-config`, so no environment-specific value
# is hardcoded here:
#
#   terraform init \
#     -backend-config="bucket=${TF_STATE_BUCKET}" \
#     -backend-config="prefix=cia/prod"
#
terraform {
  backend "gcs" {
    prefix = "cia/prod"
    # bucket is provided via -backend-config at init (see above).
  }
}
