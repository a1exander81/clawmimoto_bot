# Multi-stage Docker build for ClawForge
FROM python:3.11-slim AS builder

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Freqtrade and dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Runtime stage
FROM python:3.11-slim

WORKDIR /app

# Copy Python packages from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application code
COPY clawforge/ ./clawforge/
COPY configs/ ./configs/
COPY strategies/ ./strategies/ 2>/dev/null || true

# Create directories for data
RUN mkdir -p /app/user_data/logs /app/user_data/strategies /app/generated/cards

# Environment
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8080/api/v1/ping', timeout=5)" || exit 1

# Entrypoint
CMD ["freqtrade", "trade", "--config", "/app/configs/config.json"]
