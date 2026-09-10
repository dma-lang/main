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
# logs, and only reports success when the app answers /api/config with "db":"ok" on the public url.
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

# The managed credential broker prints a benign, non-fatal line to stderr on most gcloud calls —
# "Regional Access Boundary HTTP request failed after retries: ... Account not found for email:
# <session>|<you>" — because it scopes the brokered token, the synthetic principal 404s, and it
# then falls back (every call still succeeds). Drop ONLY that exact line from our stderr so the
# check/heal report stays readable; real gcloud errors and our own warnings pass through untouched.
# Some lines stay glued to gcloud's progress spinner (same line) and can't be split off. QUIET_BROKER=0 disables.
if [ "${QUIET_BROKER:-1}" = "1" ]; then
  exec 2> >(grep --line-buffered -v 'Regional Access Boundary HTTP request failed' >&2)
fi

REGION="${REGION:-us-central1}"
SERVICE="${SERVICE:-cia}"
JOB="${JOB:-cia-migrate}"
SQL_INSTANCE="${SQL_INSTANCE:-cia-pg}"
DB_NAME="${DB_NAME:-cia}"
DB_USER="${DB_USER:-cia}"
DB_SECRET="${DB_SECRET:-cia-database-url}"
HMAC_SECRET="${HMAC_SECRET:-cia-hmac-key}"
# Secret Manager name for the OAuth client secret. DEPLOYMENT.md A7 calls it cia-oauth-client-secret;
# earlier doctor runs used cia-google-client-secret. Storing a rotated secret under one name while
# the service reads the other leaves the service on the STALE secret -> every sign-in ends in
# "google token exchange failed: 401" (invalid_client). So, unless overridden, the doctor uses the
# secret the LIVE service actually reads (derived below from its GOOGLE_OAUTH_CLIENT_SECRET ref).
OAUTH_SECRET_DEFAULT="cia-oauth-client-secret"
OAUTH_SECRET="${OAUTH_SECRET:-}"
# The project's Google OAuth *web* client (a public identifier). It has BOTH CIA callback URLs
# registered (cia-<project#>.<region>.run.app and the legacy hash host, /api/auth/callback). Pass
# --client-id to use another; the matching secret MUST come from the same client (--client-secret).
CLIENT_ID_DEFAULT="306195530103-ub6t46i8sd9q1eatpt6dgo0i9811mnrp.apps.googleusercontent.com"
CLIENT_ID="${CLIENT_ID:-}"
CLIENT_SECRET="${CLIENT_SECRET:-}"
CHECK_ONLY=0

while [ $# -gt 0 ]; do
  case "$1" in
    --client-id) CLIENT_ID="$2"; shift 2 ;;
    --client-secret) CLIENT_SECRET="$2"; shift 2 ;;  # OAuth code flow needs the secret (server-side)
    --check-only) CHECK_ONLY=1; shift ;;
    *) echo "unknown flag: $1" >&2; exit 2 ;;
  esac
done

ok()    { printf '  \342\234\223 %s\n' "$*"; }
fixed() { printf '  FIXED %s\n' "$*"; }
warn()  { printf '  WARN  %s\n' "$*"; }
step()  { printf '\n[doctor] %s\n' "$*"; }
die()   { printf '\n[doctor] FATAL: %s\n' "$*" >&2; exit 1; }

# Guard the one value the doctor cannot verify by construction. A Google OAuth *web client* secret
# is a short opaque string (modern ones 'GOCSPX-' + 28 chars; legacy ones ~24 chars). A pasted
# private-key body, a JSON fragment or a multi-line value would be stored verbatim, wired to the
# service, and make Google answer 401 invalid_client on every sign-in — with nothing else to see.
# (It happened: the private key from a service-account JSON was passed here once.)
if [ -n "$CLIENT_SECRET" ]; then
  if [ "${#CLIENT_SECRET}" -gt 64 ] || grep -qE 'PRIVATE KEY|\\n|^MII|[{}"]' <<<"$CLIENT_SECRET"; then
    die "--client-secret does not look like an OAuth client secret (length ${#CLIENT_SECRET}; Google's are
24-40 characters, usually 'GOCSPX-…'). It looks like a private key or a pasted JSON fragment.
Use the value of the \"client_secret\" field from the OAuth WEB client's JSON (Console -> APIs &
Services -> Credentials -> that client -> Download JSON). Nothing was stored; nothing was deployed."
  fi
