# LLM Gateway v1.3 - Dockerfile
# ==============================
# Multi-stage build for minimal image size

# Build stage
FROM python:3.11-slim as builder

WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Production stage
FROM python:3.11-slim as production

# Labels
LABEL maintainer="OpenClaw Team"
LABEL version="1.3.0"
LABEL description="LLM Gateway - Kostenoptimiertes AI-Routing"

# Create non-root user
RUN groupadd -r gateway && useradd -r -g gateway gateway

# Set working directory
WORKDIR /app

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy application code
COPY --chown=gateway:gateway . .

# Create data directory
RUN mkdir -p /app/data && chown gateway:gateway /app/data

# Environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV CACHE_DIR=/app/data
ENV HOST=0.0.0.0
ENV PORT=8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Switch to non-root user
USER gateway

# Expose port
EXPOSE 8000

# Run the application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
