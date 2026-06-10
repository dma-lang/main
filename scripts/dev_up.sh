#!/usr/bin/env bash
#
# Local dev bootstrap for Claude Code on the web (and any ephemeral dev container).
#
# The web sandbox is reclaimed on inactivity and restored from a base snapshot, which stops the
# Docker daemon and the pgvector Postgres (the catalogue data survives in the named docker volume).
# This script is the idempotent "make the dev stack ready again" button: it starts dockerd, brings
# up Postgres 16 + pgvector, ensures the `cia` (dev) and `cia_test` (pytest) databases exist and are
# migrated to head, and builds the SPA. Safe to re-run. It deliberately does NOT touch git — code is
# recovered with `git fetch && git reset --hard origin/<branch>` (see README/CLAUDE.md), never here.
#
# Usage:  scripts/dev_up.sh            # full bootstrap (docker + db + migrate + spa)
#         NO_SPA=1 scripts/dev_up.sh   # skip the SPA build (backend-only work)
#
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DB_BASE="postgresql+asyncpg://cia:cia@localhost:5432"

log() { printf '[dev_up] %s\n' "$*"; }

# 1) Docker daemon. The init script trips a ulimit restriction in the sandbox, so launch directly.
if ! docker info >/dev/null 2>&1; then
  log "starting dockerd..."
  nohup dockerd --host=unix:///var/run/docker.sock >/tmp/dockerd.log 2>&1 &
  for _ in $(seq 1 30); do docker info >/dev/null 2>&1 && break; sleep 1; done
fi
docker info >/dev/null 2>&1 || { log "dockerd failed to start; see /tmp/dockerd.log"; exit 1; }
log "docker ready"

# 2) Postgres 16 + pgvector (named volume persists the catalogue across reclaims).
docker compose -f "$REPO/docker-compose.dev.yml" up -d
log "waiting for postgres on :5432..."
for _ in $(seq 1 30); do
  PGPASSWORD=cia psql -h 127.0.0.1 -U cia -d cia -tAc "select 1" >/dev/null 2>&1 && break
  sleep 2
done
PGPASSWORD=cia psql -h 127.0.0.1 -U cia -d cia -tAc "select 1" >/dev/null 2>&1 \
  || { log "postgres did not become ready"; exit 1; }
log "postgres ready"

# 3) The pytest database is not in the volume — create it on demand (idempotent).
if ! PGPASSWORD=cia psql -h 127.0.0.1 -U cia -d postgres -tAc \
      "select 1 from pg_database where datname='cia_test'" | grep -q 1; then
  log "creating cia_test database"
  PGPASSWORD=cia psql -h 127.0.0.1 -U cia -d postgres -c "CREATE DATABASE cia_test OWNER cia" >/dev/null
fi

# 4) Migrate both control planes to head (additive, transactional; never on app startup — §5).
cd "$REPO/backend"
for db in cia cia_test; do
  log "alembic upgrade head -> $db"
  DATABASE_URL="$DB_BASE/$db" uv run alembic upgrade head >/dev/null
done

# 5) Build the SPA so the single-container layout (FastAPI serves frontend/dist) is exercised.
if [ "${NO_SPA:-0}" != "1" ]; then
  cd "$REPO/frontend"
  [ -d node_modules ] || { log "installing frontend deps"; pnpm install --frozen-lockfile >/dev/null 2>&1; }
  log "building SPA"
  pnpm build >/dev/null
fi

log "ready. start the server with:"
cat <<EOF
  cd $REPO/backend && \\
    DATABASE_URL=$DB_BASE/cia LLM_MODE=hermetic STATIC_DIR=$REPO/frontend/dist \\
    uv run uvicorn app.main:app --host 0.0.0.0 --port 8092
EOF