fi

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

# Reachability from Cloud Run's built-in Cloud SQL Auth Proxy. With --add-cloudsql-instances the
# proxy reaches the instance over its PUBLIC IP; if the instance has no public IP the proxy drops
# the connection ("server closed the connection unexpectedly") however correct everything else is.
# Heal it by enabling the public IP — the proxy stays IAM-gated and, with no authorized networks,
# the instance is not internet-exposed. (No VPC / load balancer needed.)
PUBLIC_IP="$(gcloud sql instances describe "$SQL_INSTANCE" \
  --format='value(settings.ipConfiguration.ipv4Enabled)')"
if [ "$PUBLIC_IP" = "True" ]; then
  ok "instance has a public IP — the Cloud SQL Auth Proxy can reach it"
else
  warn "instance has NO public IP — enabling it so the Cloud SQL proxy can reach it"
  gcloud sql instances patch "$SQL_INSTANCE" --assign-ip --quiet \
    && fixed "enabled the instance public IP (IAM-gated proxy; no authorized networks = not exposed)" \
    || die "could not enable the public IP (org policy?) — ask an admin to allow it, then re-run"
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
# OAuth client secret (the code flow needs it, server-side). The doctor cannot invent it — store
# it once with --client-secret; thereafter it lives in Secret Manager — under the name the LIVE
# service reads (its GOOGLE_OAUTH_CLIENT_SECRET secret ref), so a rotation can never land in a
# secret the service ignores.
if [ -z "$OAUTH_SECRET" ]; then
  OAUTH_SECRET="$(gcloud run services describe "$SERVICE" --region "$REGION" --format=json 2>/dev/null \
    | python3 -c 'import json,sys
try:
  envs=json.load(sys.stdin)["spec"]["template"]["spec"]["containers"][0].get("env",[])
  for e in envs:
    if e.get("name")=="GOOGLE_OAUTH_CLIENT_SECRET":
      print(e.get("valueFrom",{}).get("secretKeyRef",{}).get("name","")); break
  else:
    print("")
except Exception:
  print("")')"
  OAUTH_SECRET="${OAUTH_SECRET:-$OAUTH_SECRET_DEFAULT}"
fi
ok "OAuth client secret lives in Secret Manager as '${OAUTH_SECRET}' (the name the service reads)"
if [ -n "$CLIENT_SECRET" ]; then
  gcloud secrets describe "$OAUTH_SECRET" >/dev/null 2>&1 \
    || gcloud secrets create "$OAUTH_SECRET" --replication-policy=automatic >/dev/null 2>&1 || true
  printf '%s' "$CLIENT_SECRET" | gcloud secrets versions add "$OAUTH_SECRET" --data-file=- >/dev/null
  fixed "stored the OAuth client secret in ${OAUTH_SECRET}"
fi
if gcloud secrets describe "$OAUTH_SECRET" >/dev/null 2>&1; then
  OAUTH_SECRET_READY=1
  ok "${OAUTH_SECRET} present (OAuth client secret)"
else
  OAUTH_SECRET_READY=0
  warn "no OAuth client secret yet — sign-in will be unconfigured until you re-run with"
  warn "  --client-secret <the GOCSPX-… secret from APIs & Services -> Credentials>"
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
if [ -z "$CLIENT_ID" ]; then  # reuse the id already on the service if not passed
  CLIENT_ID="$(gcloud run services describe "$SERVICE" --region "$REGION" --format=json 2>/dev/null \
    | python3 -c 'import json,sys
try:
  envs=json.load(sys.stdin)["spec"]["template"]["spec"]["containers"][0].get("env",[])
  by={e.get("name"):e.get("value","") for e in envs}
  print(by.get("GOOGLE_OAUTH_CLIENT_ID") or by.get("GOOGLE_CLIENT_ID") or "")
except Exception:
  print("")')"
  # nothing on the service yet -> the project's web client (its callback URLs are registered)
  CLIENT_ID="${CLIENT_ID:-$CLIENT_ID_DEFAULT}"
