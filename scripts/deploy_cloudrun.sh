#!/usr/bin/env bash
#
# One-run, self-healing Cloud Run deploy for the Capability Intelligence Agent.
#
# HUMAN-GATED (CLAUDE.md §8/§10): running this performs paid, prod-affecting actions. It is meant
# to be run BY AN OPERATOR after `terraform apply` has provisioned the infrastructure (service
# accounts, Cloud SQL, Artifact Registry, secrets). It deploys the APP only; it never creates
# infra, never edits IAM, never touches secrets.
#
# Self-healing properties (every step is safe to re-run; the whole script is ONE command):
#   * preflight fails fast with a readable reason (wrong project, missing API, no docker auth)
#   * network steps retry with exponential backoff (build pulls, pushes, gcloud calls)
#   * base-image pulls fall back to the GCR mirror when Docker Hub rate-limits (429)
#   * the image is deployed BY DIGEST (immutable), never by tag
#   * the migration Job runs TO COMPLETION before any traffic moves (never on app startup)
#   * the new revision starts with --no-traffic; it gets traffic only after /healthz passes
#   * on ANY failure after the revision exists, traffic stays/returns on the previous revision
#     (auto-rollback) and the script exits nonzero
#
# Usage:
#   PROJECT_ID=digital-maturity-assessor REGION=us-central1 ./scripts/deploy_cloudrun.sh
# Optional env:
#   SERVICE=cia            Cloud Run service name
#   MIGRATE_JOB=cia-migrate  Cloud Run Job name for the one-shot migration
#   REPO_AR=cia            Artifact Registry docker repo name
#   CANARY_PERCENT=""      e.g. 10 -> canary at 10%, then verify, then 100 (default: direct 100)
#
set -euo pipefail

PROJECT_ID="${PROJECT_ID:?set PROJECT_ID}"
REGION="${REGION:-us-central1}"
SERVICE="${SERVICE:-cia}"
MIGRATE_JOB="${MIGRATE_JOB:-cia-migrate}"
REPO_AR="${REPO_AR:-cia}"
CANARY_PERCENT="${CANARY_PERCENT:-}"
GIT_SHA="$(git rev-parse --short HEAD)"
IMAGE_BASE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO_AR}/cia"
IMAGE_TAG="${IMAGE_BASE}:${GIT_SHA}"

log()  { printf '\n[deploy] %s\n' "$*"; }
fail() { printf '\n[deploy] FATAL: %s\n' "$*" >&2; exit 1; }

# retry <name> <max> <cmd...>: exponential backoff 2,4,8,16,... seconds; transient-only retries.
retry() {
  local name="$1" max="$2"; shift 2
  local n=1
  until "$@"; do
    if (( n >= max )); then fail "$name failed after $max attempts"; fi
    local wait=$(( 2 ** n ))
    log "$name failed (attempt $n/$max) — retrying in ${wait}s"
    sleep "$wait"; ((n++))
  done
}

# ---------------------------------------------------------------- 0. preflight (fail fast)
log "preflight"
command -v gcloud >/dev/null || fail "gcloud CLI not installed"
command -v docker >/dev/null || fail "docker not installed"
[ -n "$(git status --porcelain)" ] && fail "working tree is dirty — deploy only committed code"
gcloud config set project "$PROJECT_ID" --quiet >/dev/null
ACTIVE_ACCOUNT="$(gcloud auth list --filter=status:ACTIVE --format='value(account)')"
[ -n "$ACTIVE_ACCOUNT" ] || fail "no active gcloud account (run: gcloud auth login)"
log "account=${ACTIVE_ACCOUNT} project=${PROJECT_ID} region=${REGION} sha=${GIT_SHA}"
for api in run.googleapis.com artifactregistry.googleapis.com; do
  gcloud services list --enabled --filter="name:${api}" --format='value(name)' | grep -q . \
    || fail "API ${api} is not enabled (terraform should have enabled it)"
done
gcloud run jobs describe "$MIGRATE_JOB" --region "$REGION" >/dev/null 2>&1 \
  || fail "migration job '${MIGRATE_JOB}' not found (terraform provisions it)"
retry "docker auth" 3 gcloud auth configure-docker "${REGION}-docker.pkg.dev" --quiet

# ---------------------------------------------------------------- 1. build (mirror fallback)
build() { docker buildx build --platform linux/amd64 "$@" -t "$IMAGE_TAG" . ; }
log "building ${IMAGE_TAG}"
if ! retry "image build (docker.io bases)" 2 build; then true; fi
if ! docker image inspect "$IMAGE_TAG" >/dev/null 2>&1; then
  log "docker.io pull blocked/rate-limited — falling back to the GCR mirror of the same images"
  retry "image build (mirror bases)" 3 build \
    --build-arg NODE_IMAGE=mirror.gcr.io/library/node:20-bookworm-slim \
    --build-arg PYTHON_IMAGE=mirror.gcr.io/library/python:3.12-slim-bookworm
