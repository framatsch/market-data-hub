FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

# Copy uv from official image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# Copy project files
COPY pyproject.toml uv.lock ./

# Install dependencies with uv (production only, no dev/test deps)
RUN uv sync --frozen --no-dev

COPY app/ ./app/

# Create non-root user
RUN useradd -m appuser
USER appuser

# Expose HTTP and MCP SSE ports
EXPOSE 8000 8001

# Run both HTTP (8000) and MCP (8001) servers
CMD ["uv", "run", "python", "-m", "app.main", "both"]