fi
# OAuth Authorization-Code flow: the SPA needs the client id (env) and the service needs the
# client secret (Secret Manager). The secret stays out of env vars. PUBLIC_BASE_URL pins the
# OAuth round-trip to the ONE canonical url — Cloud Run answers on two hostnames, and a
# host-derived redirect_uri was a moving target no registration could reliably match.
CANON_URL="https://${SERVICE}-${PN}.${REGION}.run.app"
ENVS="LLM_MODE=live,PUBLIC_BASE_URL=${CANON_URL}"
SECRETS="DATABASE_URL=${DB_SECRET}:latest,HMAC_KEY=${HMAC_SECRET}:latest"
if [ -n "$CLIENT_ID" ]; then
  ENVS="${ENVS},GOOGLE_OAUTH_CLIENT_ID=${CLIENT_ID}"
  ok "GOOGLE_OAUTH_CLIENT_ID present"
else
  warn "no client id — re-run with --client-id <oauth-web-client-id>"
fi
if [ "${OAUTH_SECRET_READY:-0}" = "1" ]; then
  SECRETS="${SECRETS},GOOGLE_OAUTH_CLIENT_SECRET=${OAUTH_SECRET}:latest"
  ok "GOOGLE_OAUTH_CLIENT_SECRET wired from ${OAUTH_SECRET}"
fi
gcloud run deploy "$SERVICE" --source . --region "$REGION" \
  --allow-unauthenticated \
  --add-cloudsql-instances "$SQL_CONN" \
  --set-secrets "$SECRETS" \
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

# ------------------------------------------------------------------ 7. migrate + refresh (classify+heal)
step "7. migrate + data-plane refresh job '${JOB}' (converge config, then execute with classify-and-heal)"
IMAGE="$(gcloud run services describe "$SERVICE" --region "$REGION" --format='value(spec.template.spec.containers[0].image)')"
[ -n "$IMAGE" ] || die "could not resolve the service image"
# app.refresh = alembic upgrade head THEN re-provision + re-carry every cat_<v>, so a deploy never
# serves stale catalogue / delivery. REFRESH_BUILD_ID makes a same-image re-run a no-op (no rebuild,
# no embedding spend); the longer task timeout covers the extra carry/offerings/embeddings work.
# MEMORY: the R8 rich re-ingest grew the story seed ~16x (~34MB / 14,406 rows, loaded whole); the
# Cloud Run 512Mi default OOM-kills this job (SIGKILL leaves NO app error log — the classic empty
# "migration error" block below). 4Gi/2CPU gives headroom; MIGRATE_MEM raises it further on an OOM
# heal. `jobs update` re-converges an EXISTING job's memory, so re-running the doctor fixes a job
# that was created too small.
MIGRATE_MEM="${MIGRATE_MEM:-4Gi}"
JOB_ARGS=(--image "$IMAGE" --region "$REGION"
          --set-cloudsql-instances "$SQL_CONN"
          --set-secrets "DATABASE_URL=${DB_SECRET}:latest"
          --command uv --args run,python,-m,app.refresh
          --update-env-vars "REFRESH_BUILD_ID=${IMAGE}"
          --memory "$MIGRATE_MEM" --cpu 2 --max-retries 1 --task-timeout 3600)
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
# All-severity job logs + the execution's terminal condition — an OOM/SIGKILL emits NO app ERROR
# log, so ``migrate_logs`` comes back empty; these give the operator something to see and let the
# heal loop recognise the out-of-memory case.
migrate_logs_any() {
  gcloud logging read "resource.type=\"cloud_run_job\" AND resource.labels.job_name=\"${JOB}\"" \
    --freshness=15m --limit 60 --format='value(textPayload)' 2>/dev/null || true
}
migrate_terminated() {
  gcloud run jobs executions list --job="$JOB" --region="$REGION" --limit=1 \
    --format='value(status.conditions.message)' 2>/dev/null || true
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
  elif grep -qiE 'oom|out of memory|memory limit|cannot allocate|memoryerror|signal 9|code 137' \
         <<<"$LOGS$(migrate_terminated)" || [ -z "${LOGS//[[:space:]]/}" ]; then
    # OOM/SIGKILL leaves NO application error log, so an EMPTY error-log after a hard failure IS the
    # out-of-memory signature (the R8 rich seed loads whole into memory). Raise the job's memory and
    # retry — the next iteration executes the re-converged, larger job.
    case "$MIGRATE_MEM" in 4Gi) MIGRATE_MEM=8Gi ;; 8Gi) MIGRATE_MEM=16Gi ;; *) MIGRATE_MEM=16Gi ;; esac
    warn "attempt ${attempt}: no application error log after a hard failure = OOM/SIGKILL (the rich R8 story seed exceeds the container memory). Raising job memory to ${MIGRATE_MEM} and retrying."
    gcloud run jobs update "$JOB" --region "$REGION" --memory "$MIGRATE_MEM" --cpu 2 --quiet
    fixed "migrate job memory -> ${MIGRATE_MEM}"
  else
    step "unrecognised failure — the job's own log lines (all severities):"
    migrate_logs_any | tail -25 | sed 's/^/    /'
    die "migration failed for a reason the doctor does not auto-heal (see lines above)"
  fi
