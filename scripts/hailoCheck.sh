#!/usr/bin/env bash
# ============================================================
# Hailo-8 diagnostic — run on the Pi host (not inside Docker)
#   bash scripts/hailoCheck.sh
# Verifies the four things the Hailo backend needs:
#   1. PCIe device visible   2. hailo_pci driver bound
#   3. /dev/hailo0 node      4. HailoRT userspace
# ============================================================
set +e

section() { echo ""; echo "===== $1 ====="; }

section "1. PCIe device"
lspci | grep -i hailo || echo "NOT FOUND on the PCIe bus"

section "2. Kernel driver"
lsmod | grep -i hailo || echo "hailo_pci module NOT loaded"
echo "--- driver binding ---"
for dev in /sys/bus/pci/devices/*; do
    if grep -qi "1e60" "$dev/vendor" 2>/dev/null; then
        echo "device: $(basename "$dev")"
        echo "driver: $(basename "$(readlink -f "$dev/driver" 2>/dev/null)" 2>/dev/null || echo 'NONE BOUND')"
    fi
done
dmesg 2>/dev/null | grep -i hailo | tail -10

section "3. Device node"
ls -l /dev/hailo* 2>/dev/null || echo "/dev/hailo0 MISSING (driver not loaded or failed to probe)"

section "4. HailoRT userspace"
command -v hailortcli >/dev/null && hailortcli fw-control identify 2>&1 | head -20 \
    || echo "hailortcli NOT installed"
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

section "7. In-container view"
docker exec efc-backend python -c \
    "import hailo_platform, os; print('HailoRT OK', hailo_platform.__version__); print('/dev/hailo0:', os.path.exists('/dev/hailo0'))" 2>&1 \
    | head -5 || echo "(container not running, or HailoRT not installed inside it)"

echo ""
echo "===== done — paste ALL output above ====="
