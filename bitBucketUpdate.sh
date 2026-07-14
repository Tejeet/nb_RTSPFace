#!/usr/bin/env bash
# ============================================================
# Edge Face Capture — update & redeploy script
#
# 1. Pulls the latest master branch
# 2. Regenerates .env from .env.example
# 3. Pre-downloads the InsightFace models into ./models
#    (mounted into the container, so the backend never
#    spends startup time downloading)
# 4. Rebuilds both images, restarts the stack
# 5. Removes old dangling images
#
# Usage:  ./bitBucketUpdate.sh
# ============================================================
set -euo pipefail

# Always run from the repository root (where this script lives).
cd "$(dirname "$0")"

# ---- Pick the compose command (plugin or standalone binary) ----
if docker compose version >/dev/null 2>&1; then
    COMPOSE="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
    COMPOSE="docker-compose"
else
    echo "ERROR: neither 'docker compose' nor 'docker-compose' found."
    echo "Install the plugin with: sudo apt-get install docker-compose-plugin"
    exit 1
fi
echo "==> Using: $COMPOSE"

echo "==> Current version: $(git log --oneline -1)"

echo "==> Pulling latest code from origin/master..."
git fetch origin master
git reset --hard origin/master
echo "==> Now at: $(git log --oneline -1)"

# ---- Regenerate .env (source of truth is the committed .env.example) ----
echo "==> Refreshing .env from .env.example..."
cp .env.example .env

# ---- Pre-download InsightFace models (one-time; ~300 MB) ----
MODEL_PACK="buffalo_l"
MODEL_URL="https://github.com/deepinsight/insightface/releases/download/v0.7/${MODEL_PACK}.zip"
MODEL_DIR="models/models/${MODEL_PACK}"

if [ ! -f "${MODEL_DIR}/det_10g.onnx" ] || [ ! -f "${MODEL_DIR}/w600k_r50.onnx" ]; then
    echo "==> Downloading ${MODEL_PACK} models (~300 MB, one-time)..."
    mkdir -p "${MODEL_DIR}"
    curl -L --fail --progress-bar -o "/tmp/${MODEL_PACK}.zip" "${MODEL_URL}"
    python3 -m zipfile -e "/tmp/${MODEL_PACK}.zip" "${MODEL_DIR}/"
    rm -f "/tmp/${MODEL_PACK}.zip"
    # Some archives nest a folder; flatten it if so.
    if [ -d "${MODEL_DIR}/${MODEL_PACK}" ]; then
        mv "${MODEL_DIR}/${MODEL_PACK}"/* "${MODEL_DIR}/"
        rmdir "${MODEL_DIR}/${MODEL_PACK}"
    fi
    echo "==> Models ready:"
    ls -lh "${MODEL_DIR}"
else
    echo "==> Models already present in ${MODEL_DIR} — skipping download."
fi

echo "==> Building images (backend + frontend)..."
$COMPOSE build backend frontend

echo "==> Restarting stack with new images..."
$COMPOSE up -d

echo "==> Removing old dangling images..."
docker image prune -f

echo "==> Waiting for backend to come up..."
sleep 5
$COMPOSE ps

echo ""
echo "==> Last backend logs:"
docker logs efc-backend --tail 15 2>&1 || true

echo ""
echo "✔ Update complete. Dashboard: http://$(hostname -I 2>/dev/null | awk '{print $1}'):8080"
echo "  (Hard-refresh the browser with Ctrl+Shift+R to load the new frontend.)"
