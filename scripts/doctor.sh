#!/usr/bin/env bash
#
# CIA doctor — check -> FIX -> verify, on every run. One command from Cloud Shell:
#
#     bash scripts/doctor.sh                      # heal + deploy + migrate + verify
#     bash scripts/doctor.sh --client-id <id>     # also (re)set the Google OAuth client id
#     bash scripts/doctor.sh --check-only         # diagnose and fix config, no deploy/migrate
#
# WHY THIS EXISTS. Production taught us the failure modes, each of which once cost a debugging
# loop: a migrate job created while $SQL_CONN was empty (no Cloud SQL attach -> TCP timeout); a
# DATABASE_URL secret in TCP form instead of the unix-socket form; database/user/password not
# agreeing with the secret; the runtime SA missing roles/cloudsql.client; a service with no ready
# revision (Google's 404); GOOGLE_CLIENT_ID never reaching the service. This script makes every
# one of those self-healing: it re-derives all values from the project on every run (nothing
# depends on shell variables surviving a Cloud Shell session), converges the config to the known-
# good shape, runs the migration with a classify-and-heal retry loop that reads the job's own
# logs, and only reports success when /healthz says {"status":"ok","db":"ok"}.
#
# It is the human-gated entry point (CLAUDE.md §10): the OPERATOR runs it deliberately, with
# operator credentials. The app itself stays least-privilege — it can never edit its own secrets,
# IAM, or job wiring, by design. Self-healing the app can do from inside (DB-wait in app.migrate,
# retries/breakers in app/resilience) lives in the app; everything that needs operator authority
# lives here, automated.
#
# Safety: idempotent end to end; secrets are never printed (only the non-credential tail of the
# DB URL is shown); the only mutations are the documented A3-A9 ones (create db, set the cia SQL
# user's password WHEN credentials are broken, add secret versions, grant the two documented A8
# roles if missing, deploy, update+execute the migrate job).
#
set -euo pipefail

REGION="${REGION:-us-central1}"
SERVICE="${SERVICE:-cia}"
JOB="${JOB:-cia-migrate}"
SQL_INSTANCE="${SQL_INSTANCE:-cia-pg}"
DB_NAME="${DB_NAME:-cia}"
DB_USER="${DB_USER:-cia}"
DB_SECRET="${DB_SECRET:-cia-database-url}"
HMAC_SECRET="${HMAC_SECRET:-cia-hmac-key}"
CLIENT_ID="${CLIENT_ID:-}"
CHECK_ONLY=0

while [ $# -gt 0 ]; do
  case "$1" in
    --client-id) CLIENT_ID="$2"; shift 2 ;;
    --check-only) CHECK_ONLY=1; shift ;;
    *) echo "unknown flag: $1" >&2; exit 2 ;;
  esac
done

ok()    { printf '  \342\234\223 %s\n' "$*"; }
fixed() { printf '  FIXED %s\n' "$*"; }
warn()  { printf '  WARN  %s\n' "$*"; }
step()  { printf '\n[doctor] %s\n' "$*"; }
die()   { printf '\n[doctor] FATAL: %s\n' "$*" >&2; exit 1; }

# ------------------------------------------------------------------ 0. identity & project
step "0. identity & project"
command -v gcloud >/dev/null || die "gcloud CLI not found"
PROJECT="$(gcloud config get-value project 2>/dev/null)"
[ -n "$PROJECT" ] && [ "$PROJECT" != "(unset)" ] || die "no project set — run: gcloud config set project <id>"
ACCOUNT="$(gcloud auth list --filter=status:ACTIVE --format='value(account)')"
[ -n "$ACCOUNT" ] || die "not authenticated — run: gcloud auth login"
ok "account=${ACCOUNT} project=${PROJECT} region=${REGION}"

step "1. required APIs (enable any that are missing)"
NEED_APIS=(run.googleapis.com sqladmin.googleapis.com secretmanager.googleapis.com
           cloudbuild.googleapis.com artifactregistry.googleapis.com logging.googleapis.com)
