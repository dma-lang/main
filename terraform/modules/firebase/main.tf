# firebase / identitytoolkit — auth fails CLOSED on @zennify.com.
#
# IMPORTANT: The application does NOT use Firebase client SDKs or browser-side Google Identity
# Services. It runs a server-side OAuth 2.0 authorization-code flow (see backend/app/routers/
# auth.py + settings.py): the backend exchanges the code with the client secret, verifies the
# Google Workspace HOSTED DOMAIN (GOOGLE_OAUTH_HOSTED_DOMAIN=zennify.com), and mints its own signed
# session cookie. Sign-in restriction to @zennify.com is enforced IN CODE and FAILS CLOSED
# (AUTH_MODE=live with no dev bypass in prod). Terraform cannot express that policy.
#
# What Terraform CAN do (optional, gated by manage_identity_platform_config):
#   * Manage the Identity Platform project config's authorized domains, IF Identity Platform has
#     already been INITIALIZED on the project. Initialization (enabling Identity Platform / adding
#     it to the Firebase project) is a one-time console or gcloud step and is NOT reliably
#     idempotent through Terraform — do it manually first (see terraform/README.md), then flip
#     manage_identity_platform_config = true to let TF manage authorized_domains.
#
# Because the app uses the plain OAuth code flow, the ONLY thing that must be registered with the
# Google OAuth client is the redirect URI (PUBLIC_BASE_URL + the callback path). There are no
# "Authorized JavaScript origins". That registration happens in the Google Cloud console on the
# OAuth client and is out of Terraform's scope.

terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 5.40, < 7.0"
    }
  }
}

resource "google_identity_platform_config" "auth" {
  count   = var.manage_identity_platform_config ? 1 : 0
  project = var.project_id

  # Domains permitted to complete the redirect handshake (not the email allow-list).
  authorized_domains = var.authorized_domains
}
