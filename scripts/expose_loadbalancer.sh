#!/usr/bin/env bash
#
# Expose the (internal) Cloud Run service publicly through an External Application Load Balancer —
# the supported way into a VPC-SC / internal-ingress-locked project — with REAL browser-trusted
# HTTPS and NO custom domain required.
#
# The no-domain trick: the LB gets a static global IP; we address it as <ip>.sslip.io (sslip.io is
# free wildcard DNS that resolves <ip>.sslip.io -> that IP), and Google issues a MANAGED TLS cert
# for that hostname. Google's managed-cert validation only checks that the hostname resolves to the
# LB's IP — which sslip.io satisfies by construction — so it provisions with no domain ownership.
# Crucially this also makes Google sign-in possible: OAuth/GSI reject raw-IP origins but accept the
# https://<ip>.sslip.io domain. Finally we lock Cloud Run ingress to
# internal-and-cloud-load-balancing so the default run.app URL is shut off and ALL public traffic
# must traverse the LB.
#
# HUMAN-GATED (CLAUDE.md §10): creates billable infra (a global static IP + forwarding rules).
# Idempotent end to end — safe to re-run; each resource is created only if absent.
#
#   bash scripts/expose_loadbalancer.sh
#   DOMAIN=cia.zennify.com bash scripts/expose_loadbalancer.sh   # use a real domain instead of sslip.io
#
set -euo pipefail

PROJECT="${PROJECT:-$(gcloud config get-value project 2>/dev/null)}"
REGION="${REGION:-us-central1}"
SERVICE="${SERVICE:-cia}"
PREFIX="${PREFIX:-cia}"
DOMAIN="${DOMAIN:-}"   # empty -> derive <ip>.sslip.io from the reserved IP

IP_NAME="${PREFIX}-prod-ip"
NEG="${PREFIX}-serverless-neg"
BACKEND="${PREFIX}-backend-service"
URLMAP="${PREFIX}-url-map"
CERT="${PREFIX}-cert"
HPROXY="${PREFIX}-https-proxy"
HFR="${PREFIX}-https-fr"

ok()    { printf '  \342\234\223 %s\n' "$*"; }
fixed() { printf '  FIXED %s\n' "$*"; }
step()  { printf '\n[lb] %s\n' "$*"; }
die()   { printf '\n[lb] FATAL: %s\n' "$*" >&2; exit 1; }

[ -n "$PROJECT" ] && [ "$PROJECT" != "(unset)" ] || die "no project set"
gcloud run services describe "$SERVICE" --region "$REGION" >/dev/null 2>&1 \
  || die "service '${SERVICE}' not found in ${REGION} — deploy it first (scripts/doctor.sh)"
step "project=${PROJECT} region=${REGION} service=${SERVICE}"

# 1. static global IP (reserve first; everything else is addressed off it) ----------------------
step "1. static global IP '${IP_NAME}'"
gcloud compute addresses describe "$IP_NAME" --global >/dev/null 2>&1 \
  || { gcloud compute addresses create "$IP_NAME" --global --network-tier=PREMIUM --quiet \
       && fixed "reserved global IP"; }
IP="$(gcloud compute addresses describe "$IP_NAME" --global --format='value(address)')"
[ -n "$IP" ] || die "could not read the reserved IP"
HOST="${DOMAIN:-$(echo "$IP" | tr '.' '-').sslip.io}"
ok "IP=${IP}  hostname=${HOST}$([ -z "$DOMAIN" ] && echo '  (sslip.io — no custom domain needed)')"

# 2. Google-managed TLS cert for the hostname ---------------------------------------------------
step "2. managed TLS certificate for ${HOST}"
if ! gcloud compute ssl-certificates describe "$CERT" --global >/dev/null 2>&1; then
  gcloud compute ssl-certificates create "$CERT" --domains="$HOST" --global --quiet
  fixed "created managed cert (provisions once traffic flows to the IP; can take 15-60 min)"
else
  ok "cert exists"
fi

