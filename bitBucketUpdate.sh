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
# This script uses bash syntax. Running it as `sh bitBucketUpdate.sh` would use
# dash on Raspberry Pi OS and fail, so re-exec under bash however it was started.
if [ -z "${BASH_VERSION:-}" ]; then
    exec bash "$0" "$@"
fi

set -euo pipefail

# Always run from the repository root (where this script lives).
cd "$(dirname "$0")"

# Files must end up owned by the human, not root, even when run under sudo —
# Docker creates missing bind-mount directories as root and would otherwise
# lock the user out of ./models on the next non-sudo run.
OWNER_UID="${SUDO_UID:-$(id -u)}"
OWNER_GID="${SUDO_GID:-$(id -g)}"

own() {
    # Give a path back to the invoking user; ignored if we lack the rights.
    [ -e "$1" ] && chown -R "${OWNER_UID}:${OWNER_GID}" "$1" 2>/dev/null || true
}

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
own .env

# ---- Pre-download InsightFace models (one-time; ~300 MB) ----
MODEL_PACK="buffalo_l"
MODEL_URL="https://github.com/deepinsight/insightface/releases/download/v0.7/${MODEL_PACK}.zip"
MODEL_DIR="models/models/${MODEL_PACK}"

# Repair ownership before touching anything: an earlier `docker compose up`
# may have created ./models as root, which makes even `test -f` fail here.
if [ -d models ] && [ ! -w models ]; then
    echo "==> ./models is not writable (created by Docker as root) — fixing owner..."
    if ! chown -R "${OWNER_UID}:${OWNER_GID}" models 2>/dev/null; then
        echo "    Needs elevation; re-run once as: sudo ./bitBucketUpdate.sh"
        exit 1
    fi
fi
mkdir -p "${MODEL_DIR}" models/hailo

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
    own models
    echo "==> Models ready:"
    ls -lh "${MODEL_DIR}"
else
    echo "==> Models already present in ${MODEL_DIR} — skipping download."
fi

# ---- Get images: pull the CI-built image for this exact commit, ----
# ---- build locally only when it isn't published (yet).          ----
export IMAGE_TAG="$(git rev-parse HEAD)"
echo "==> Looking for prebuilt images tagged $(git rev-parse --short HEAD)..."
if $COMPOSE pull backend frontend; then
    echo "==> Prebuilt images pulled from GHCR — no local build needed."
else
    echo "==> Prebuilt images not available (CI still running, or first push)."
    echo "==> Building locally instead..."
    $COMPOSE build backend frontend
fi

echo "==> Restarting stack with new images..."
$COMPOSE up -d

echo "==> Removing old images..."
docker image prune -f
# Tagged images from previous updates are not "dangling" — remove any tag of
# our two repos that is not the one now running.
for repo in ghcr.io/tejeet/nb_rtspface-backend ghcr.io/tejeet/nb_rtspface-frontend; do
    docker images "$repo" --format '{{.Repository}}:{{.Tag}}' \
        | grep -v ":${IMAGE_TAG}$" \
        | xargs -r docker rmi 2>/dev/null || true
done

echo "==> Waiting for backend to come up..."
sleep 5
$COMPOSE ps

echo ""
echo "==> Last backend logs:"
docker logs efc-backend --tail 15 2>&1 || true

echo ""
echo "✔ Update complete. Dashboard: http://$(hostname -I 2>/dev/null | awk '{print $1}'):8080"
echo "  (Hard-refresh the browser with Ctrl+Shift+R to load the new frontend.)"