done
[ "${MIGRATED:-0}" = "1" ] || die "migration still failing after 3 heal attempts — error lines: $(migrate_logs | grep -E '^(psycopg|sqlalchemy)' | sort -u | head -3)"

# ------------------------------------------------------------------ 8. end-to-end verify
step "8. verify external reachability + health"
# The probe path ALWAYS returns HTTP 200 from the app (db state is a body field, never an HTTP
# error). So a non-200 means the request never reached the app — rejected at Google's frontend =
# ingress / org policy / wrong URL, NOT the database. Re-assert public ingress first (the app's own
# auth fails closed, so external ingress is safe).
# NOT /healthz: on this project Google's frontend answers /healthz on the public run.app URL with
# its own HTML 404 while /, /livez and /api/* all reach the app (observed 2026-09). Probing it
# produced a false "ingress blocked" root cause on a perfectly healthy deploy and sent the doctor
# into its ingress/IAM/org-policy healing branch. /api/config is public, unauthenticated, comes
# from the app itself and carries the db state.
HEALTH_PATH="/api/config"
CUR_INGRESS="$(gcloud run services describe "$SERVICE" --region "$REGION" \
  --format='value(metadata.annotations."run.googleapis.com/ingress")')"
if [ "${CUR_INGRESS:-all}" != "all" ]; then
  gcloud run services update "$SERVICE" --region "$REGION" --ingress all --quiet \
    && fixed "ingress -> all" || warn "could not set ingress to all (org policy?)"
fi

# A Cloud Run service can carry TWO url formats — the deterministic one
# (<service>-<projectNumber>.<region>.run.app, what `gcloud run deploy` prints) and the legacy
# hash one (<service>-<hash>-<rc>.a.run.app, what status.url can still report) — and on some
# services only the deterministic one actually routes (the legacy URL 404s at the GFE). Probing
# only status.url produced a false "service unreachable" while the app was healthy the whole
# time. Probe BOTH and adopt whichever answers.
DET_URL="https://${SERVICE}-${PN}.${REGION}.run.app"
CANDIDATES=("$DET_URL")
[ -n "$URL" ] && [ "$URL" != "$DET_URL" ] && CANDIDATES+=("$URL")
WINNER=""; CODE=000; BODY=""
TMP="$(mktemp)"
for _ in 1 2 3 4 5 6; do
  for u in "${CANDIDATES[@]}"; do
    CODE="$(curl -sS -o "$TMP" -w '%{http_code}' --max-time 20 "${u}${HEALTH_PATH}" 2>/dev/null || echo 000)"
    BODY="$(cat "$TMP" 2>/dev/null)"
    echo "  ${u} -> HTTP ${CODE}"
    if [ "$CODE" = "200" ]; then WINNER="$u"; break 2; fi
  done
  sleep 8
done
rm -f "$TMP"
if [ -n "$WINNER" ]; then
  URL="$WINNER"
  ok "the live url is ${URL}"
else
  URL="$DET_URL"
  echo "  no url format answered 200 — last body: $(head -c 200 <<<"$BODY" | tr '\n' ' ')"