fi

# ---------------------------------------------------------------- 2. push + resolve digest
log "pushing"
retry "image push" 4 docker push "$IMAGE_TAG"
DIGEST="$(gcloud artifacts docker images describe "$IMAGE_TAG" --format='value(image_summary.digest)')"
[ -n "$DIGEST" ] || fail "could not resolve pushed image digest"
IMAGE_DIGEST="${IMAGE_BASE}@${DIGEST}"
log "image by digest: ${IMAGE_DIGEST}"

# ---------------------------------------------------------------- 3. migrate TO COMPLETION
log "running one-shot migration job (advisory-locked, at-head no-op) BEFORE any traffic moves"
retry "migrate job image update" 3 gcloud run jobs update "$MIGRATE_JOB" \
  --region "$REGION" --image "$IMAGE_DIGEST" --quiet
retry "migrate job execute" 2 gcloud run jobs execute "$MIGRATE_JOB" \
  --region "$REGION" --wait --quiet
log "migration complete"

# ---------------------------------------------------------------- 4. deploy with NO traffic
PREV_REVISION="$(gcloud run services describe "$SERVICE" --region "$REGION" \
  --format='value(status.latestReadyRevisionName)' 2>/dev/null || true)"
log "previous ready revision: ${PREV_REVISION:-<none>}"
retry "service deploy (no traffic)" 3 gcloud run deploy "$SERVICE" \
  --region "$REGION" --image "$IMAGE_DIGEST" --no-traffic --quiet
NEW_REVISION="$(gcloud run services describe "$SERVICE" --region "$REGION" \
  --format='value(status.latestCreatedRevisionName)')"
log "new revision (0%% traffic): ${NEW_REVISION}"

# ---------------------------------------------------------------- 5. smoke the new revision
SERVICE_URL="$(gcloud run services describe "$SERVICE" --region "$REGION" --format='value(status.url)')"
smoke() {
  # Tag-routed URL hits the new revision while it still has 0% of real traffic.
  gcloud run services update-traffic "$SERVICE" --region "$REGION" \
    --set-tags "smoke=${NEW_REVISION}" --quiet >/dev/null
  local tag_url="${SERVICE_URL/https:\/\//https://smoke---}"
  local body; body="$(curl -fsS --max-time 20 "${tag_url}/healthz")" || return 1
  echo "$body" | grep -q '"status":"ok"' || return 1
  echo "$body" | grep -q '"db":"ok"' || return 1
}
if ! retry "healthz smoke on new revision" 5 smoke; then
  log "smoke FAILED — leaving 100%% of traffic on ${PREV_REVISION:-current}; new revision gets none"
  exit 1
fi
log "smoke passed on ${NEW_REVISION}"

# ---------------------------------------------------------------- 6. promote (canary optional)
promote() { gcloud run services update-traffic "$SERVICE" --region "$REGION" "$@" --quiet; }
if [ -n "$CANARY_PERCENT" ] && [ -n "$PREV_REVISION" ]; then
  log "canary: ${CANARY_PERCENT}%% to ${NEW_REVISION}"
  retry "canary traffic" 3 promote --to-revisions "${NEW_REVISION}=${CANARY_PERCENT}"
  if ! retry "healthz during canary" 5 curl -fsS --max-time 20 "${SERVICE_URL}/healthz" >/dev/null; then
    log "canary FAILED — rolling traffic back to ${PREV_REVISION}"
    promote --to-revisions "${PREV_REVISION}=100" || true
    exit 1
  fi
fi
log "promoting ${NEW_REVISION} to 100%%"
if ! retry "traffic promote" 3 promote --to-latest; then
  [ -n "$PREV_REVISION" ] && promote --to-revisions "${PREV_REVISION}=100" || true
  fail "promotion failed — traffic restored to ${PREV_REVISION:-previous}"
fi

# ---------------------------------------------------------------- 7. verify serving revision
if ! retry "final healthz" 5 curl -fsS --max-time 20 "${SERVICE_URL}/healthz" >/dev/null; then
  log "post-promote health FAILED — rolling back to ${PREV_REVISION}"
  [ -n "$PREV_REVISION" ] && promote --to-revisions "${PREV_REVISION}=100" || true
  exit 1
fi
log "DEPLOYED ${SERVICE} -> ${NEW_REVISION} (${IMAGE_DIGEST}) and serving healthily"