ENABLED="$(gcloud services list --enabled --format='value(config.name)')"
for api in "${NEED_APIS[@]}"; do
  if grep -q "^${api}$" <<<"$ENABLED"; then ok "$api"; else
    gcloud services enable "$api" --quiet && fixed "enabled $api"
  fi
done

# ------------------------------------------------------------------ 2. Cloud SQL instance
step "2. Cloud SQL instance '${SQL_INSTANCE}'"
STATE="$(gcloud sql instances describe "$SQL_INSTANCE" --format='value(state)' 2>/dev/null || true)"
if [ -z "$STATE" ]; then
  die "instance '${SQL_INSTANCE}' does not exist. Creating one is a paid decision the doctor will
not take for you — create it per docs/DEPLOYMENT.md A3 (Postgres 16, region ${REGION}), then re-run."
fi
[ "$STATE" = "RUNNABLE" ] || die "instance '${SQL_INSTANCE}' is ${STATE}, not RUNNABLE — wait/start it, then re-run"
SQL_CONN="$(gcloud sql instances describe "$SQL_INSTANCE" --format='value(connectionName)')"
[ -n "$SQL_CONN" ] || die "could not resolve the instance connection name"
ok "RUNNABLE — ${SQL_CONN}"

# Reachability from Cloud Run's built-in Cloud SQL Auth Proxy. With --add/--set-cloudsql-instances
# the proxy reaches the instance over its PUBLIC IP by default; a private-IP-only instance with no
# VPC egress is unreachable, so the proxy drops the connection ("server closed the connection
# unexpectedly") however correct the secret/roles/password are. This was the residual blocker that
# survived every other fix because it is a NETWORK fact, not a config string. Proven by simulation:
# the migration runner applies all migrations against a reachable empty DB with exit 0, so a job
# that still fails to connect can only be failing the network path. Heal it by enabling the public
# IP — the proxy stays IAM-gated and, with no authorized networks, the instance is not internet-
# exposed (for a private-IP posture instead, attach a Serverless VPC connector to the job/service).
PUBLIC_IP="$(gcloud sql instances describe "$SQL_INSTANCE" \
  --format='value(settings.ipConfiguration.ipv4Enabled)')"
JOB_VPC="$(gcloud run jobs describe "$JOB" --region "$REGION" \
  --format='value(spec.template.metadata.annotations."run.googleapis.com/vpc-access-connector")' \
  2>/dev/null || true)"
if [ "$PUBLIC_IP" = "True" ]; then
  ok "instance has a public IP — the Cloud SQL Auth Proxy can reach it"
elif [ -n "$JOB_VPC" ]; then
  ok "instance is private-IP, but the migrate job egresses via VPC connector ${JOB_VPC}"
else
  warn "instance has NO public IP and the migrate job has no VPC egress — the Cloud SQL proxy"
  warn "cannot reach it; THIS is the 'server closed the connection unexpectedly' failure"
  if gcloud sql instances patch "$SQL_INSTANCE" --assign-ip --quiet; then
    fixed "enabled the instance public IP (IAM-gated proxy; no authorized networks = not exposed)"
  else
    die "could not enable the public IP (org policy?). Private-IP alternative — create a
Serverless VPC connector once and attach it to both the job and the service:
  gcloud compute networks vpc-access connectors create cia-conn --region ${REGION} --range 10.8.0.0/28
  gcloud run jobs update ${JOB} --region ${REGION} --vpc-connector cia-conn --vpc-egress private-ranges-only
  gcloud run services update ${SERVICE} --region ${REGION} --vpc-connector cia-conn --vpc-egress private-ranges-only
then re-run this doctor."
  fi
fi

step "3. database '${DB_NAME}'"
if gcloud sql databases describe "$DB_NAME" --instance="$SQL_INSTANCE" >/dev/null 2>&1; then
  ok "exists"
