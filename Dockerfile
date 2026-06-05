FROM node:20-alpine AS node-builder

WORKDIR /build

# Frontend sources are added by the admin-ui-frontend change. Keep this stage
# no-op-safe until then so backend-only Docker builds continue to work.
RUN mkdir -p /build/admin/dist

FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

# Copy uv from official image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# Create non-root user first
RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser

# Copy project files
COPY --chown=appuser:appuser pyproject.toml uv.lock ./

# Install dependencies with uv (production only, no dev/test deps)
RUN uv sync --frozen --no-dev

COPY --chown=appuser:appuser app/ ./app/
COPY --from=node-builder --chown=appuser:appuser /build/admin/dist ./app/static/admin/
RUN mkdir -p /app/data

VOLUME ["/app/data"]

# Expose HTTP API (8000) and MCP SSE (8001) ports
EXPOSE 8000 8001

# Run both servers
CMD ["uv", "run", "python", "-m", "app.main"]
