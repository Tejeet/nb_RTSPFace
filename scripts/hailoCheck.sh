#!/usr/bin/env bash
# ============================================================
# Hailo-8 diagnostic — run on the Pi host (not inside Docker)
#   bash scripts/hailoCheck.sh
# Verifies the four things the Hailo backend needs:
#   1. PCIe device visible   2. hailo_pci driver bound
#   3. /dev/hailo0 node      4. HailoRT userspace
# ============================================================
if [ -z "${BASH_VERSION:-}" ]; then
    exec bash "$0" "$@"
fi

set +e

section() { echo ""; echo "===== $1 ====="; }

section "1. PCIe device"
lspci | grep -i hailo || echo "NOT FOUND on the PCIe bus"

section "2. Kernel driver"
echo "booted kernel: $(uname -r)"
lsmod | grep -i hailo || echo "hailo_pci module NOT loaded"
echo "--- dkms (module must be built for the BOOTED kernel) ---"
if command -v dkms >/dev/null; then
    dkms status 2>/dev/null | grep -i hailo || echo "no hailo dkms entry"
else
    echo "dkms NOT INSTALLED — an arch:all driver package cannot build without it"
fi
# `find` exits 0 even when it matches nothing, so test the output, not the status.
KO="$(find "/lib/modules/$(uname -r)" -name "hailo*.ko*" 2>/dev/null)"
[ -n "$KO" ] && echo "$KO" || echo "no hailo .ko under the booted kernel's modules"
echo "--- driver binding ---"
for dev in /sys/bus/pci/devices/*; do
    if grep -qi "1e60" "$dev/vendor" 2>/dev/null; then
        echo "device: $(basename "$dev")"
        # readlink -f canonicalises even non-existent paths, so test the symlink
        # itself — otherwise an unbound device misreports as driver "driver".
        if [ -L "$dev/driver" ]; then
            echo "driver: $(basename "$(readlink -f "$dev/driver")")"
        else
            echo "driver: NONE BOUND"
        fi
    fi
done
dmesg 2>/dev/null | grep -i hailo | tail -10

section "3. Device node"
ls -l /dev/hailo* 2>/dev/null || echo "/dev/hailo0 MISSING (driver not loaded or failed to probe)"

section "4. HailoRT userspace"
# Explicit if: `a && b | head || c` swallows the failure branch.
if command -v hailortcli >/dev/null; then
    echo "--- hailortcli fw-control identify ---"
    hailortcli fw-control identify 2>&1 | head -20
else
    echo "hailortcli NOT installed"
fi
echo "--- python bindings (host) ---"
python3 -c "import hailo_platform; print('hailo_platform', hailo_platform.__version__)" 2>/dev/null \
    || echo "hailo_platform NOT importable on host"
echo "--- packages ---"
dpkg -l 2>/dev/null | grep -i hailo || echo "no hailo debs installed"

section "5. PCIe link speed (Hailo-8 wants Gen3 x1+)"
HAILO_ADDR=$(lspci | grep -i hailo | awk '{print $1}')
[ -n "$HAILO_ADDR" ] && sudo lspci -vv -s "$HAILO_ADDR" 2>/dev/null | grep -E "LnkCap|LnkSta" \
    || echo "(run with sudo to see link status)"

section "6. Compiled models present?"
ls -lh models/models/hailo/*.hef 2>/dev/null || echo "no .hef files in models/models/hailo/"

section "7. Python ABI of the host HailoRT bindings"
# The container runs Python 3.12; a compiled _pyhailort .so built for another
# Python version cannot be reused there. This prints which one you have.
echo "host python: $(python3 --version 2>&1)"
find /usr/lib/python3/dist-packages/hailo_platform /usr/lib/python3*/site-packages/hailo_platform \
     -name "*.so" 2>/dev/null | head -5
echo "--- available versions in apt ---"
apt-cache policy python3-hailort 2>/dev/null | head -8

section "8. In-container view"
docker exec efc-backend python -c \
    "import hailo_platform, os; print('HailoRT OK', hailo_platform.__version__); print('/dev/hailo0:', os.path.exists('/dev/hailo0'))" 2>&1 \
    | head -5 || echo "(container not running, or HailoRT not installed inside it)"

echo ""
echo "===== done — paste ALL output above ====="
