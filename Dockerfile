FROM python:3.11-slim

WORKDIR /app

# Install system dependencies if needed (e.g. curl for healthcheck)
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

# Copy project files
COPY pyproject.toml .
# Install dependencies
RUN pip install --no-cache-dir .

COPY app app/

# Create non-root user
RUN useradd -m appuser
USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
