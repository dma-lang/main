# syntax=docker/dockerfile:1
#
# Single Cloud Run service: the built Vite/React SPA served by the FastAPI app.
# Build for linux/amd64 and verify it runs locally before any deploy (§16):
#   docker buildx build --platform linux/amd64 -t cia:dev . && docker run -p 8080:8080 cia:dev
#
# Base images are ARG-overridable so a Docker Hub rate limit (429) never blocks a build — the
# deploy script falls back to the GCR/ECR mirrors of the SAME official images, pinned by the
# same tags (self-healing build, no content change):
#   --build-arg NODE_IMAGE=mirror.gcr.io/library/node:20-bookworm-slim \
#   --build-arg PYTHON_IMAGE=mirror.gcr.io/library/python:3.12-slim-bookworm
ARG NODE_IMAGE=node:20-bookworm-slim
ARG PYTHON_IMAGE=python:3.12-slim-bookworm

# ---- Stage 1: build the SPA ----
FROM ${NODE_IMAGE} AS frontend
WORKDIR /fe
# Optional extra CAs (corporate/sandbox TLS proxies): drop a PEM into build-ca/ and both stages
# trust it; the committed dir is empty (a missing file is only a node warning, never a failure).
COPY build-ca/ /tmp/build-ca/
ENV NODE_EXTRA_CA_CERTS=/tmp/build-ca/extra-ca.crt
RUN corepack enable   # pnpm version comes from package.json "packageManager" (pinned, reproducible)
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY frontend/ ./
RUN pnpm build   # -> /fe/dist

# ---- Stage 2: runtime (FastAPI + static SPA) ----
FROM ${PYTHON_IMAGE} AS runtime
ENV PYTHONUNBUFFERED=1 \
    PORT=8080 \
    LLM_MODE=live
WORKDIR /app
# Same optional CA hook as stage 1 (appended to the system bundle only when a PEM is present).
# uv/pip are pointed at the SYSTEM store (uv otherwise uses its bundled roots and would ignore
# the appended CA); these are safe defaults in clean environments — the system store is standard.
COPY build-ca/ /tmp/build-ca/
RUN if [ -s /tmp/build-ca/extra-ca.crt ]; then \
      cat /tmp/build-ca/extra-ca.crt >> /etc/ssl/certs/ca-certificates.crt; \
    fi
ENV UV_NATIVE_TLS=true \
    SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \
    PIP_CERT=/etc/ssl/certs/ca-certificates.crt
RUN pip install --no-cache-dir uv
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev
COPY backend/ ./
COPY config/ ./config/
COPY --from=frontend /fe/dist ./static
# Least-privilege: run as non-root. App binds 0.0.0.0:$PORT and handles SIGTERM (graceful drain).
RUN useradd -m appuser && chown -R appuser /app
USER appuser
EXPOSE 8080
CMD ["sh", "-c", "uv run uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