else
  gcloud sql databases create "$DB_NAME" --instance="$SQL_INSTANCE" --quiet
  fixed "created database ${DB_NAME}"
fi

# heal_db_credentials: make user+password+secret agree BY CONSTRUCTION (the only way to repair a
# password mismatch without being able to test the old one). Never prints the password.
heal_db_credentials() {
  local pw; pw="$(openssl rand -base64 33 | tr -dc 'A-Za-z0-9' | head -c 32)"
  gcloud sql users create "$DB_USER" --instance="$SQL_INSTANCE" --password="$pw" --quiet 2>/dev/null \
    || gcloud sql users set-password "$DB_USER" --instance="$SQL_INSTANCE" --password="$pw" --quiet
  printf 'postgresql+asyncpg://%s:%s@/%s?host=/cloudsql/%s' "$DB_USER" "$pw" "$DB_NAME" "$SQL_CONN" \
    | gcloud secrets versions add "$DB_SECRET" --data-file=- >/dev/null
  fixed "reset ${DB_USER} password and rewrote ${DB_SECRET} to match (socket form)"
}

step "4. secrets"
if ! gcloud secrets describe "$HMAC_SECRET" >/dev/null 2>&1; then
  openssl rand -base64 48 | gcloud secrets create "$HMAC_SECRET" --data-file=- >/dev/null
  fixed "created ${HMAC_SECRET}"
else ok "${HMAC_SECRET} exists"; fi
if ! gcloud secrets describe "$DB_SECRET" >/dev/null 2>&1; then
  gcloud secrets create "$DB_SECRET" --replication-policy=automatic >/dev/null 2>&1 || true
  heal_db_credentials
else
  CUR_TAIL="$(gcloud secrets versions access latest --secret="$DB_SECRET" 2>/dev/null | sed 's#^.*@#@#')"
  WANT_TAIL="@/${DB_NAME}?host=/cloudsql/${SQL_CONN}"
  if [ "$CUR_TAIL" = "$WANT_TAIL" ]; then
    ok "${DB_SECRET} is socket-form and points at ${SQL_INSTANCE}"
  else
    warn "${DB_SECRET} is '${CUR_TAIL:-<empty>}' — must be '${WANT_TAIL}'"
    heal_db_credentials
  fi
fi

step "5. runtime service-account roles (documented in A8)"
PN="$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')"
RUN_SA="$(gcloud run services describe "$SERVICE" --region "$REGION" \
  --format='value(spec.template.spec.serviceAccountName)' 2>/dev/null || true)"
RUN_SA="${RUN_SA:-${PN}-compute@developer.gserviceaccount.com}"
POLICY="$(gcloud projects get-iam-policy "$PROJECT" \
  --flatten='bindings[].members' --filter="bindings.members:serviceAccount:${RUN_SA}" \
  --format='value(bindings.role)')"
for role in roles/cloudsql.client roles/secretmanager.secretAccessor; do
  if grep -q "^${role}$" <<<"$POLICY"; then ok "${RUN_SA} has ${role}"; else
    gcloud projects add-iam-policy-binding "$PROJECT" \
      --member="serviceAccount:${RUN_SA}" --role="$role" --quiet >/dev/null
    fixed "granted ${role} to ${RUN_SA}"
  fi
done

if [ "$CHECK_ONLY" = "1" ]; then
  step "check-only: configuration converged; skipping deploy/migrate/verify"
  exit 0
fi

# ------------------------------------------------------------------ 6. deploy the service
step "6. deploy ${SERVICE} from source (Cloud Build)"
[ -f Dockerfile ] && [ -d backend ] || die "run from the repo root (~/cia)"
if [ -z "$CLIENT_ID" ]; then
  CLIENT_ID="$(gcloud run services describe "$SERVICE" --region "$REGION" --format=json 2>/dev/null \
    | python3 -c 'import json,sys
