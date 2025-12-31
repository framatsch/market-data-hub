FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

# Copy project files
COPY pyproject.toml .
# Install dependencies
RUN pip install --no-cache-dir .

COPY app/ ./app/

# Create non-root user
RUN useradd -m appuser
USER appuser

# Expose HTTP and MCP SSE ports
EXPOSE 8000 8001

# Default to HTTP mode, can be overridden to "mcp" or "both"
CMD ["python", "-m", "app.main", "http"]
