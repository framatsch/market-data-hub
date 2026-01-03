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

# Expose HTTP and MCP SSE ports
EXPOSE 8000 8001

# Run both HTTP (8000) and MCP (8001) servers
CMD ["uv", "run", "python", "-m", "app.main", "both"]