try:
  envs=json.load(sys.stdin)["spec"]["template"]["spec"]["containers"][0].get("env",[])
  print(next((e.get("value","") for e in envs if e.get("name")=="GOOGLE_CLIENT_ID"), ""))
except Exception:
  print("")')"
fi
ENVS="LLM_MODE=live"
if [ -n "$CLIENT_ID" ]; then ENVS="${ENVS},GOOGLE_CLIENT_ID=${CLIENT_ID}"; ok "GOOGLE_CLIENT_ID present"; else
  warn "no GOOGLE_CLIENT_ID known — sign-in will be unconfigured until you re-run with --client-id <id>"
fi
gcloud run deploy "$SERVICE" --source . --region "$REGION" \
  --allow-unauthenticated \
  --add-cloudsql-instances "$SQL_CONN" \
  --set-secrets "DATABASE_URL=${DB_SECRET}:latest,HMAC_KEY=${HMAC_SECRET}:latest" \
  --set-env-vars "$ENVS" \
  --quiet
READY="$(gcloud run services describe "$SERVICE" --region "$REGION" --format='value(status.latestReadyRevisionName)')"
CREATED="$(gcloud run services describe "$SERVICE" --region "$REGION" --format='value(status.latestCreatedRevisionName)')"
if [ -z "$READY" ] || [ "$READY" != "$CREATED" ]; then
  step "revision ${CREATED} is not ready — its own logs:"
  gcloud logging read "resource.type=\"cloud_run_revision\" AND resource.labels.revision_name=\"${CREATED}\" AND severity>=ERROR" \
    --freshness=30m --limit 20 --format='value(textPayload)' | head -30
  die "service has no ready revision — fix the error above and re-run"
fi
ok "serving revision ${READY}"
# Ingress: a service can deploy green yet Google-404 every external request when ingress is
# restricted (internal / internal-and-cloud-load-balancing). The app's own auth fails closed, so
# external ingress is safe — converge it.
INGRESS="$(gcloud run services describe "$SERVICE" --region "$REGION" \
  --format='value(metadata.annotations."run.googleapis.com/ingress")')"
if [ -n "$INGRESS" ] && [ "$INGRESS" != "all" ]; then
  warn "service ingress is '${INGRESS}' — external requests get Google's 404 page, not the app"
  gcloud run services update "$SERVICE" --region "$REGION" --ingress all --quiet
  fixed "ingress set to 'all' (sign-in still fails closed inside the app)"
else
  ok "ingress allows external traffic"
fi
URL="$(gcloud run services describe "$SERVICE" --region "$REGION" --format='value(status.url)')"

# ------------------------------------------------------------------ 7. migrate (classify+heal)
step "7. migration job '${JOB}' (converge config, then execute with classify-and-heal)"
IMAGE="$(gcloud run services describe "$SERVICE" --region "$REGION" --format='value(spec.template.spec.containers[0].image)')"
[ -n "$IMAGE" ] || die "could not resolve the service image"
JOB_ARGS=(--image "$IMAGE" --region "$REGION"
          --set-cloudsql-instances "$SQL_CONN"
          --set-secrets "DATABASE_URL=${DB_SECRET}:latest"
          --command uv --args run,python,-m,app.migrate
          --max-retries 1 --task-timeout 600)
if gcloud run jobs describe "$JOB" --region "$REGION" >/dev/null 2>&1; then
  gcloud run jobs update "$JOB" "${JOB_ARGS[@]}" --quiet && ok "job converged to fresh image + SQL attach"
else
  gcloud run jobs create "$JOB" "${JOB_ARGS[@]}" --quiet && fixed "created job ${JOB}"
fi
ATTACH="$(gcloud run jobs describe "$JOB" --region "$REGION" --format=yaml | grep -m1 'cloudsql-instances' | sed "s/.*: //;s/'//g")"
[ "$ATTACH" = "$SQL_CONN" ] || die "job SQL attach is '${ATTACH:-<empty>}' (expected ${SQL_CONN}) — gcloud refused the update?"

