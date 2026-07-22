#!/usr/bin/env bash
# ============================================================
# Download precompiled Hailo-8 HEF models from the public
# Hailo Model Zoo bucket into models/models/hailo/.
#
#   bash scripts/fetchHailoModels.sh [MODELZOO_VERSION]
#
# The bucket is versioned and Hailo adds/moves builds over time, so if a
# download 404s, browse the Model Zoo release page for the current version
# and pass it as the argument:
#   https://github.com/hailo-ai/hailo_model_zoo
# ============================================================
# Uses bash arrays; re-exec under bash if started with sh/dash.
if [ -z "${BASH_VERSION:-}" ]; then
    exec bash "$0" "$@"
fi

set -uo pipefail

cd "$(dirname "$0")/.."

VERSION="${1:-v2.13.0}"
BASE="https://hailo-model-zoo.s3.eu-west-2.amazonaws.com/ModelZoo/Compiled/${VERSION}/hailo8"
DEST="models/models/hailo"
mkdir -p "$DEST"

# Detection is the model that matters; recognition is optional (CPU by default).
MODELS=(
    "scrfd_10g.hef"
    "arcface_mobilefacenet.hef"
)

echo "==> Hailo Model Zoo ${VERSION} -> ${DEST}"
FAILED=0
for model in "${MODELS[@]}"; do
    if [ -f "${DEST}/${model}" ]; then
        echo "  = ${model} already present, skipping"
        continue
    fi
    echo "  ↓ ${model}"
    if curl -fL --progress-bar -o "${DEST}/${model}.part" "${BASE}/${model}"; then
        mv "${DEST}/${model}.part" "${DEST}/${model}"
    else
        rm -f "${DEST}/${model}.part"
        echo "  ✗ ${model} NOT available at ${BASE}/${model}"
        FAILED=1
    fi
done

echo ""
ls -lh "$DEST" 2>/dev/null | tail -n +2 || true

if [ "$FAILED" -ne 0 ]; then
    echo ""
    echo "Some downloads failed. Check the current Model Zoo version and retry:"
    echo "  bash scripts/fetchHailoModels.sh v2.14.0"
    echo "Only scrfd_10g.hef is required — arcface is optional (CPU is the default)."
    exit 1
fi

echo ""
echo "✔ Models ready. Set INFERENCE_BACKEND=hailo (or pick Hailo-8 on the"
echo "  Settings page), then restart the backend."