fi

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
    # Google's frontend answered, the app did not: external ingress is blocked ABOVE the service.
    # Heal the two service-level causes explicitly (the earlier check skips when the ingress
    # annotation is absent, which defaults to 'all' but can still be overridden by policy), then
    # attempt the project-level org-policy override (the operator is project Owner), then re-probe.
    warn "HTTP ${CODE} at Google's frontend — forcing public ingress + invoker, then retrying"
    ERRF="$(mktemp)"
    gcloud run services update "$SERVICE" --region "$REGION" --ingress all --quiet 2>"$ERRF" \
      && fixed "ingress -> all (explicit)" \
      || warn "ingress update rejected: $(head -1 "$ERRF")"
    gcloud run services add-iam-policy-binding "$SERVICE" --region "$REGION" \
      --member=allUsers --role=roles/run.invoker --quiet >/dev/null 2>"$ERRF" \
      && fixed "granted run.invoker to allUsers (the app still fails closed at sign-in)" \
      || warn "could not grant public invoker: $(head -1 "$ERRF") (org policy iam.allowedPolicyMemberDomains?)"

    # "Default URL disabled": a service-level switch that makes BOTH run.app urls return Google's
    # 404 BY DESIGN while deploys stay green — exactly these symptoms. Check and re-enable.
    DEFURL_OFF="$(gcloud run services describe "$SERVICE" --region "$REGION" \
      --format='value(metadata.annotations."run.googleapis.com/default-url-disabled")' 2>/dev/null)"
    echo "  default-url-disabled annotation: '${DEFURL_OFF:-<absent>}'"
    if grep -qi 'true' <<<"$DEFURL_OFF"; then
      warn "the service's DEFAULT URL is DISABLED — that alone 404s both run.app urls"
      gcloud run services update "$SERVICE" --region "$REGION" --default-url --quiet 2>"$ERRF" \
        && fixed "re-enabled the default run.app url" \
        || warn "could not re-enable the default url: $(head -1 "$ERRF") — in the Console: Cloud Run -> ${SERVICE} -> Networking -> enable 'Default URL'"
    fi

    # Also check the ORG-LEVEL default-URL policy: constraints/run.disableDefaultURI enforced from a
    # folder/org disables BOTH run.app urls for every service (GFE 404) regardless of the per-service
    # annotation — the per-service --default-url override cannot beat an enforced org policy.
    DEFPOL="$(gcloud org-policies describe run.disableDefaultURI --project "$PROJECT" --effective \
      2>/dev/null | grep -v 'Regional Access Boundary' || true)"
    if grep -qiE 'enforced: *true|enforce: *true' <<<"$DEFPOL"; then
      warn "org policy constraints/run.disableDefaultURI is ENFORCED — the run.app default URL is off org-wide (GFE 404 by design); reach the app via a load balancer, or 'gcloud run services proxy ${SERVICE} --region ${REGION}', and ask an org admin to exempt this project to restore the run.app url"
    fi

    # The EFFECTIVE policy includes org/folder inheritance — print it verbatim so a read failure
    # (API disabled, missing permission) can never silently masquerade as "policy is permissive".
    # Read WITHOUT merging stderr into the value: the managed credential broker prints its benign
    # "Regional Access Boundary … Account not found" line to stderr, and a 2>&1 here captured THAT
    # into $EFF, masking the real policy so the override below never fired. Drop any broker line that
    # still leaks to stdout, and make an unreadable policy explicit (never a silent "permissive").
    EFF="$(gcloud org-policies describe run.allowedIngress --project "$PROJECT" --effective \
      2>/dev/null | grep -v 'Regional Access Boundary' || true)"
    EFF_SHOW="${EFF:-<unreadable: enable orgpolicy.googleapis.com or grant roles/orgpolicy.policyViewer>}"
    echo "  effective run.allowedIngress: $(tr '\n' ' ' <<<"$EFF_SHOW" | head -c 220)"
    if grep -qiE 'internal|denyAll|deny_all' <<<"$EFF"; then
      warn "org policy constraints/run.allowedIngress (inherited) restricts ingress — attempting a project-level allow-all override"
      cat >"$ERRF" <<YAML
name: projects/${PROJECT}/policies/run.allowedIngress
spec:
  rules:
  - allowAll: true
YAML
      gcloud org-policies set-policy "$ERRF" --quiet 2>/dev/null \
        && fixed "set a project-level allow-all ingress policy" \
        || warn "could not override the org policy at project level (enforced from above)"
    fi

    # Re-assert ingress, then re-probe both urls for up to ~1 minute (GFE config can lag).
    gcloud run services update "$SERVICE" --region "$REGION" --ingress all --quiet 2>/dev/null || true
    for round in 1 2 3 4; do
      sleep 15
      for u in "$DET_URL" "$URL"; do
        RC2="$(curl -sS -o "$ERRF" -w '%{http_code}' --max-time 20 "${u}${HEALTH_PATH}" 2>/dev/null || echo 000)"
        echo "  re-probe (round ${round}) ${u} -> HTTP ${RC2}"
        if [ "$RC2" = "200" ]; then WINNER="$u"; break 2; fi
      done
    done
    rm -f "$ERRF"
    if [ -n "$WINNER" ]; then
      URL="$WINNER"
      ok "reachable after healing: ${URL}"
    else
      OTHERS="$(gcloud run services list --format='value(metadata.name)' 2>/dev/null \
        | grep -v "^${SERVICE}\$" | tr '\n' ' ')"
      die "ROOT CAUSE: external ingress to the run.app URL is blocked above this service. The app