migrate_logs() {
  gcloud logging read "resource.type=\"cloud_run_job\" AND resource.labels.job_name=\"${JOB}\" AND severity>=ERROR" \
    --freshness=15m --limit 40 --format='value(textPayload)'
}
for attempt in 1 2 3; do
  if gcloud run jobs execute "$JOB" --region "$REGION" --wait --quiet; then
    ok "migration succeeded (attempt ${attempt})"
    MIGRATED=1; break
  fi
  MIGRATED=0
  LOGS="$(migrate_logs)"
  printf '  --- migration error (attempt %s) — the migrate job log lines ---\n' "$attempt"
  grep -E '^(psycopg|sqlalchemy|alembic|RuntimeError|TimeoutError|FileNotFoundError|FATAL)' \
    <<<"$LOGS" | sort -u | head -6 | sed 's/^/    /'
  if grep -qiE 'password authentication failed|role "'"$DB_USER"'" does not exist|28P01' <<<"$LOGS"; then
    warn "attempt ${attempt}: credentials disagree — healing user+password+secret"
    heal_db_credentials
  elif grep -qiE 'database "'"$DB_NAME"'" does not exist|3D000' <<<"$LOGS"; then
    warn "attempt ${attempt}: database missing — creating"
    gcloud sql databases create "$DB_NAME" --instance="$SQL_INSTANCE" --quiet || true
  elif grep -qiE 'server closed the connection unexpectedly|connection timeout|not reachable after' <<<"$LOGS"; then
    warn "attempt ${attempt}: transient connectivity (proxy/instance) — retrying"
  else
    step "unrecognised failure — the job's own error lines:"
    grep -E '^(psycopg|sqlalchemy|alembic|RuntimeError|TimeoutError|FileNotFoundError)' <<<"$LOGS" | sort -u | head -8
    die "migration failed for a reason the doctor does not auto-heal (see lines above)"
  fi
done
[ "${MIGRATED:-0}" = "1" ] || die "migration still failing after 3 heal attempts — error lines: $(migrate_logs | grep -E '^(psycopg|sqlalchemy)' | sort -u | head -3)"

# ------------------------------------------------------------------ 8. end-to-end verify
step "8. verify external reachability + health at ${URL}"
# /healthz ALWAYS returns HTTP 200 (db state is a body field, never an HTTP error). So a non-200
# means the request never reached the app — it was rejected at Google's frontend = ingress / org
# policy / wrong URL, NOT the database. Re-assert public ingress first (the app's own auth fails
# closed, so external ingress is safe).
CUR_INGRESS="$(gcloud run services describe "$SERVICE" --region "$REGION" \
  --format='value(metadata.annotations."run.googleapis.com/ingress")')"
if [ "${CUR_INGRESS:-all}" != "all" ]; then
  gcloud run services update "$SERVICE" --region "$REGION" --ingress all --quiet \
    && fixed "ingress -> all" || warn "could not set ingress to all (org policy?)"
fi

# Diagnostic probe: capture HTTP code AND body (no -f, so 404/503 bodies are visible). Retry to
# absorb a just-deployed revision and the freshly-enabled public IP settling.
TMP="$(mktemp)"
CODE=000; BODY=""
for _ in 1 2 3 4 5 6; do
  CODE="$(curl -sS -o "$TMP" -w '%{http_code}' --max-time 20 "${URL}/healthz" 2>/dev/null || echo 000)"
  BODY="$(cat "$TMP" 2>/dev/null)"
  { [ "$CODE" = "200" ] && grep -q '"db":"ok"' <<<"$BODY"; } && break
  sleep 8
done
rm -f "$TMP"
echo "  HTTP ${CODE} — $(head -c 200 <<<"$BODY" | tr '\n' ' ')"

