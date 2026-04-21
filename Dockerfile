# Multi-stage Docker build for ClawForge MTF Bot
FROM python:3.13-slim AS builder

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    git \
    curl \
    libffi-dev \
    libssl-dev \
    pkg-config \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip setuptools wheel
RUN pip install --no-cache-dir -r requirements.txt

# Runtime stage
FROM python:3.13-slim

WORKDIR /app

# Copy Python packages from builder
COPY --from=builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application code
COPY clawforge/ ./clawforge/
COPY strategies/ ./strategies/

# Create directories for data
RUN mkdir -p /app/user_data/logs \
    /app/user_data/strategies \
    /app/user_data/data \
    /app/generated/cards \
    /app/generated-cards

# Environment
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Asia/Singapore

# Health check: verify service process is running (reads /proc, no extra deps)
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python3 -c "import glob; cmds=' '.join(open(p+'/cmdline','rb').read().decode(errors='ignore').replace('\\x00',' ') for p in glob.glob('/proc/[0-9]*')); (('freqtrade' in cmds) or ('telegram_ui' in cmds)) or exit(1)"

# Default: run both services via supervisord-like script
# But we'll use docker-compose to run them as separate services
CMD ["freqtrade", "trade", "--config", "/app/configs/config.json", "--logfile", "/app/user_data/logs/clawforge.log"]