# 3. serverless NEG -> backend service -> url map ----------------------------------------------
step "3. serverless NEG + backend + url map"
gcloud compute network-endpoint-groups describe "$NEG" --region "$REGION" >/dev/null 2>&1 \
  || { gcloud compute network-endpoint-groups create "$NEG" --region "$REGION" \
         --network-endpoint-type=serverless --cloud-run-service="$SERVICE" --quiet \
       && fixed "created serverless NEG -> ${SERVICE}"; }
gcloud compute backend-services describe "$BACKEND" --global >/dev/null 2>&1 \
  || { gcloud compute backend-services create "$BACKEND" --global \
         --load-balancing-scheme=EXTERNAL_MANAGED --quiet && fixed "created backend service"; }
# add-backend errors if already attached — make it idempotent
gcloud compute backend-services add-backend "$BACKEND" --global \
  --network-endpoint-group="$NEG" --network-endpoint-group-region="$REGION" --quiet 2>/dev/null \
  && fixed "attached NEG to backend" || ok "NEG already attached"
gcloud compute url-maps describe "$URLMAP" --global >/dev/null 2>&1 \
  || { gcloud compute url-maps create "$URLMAP" --default-service="$BACKEND" --global --quiet \
       && fixed "created url map"; }

# 4. HTTPS target proxy + :443 forwarding rule on the static IP --------------------------------
step "4. HTTPS proxy + :443 forwarding rule"
gcloud compute target-https-proxies describe "$HPROXY" --global >/dev/null 2>&1 \
  || { gcloud compute target-https-proxies create "$HPROXY" --url-map="$URLMAP" \
         --ssl-certificates="$CERT" --global --quiet && fixed "created HTTPS proxy"; }
gcloud compute forwarding-rules describe "$HFR" --global >/dev/null 2>&1 \
  || { gcloud compute forwarding-rules create "$HFR" --global \
         --target-https-proxy="$HPROXY" --ports=443 --address="$IP_NAME" \
         --load-balancing-scheme=EXTERNAL_MANAGED --network-tier=PREMIUM --quiet \
       && fixed "created :443 forwarding rule (the public entrance)"; }

# 5. lock Cloud Run ingress so ONLY the LB can reach the container ------------------------------
step "5. lock service ingress to internal-and-cloud-load-balancing"
gcloud run services update "$SERVICE" --region "$REGION" \
  --ingress internal-and-cloud-load-balancing --quiet \
  && fixed "default run.app URL is now off; all public traffic must pass the LB"

# 6. status + next steps ------------------------------------------------------------------------
step "6. certificate status"
CSTATE="$(gcloud compute ssl-certificates describe "$CERT" --global \
  --format='value(managed.status)' 2>/dev/null || echo UNKNOWN)"
echo "  managed cert status: ${CSTATE}  (ACTIVE means HTTPS is live; PROVISIONING can take up to ~60 min)"
URLP="https://${HOST}"
echo ""
step "DONE — load balancer provisioned"
echo "  Public URL (once the cert is ACTIVE):  ${URLP}"
echo "  Static IP:                             ${IP}"
echo ""
echo "  Finish sign-in (Console, one-time):"
echo "  - APIs & Services -> Credentials -> your OAuth web client -> Authorized JavaScript origins"
echo "    -> add exactly:  ${URLP}"
echo ""
echo "  Watch the cert go ACTIVE, then verify:"
echo "    watch -n30 gcloud compute ssl-certificates describe ${CERT} --global --format='value(managed.status)'"
echo "    curl -s ${URLP}/healthz   # expect {\"status\":\"ok\",...,\"db\":\"ok\"}"
[ -z "$DOMAIN" ] && echo "
  Note: ${HOST} uses sslip.io (free wildcard DNS -> ${IP}); no domain registration or DNS record
  is needed. If your project sits in a VPC-SC perimeter and the cert stays PROVISIONING or the LB
  errors, your security team must allow external ingress to the load balancer for run.googleapis.com."
echo "
  If you later get a real domain (e.g. cia.zennify.com): point an A record at ${IP}, then re-run
  this with DOMAIN=cia.zennify.com to swap the managed cert to it."