case "$CODE" in
  200)
    if grep -q '"db":"ok"' <<<"$BODY"; then
      ok "healthy: ${BODY}"
    else
      die "the app is reachable but reports db=down — the SERVING revision lacks the Cloud SQL
attach or the secret. Re-run the doctor (its step 6 deploys with both); if it persists, the
serving revision is stale: gcloud run services update-traffic ${SERVICE} --region ${REGION} --to-latest.
body: ${BODY}"
    fi
    ;;
  403|404)
    # Reached Google's frontend, not the app: ingress, an org policy override, or a stale URL.
    POL="$(gcloud org-policies describe run.allowedIngress --project "$PROJECT" 2>/dev/null \
      | grep -iE 'internal|INTERNAL' || true)"
    if [ -n "$POL" ]; then
      die "ROOT CAUSE: the org policy constraints/run.allowedIngress restricts this project to
INTERNAL ingress, so ${URL} is unreachable from the public internet no matter the per-service
setting (this is why /healthz 404s externally while the app is healthy and migrated internally).
If you have orgpolicy.policyAdmin on the project, lift it with:
    gcloud org-policies reset run.allowedIngress --project ${PROJECT}
  then re-run this doctor. Otherwise an ORG ADMIN must allow external ingress (or exempt the
'${SERVICE}' service), or you front it with an external HTTPS Load Balancer / IAP, or reach it
from inside the VPC. Nothing in the app or this script can override an org policy."
    fi
    OTHERS="$(gcloud run services list --format='value(metadata.name)' 2>/dev/null \
      | grep -v "^${SERVICE}\$" | tr '\n' ' ')"
    die "external request hit Google's ${CODE} (not the app). Ingress is now 'all' with no
org-policy override detected, so you are almost certainly opening a STALE url. The ONE url for the
live service is:
    ${URL}
Other Cloud Run services in this project (a stale bookmark may point at one): ${OTHERS:-none}"
    ;;
  000)
    die "no HTTP response from ${URL} (timeout/DNS/connection). A VPC-SC perimeter or network
policy in front of Cloud Run can block the run.app URL externally — otherwise retry in a minute."
    ;;
  *)
    die "unexpected HTTP ${CODE} from ${URL}/healthz — body: ${BODY:-<empty>}"
    ;;
esac

# Sign-in config smoke: the SPA needs only the OAuth CLIENT ID (Google Identity Services ID-token
# flow — the client SECRET is for authorization-code server flows this app does not use; there is
# nothing to configure for it).
CFG="$(curl -sS --max-time 20 "${URL}/api/config" 2>/dev/null || true)"
if grep -q '"google_client_id":"..*"' <<<"$CFG"; then
  ok "sign-in configured — /api/config serves the client id"
else
  warn "GOOGLE_CLIENT_ID is not live on the service — sign-in will say 'not configured';"
  warn "re-run with: bash scripts/doctor.sh --client-id <your-oauth-web-client-id>"
fi

step "DONE — healthy at ${URL}"
echo "  USE EXACTLY THIS URL in the browser. Older bookmarks may point at a stale service:"
OTHERS="$(gcloud run services list --format='value(metadata.name)' 2>/dev/null | grep -v "^${SERVICE}\$" | head -6 | tr '\n' ' ')"
[ -n "$OTHERS" ] && echo "  (other Cloud Run services exist in this project: ${OTHERS}— the CIA app is only '${SERVICE}')"
echo ""
echo "  Two things only the Console can do (gcloud has no API for either):"
echo "  1. If Google shows 'Error 401: invalid_client' at sign-in, the configured OAuth client id"
echo "     no longer exists (it was rotated/deleted). Create or open the CURRENT 'Web application'"
echo "     client (Console -> APIs & Services -> Credentials), copy its Client ID, then:"
echo "         bash scripts/doctor.sh --client-id <the-new-client-id>"
echo "  2. On that SAME client, add to 'Authorized JavaScript origins':  ${URL}"
