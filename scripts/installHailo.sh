#!/usr/bin/env bash
# ============================================================
# Install the Hailo-8 driver + HailoRT on Raspberry Pi OS.
#   sudo bash scripts/installHailo.sh
# Installs the host side only. The HailoRT *Python wheel* for the
# container still has to be downloaded manually from the Hailo
# Developer Zone into backend/vendor/ (account required).
# ============================================================
if [ -z "${BASH_VERSION:-}" ]; then
    exec bash "$0" "$@"
fi
set -uo pipefail

if [ "$(id -u)" -ne 0 ]; then
    echo "Run with sudo: sudo bash scripts/installHailo.sh"
    exit 1
fi

echo "===== available hailo packages ====="
apt-get update -qq
apt-cache search hailo | sort || true
echo ""

# hailo-all is the Raspberry Pi metapackage (driver + firmware + HailoRT +
# Python bindings). Fall back to the individual packages if it is absent.
if apt-cache show hailo-all >/dev/null 2>&1; then
    echo "===== installing hailo-all ====="
    apt-get install -y hailo-all
else
    echo "hailo-all not in the repos for this release; trying components..."
    apt-get install -y hailort hailo-dkms hailofw python3-hailort || {
        echo ""
        echo "Could not install from apt. This Pi runs $(. /etc/os-release; echo "$PRETTY_NAME")."
        echo "If the packages are missing for this release, either:"
        echo "  * switch to Raspberry Pi OS Bookworm (best-supported for Hailo), or"
        echo "  * install HailoRT manually from https://hailo.ai/developer-zone/"
        exit 1
    }
fi

echo ""
echo "===== verifying ====="
modprobe hailo_pci 2>/dev/null || true
lsmod | grep -i hailo || echo "hailo_pci still not loaded — a reboot is required"
ls -l /dev/hailo* 2>/dev/null || echo "/dev/hailo0 not present yet — reboot required"

echo ""
echo "✔ Host packages installed. Now:"
echo "   1. sudo reboot"
echo "   2. bash scripts/hailoCheck.sh        # expect /dev/hailo0 present"
echo "   3. bash scripts/fetchHailoModels.sh  # download the .hef models"
echo "   4. copy the HailoRT cp312 aarch64 wheel into backend/vendor/"
echo "   5. uncomment the /dev/hailo0 device line in docker-compose.yml"
echo "   6. set INFERENCE_BACKEND=hailo, then ./bitBucketUpdate.sh"
