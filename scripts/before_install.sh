#!/bin/bash
set -e

echo "[BeforeInstall] 📦 Preparing environment..."

DEPLOY_DIR="/home/ubuntu/tarafirst_user_management"
SOURCE_ENV="/home/ubuntu/.env"
TARGET_ENV="$DEPLOY_DIR/.env"

# 1. Ensure deployment folder exists
if [ ! -d "$DEPLOY_DIR" ]; then
    echo "[BeforeInstall] Creating deployment folder: $DEPLOY_DIR"
    mkdir -p "$DEPLOY_DIR"
    chown ubuntu:ubuntu "$DEPLOY_DIR"
fi

# 2. Copy .env to deployment folder
if [ -f "$SOURCE_ENV" ]; then
    echo "[BeforeInstall] Copying .env to deployment folder..."
    cp "$SOURCE_ENV" "$TARGET_ENV"
    chown ubuntu:ubuntu "$TARGET_ENV"
    chmod 600 "$TARGET_ENV"
else
    echo "❌ Source .env not found at $SOURCE_ENV"
    exit 1
fi

echo "[BeforeInstall] ✅ Environment prepared successfully."
