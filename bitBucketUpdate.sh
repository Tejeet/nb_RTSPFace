#!/usr/bin/env bash
# ============================================================
# Edge Face Capture — update & redeploy script
#
# Pulls the latest master branch, rebuilds both Docker images,
# restarts the stack, and removes the old (dangling) images.
#
# Usage:  ./bitBucketUpdate.sh
# ============================================================
set -euo pipefail

# Always run from the repository root (where this script lives).
cd "$(dirname "$0")"

echo "==> Current version: $(git log --oneline -1)"

echo "==> Pulling latest code from origin/master..."
git fetch origin master
git reset --hard origin/master
echo "==> Now at: $(git log --oneline -1)"

echo "==> Building images (backend + frontend)..."
docker compose build backend frontend

echo "==> Restarting stack with new images..."
docker compose up -d

echo "==> Removing old dangling images..."
docker image prune -f

echo "==> Waiting for backend to come up..."
sleep 5
docker compose ps

echo ""
echo "==> Last backend logs:"
docker logs efc-backend --tail 15 2>&1 || true

echo ""
echo "✔ Update complete. Dashboard: http://$(hostname -I 2>/dev/null | awk '{print $1}'):8080"
echo "  (Hard-refresh the browser with Ctrl+Shift+R to load the new frontend.)"
