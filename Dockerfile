# syntax=docker/dockerfile:1
#
# Single Cloud Run service: the built Vite/React SPA served by the FastAPI app.
# Build for linux/amd64 and verify it runs locally before any deploy (§16):
#   docker buildx build --platform linux/amd64 -t cia:dev . && docker run -p 8080:8080 cia:dev
#
# NOTE (Stage 0): the app server `app.main:app` lands in Stage 1 (F1). This Dockerfile defines its
# target shape now; the final image becomes runnable when F1 merges.

# ---- Stage 1: build the SPA ----
FROM node:20-bookworm-slim AS frontend
WORKDIR /fe
RUN corepack enable
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY frontend/ ./
RUN pnpm build   # -> /fe/dist

# ---- Stage 2: runtime (FastAPI + static SPA) ----
FROM python:3.12-slim-bookworm AS runtime
ENV PYTHONUNBUFFERED=1 \
    PORT=8080 \
    LLM_MODE=live
WORKDIR /app
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