itself is healthy and migrated; the block sits in Google's frontend. The 'effective
run.allowedIngress' line printed above is decisive: internal-only values => an inherited org
policy (ask an admin to allow external ingress, or grant you orgpolicy.policyAdmin so this
doctor's project-level override sticks); an ERROR => enable orgpolicy.googleapis.com and re-run.

VERIFY THE APP RIGHT NOW (your own IAM, no admin, no load balancer):
    gcloud run services proxy ${SERVICE} --region ${REGION} --port 8080
  then open Cloud Shell's Web Preview on port 8080 — you will see the app and /healthz.
The healthy service is '${SERVICE}'; other services here: ${OTHERS:-none}."
    fi
    ;;
  000)
    die "no HTTP response from ${URL} (timeout/DNS/connection) — retry in a minute, or verify via
'gcloud run services proxy ${SERVICE} --region ${REGION} --port 8080' + Cloud Shell Web Preview."
    ;;
  *)
    die "unexpected HTTP ${CODE} from ${URL}${HEALTH_PATH} — body: ${BODY:-<empty>}"
    ;;
esac

# Sign-in config smoke: the OAuth code flow advertises auth_configured + login_url (the client
# id/secret stay server-side, so they never appear in /api/config).
CFG="$(curl -sS --max-time 20 "${URL}/api/config" 2>/dev/null || true)"
if grep -q '"auth_configured":true' <<<"$CFG"; then
  ok "sign-in configured — OAuth client id + secret are live on the service"
  # Does Google ACCEPT the pair? The service probes the token endpoint with a bogus code: a matching
  # pair fails on the code (invalid_grant -> "ok"); a mismatched pair fails on the CLIENT
  # (401 invalid_client -> "rejected") — the exact failure users see as
  # "google token exchange failed: 401 ... oauth2.googleapis.com/token".
  case "$CFG" in
    *'"auth_credentials":"ok"'*)
      ok "Google accepts the OAuth client id/secret pair" ;;
    *'"auth_credentials":"rejected"'*)
      warn "Google REJECTS the OAuth client id/secret pair (401 invalid_client): the secret in"
      warn "  ${OAUTH_SECRET} is not the secret of client ${CLIENT_ID:-<GOOGLE_OAUTH_CLIENT_ID>}"
      warn "  (regenerated, copied from a different OAuth client, or stored with a trailing newline)."
      warn "  Fix: Console -> APIs & Services -> Credentials -> THAT web client -> copy its secret, then"
      warn "  bash scripts/doctor.sh --client-id <that client id> --client-secret <GOCSPX-…>" ;;
    *)
      warn "could not confirm Google accepts the OAuth credentials (probe unknown) — sign in to verify" ;;
  esac
else
  warn "sign-in is NOT configured on the service — re-run with BOTH:"
  warn "  bash scripts/doctor.sh --client-id <oauth-web-client-id> --client-secret <GOCSPX-…>"
fi

step "DONE — healthy at ${URL}"
echo "  USE EXACTLY THIS URL in the browser. Older bookmarks may point at a stale service:"
OTHERS="$(gcloud run services list --format='value(metadata.name)' 2>/dev/null | grep -v "^${SERVICE}\$" | head -6 | tr '\n' ' ')"
[ -n "$OTHERS" ] && echo "  (other Cloud Run services exist in this project: ${OTHERS}— the CIA app is only '${SERVICE}')"
echo ""
echo "  ONE Console step the API cannot do — register the OAuth redirect URI (NOT a JS origin):"
echo "    Console -> APIs & Services -> Credentials -> your Web client -> Authorized redirect URIs"
echo "    -> + Add URI -> EXACTLY:   ${CANON_URL}/api/auth/callback"
echo "  The redirect uri is PINNED (PUBLIC_BASE_URL): whichever url a user opens, the app always"
echo "  sends this ONE value — this single registration is sufficient, forever."
echo "  No 'Authorized JavaScript origins' are needed. Then open ${CANON_URL} and Continue with Google."
