#!/bin/bash
# Deploy ClawForge to production VPS via SSH
# Usage: ./deploy/prod.sh

set -e

echo "🚀 Deploying ClawForge to production..."

# Config
VPS_HOST="${VPS_HOST:-your-vps-ip}"
VPS_USER="${VPS_USER:-root}"
DEPLOY_DIR="/opt/clawforge"
SERVICE_NAME="clawforge"

# 1. Build Docker image locally
echo "[1/4] Building Docker image..."
docker build -t clawforge:${GITHUB_SHA:-latest} .

# 2. Save to tar for transfer
echo "[2/4] Packaging image..."
docker save clawforge:latest -o clawforge-image.tar

# 3. Transfer to VPS
echo "[3/4] Uploading to VPS..."
scp clawforge-image.tar ${VPS_USER}@${VPS_HOST}:/tmp/
ssh ${VPS_USER}@${VPS_HOST} "docker load -i /tmp/clawforge-image.tar"

# 4. Restart service
echo "[4/4] Restarting service..."
ssh ${VPS_USER}@${VPS_HOST} "
  cd ${DEPLOY_DIR}
  docker-compose down
  docker-compose up -d
  docker image prune -f
"

echo "✅ Deployed successfully!"
echo "Check logs: ssh ${VPS_USER}@${VPS_HOST} 'docker logs -f ${SERVICE_NAME}'"
