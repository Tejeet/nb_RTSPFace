#!/usr/bin/env bash
# ============================================================
# NPU diagnostic — run on the Radxa Cubie A7Z host (not in Docker)
# Collects everything needed to decide how to enable NPU inference.
# Usage:  bash scripts/npuCheck.sh
# ============================================================
set +e

section() { echo ""; echo "===== $1 ====="; }

section "Board / OS"
cat /proc/device-tree/model 2>/dev/null; echo ""
uname -a
grep PRETTY_NAME /etc/os-release

section "NPU device nodes"
ls -l /dev/galcore /dev/vipcore /dev/npu* 2>/dev/null || echo "none found"

section "NPU kernel driver"
lsmod | grep -i -E "galcore|vipcore|npu|vha" || echo "no NPU module loaded"
dmesg 2>/dev/null | grep -i -E "galcore|verisilicon|vip|npu" | tail -10

section "NPU load/debug nodes"
ls -l /sys/kernel/debug/gc /sys/kernel/debug/rknpu 2>/dev/null || echo "none (or debugfs not mounted)"
ls -d /sys/class/devfreq/*npu* 2>/dev/null

section "Vendor userspace libraries"
find /usr /opt /lib -maxdepth 4 \( -name "libtim-vx*" -o -name "libGAL*" -o -name "libVSC*" \
    -o -name "libOpenVX*" -o -name "libVIPlite*" -o -name "libawnn*" -o -name "*viplite*" \) 2>/dev/null \
    | head -20 || true

section "Vendor packages"
dpkg -l 2>/dev/null | grep -i -E "npu|tim-vx|verisilicon|viplite|awnn|vip-" || echo "no NPU packages installed"
apt-cache search npu 2>/dev/null | head -10

section "Python NPU runtimes"
python3 -c "import onnxruntime; print('onnxruntime', onnxruntime.__version__, onnxruntime.get_available_providers())" 2>/dev/null \
    || echo "onnxruntime not installed on host (that's fine)"
python3 -c "import tim" 2>/dev/null && echo "tim-vx python bindings present"

echo ""
echo "===== done — paste ALL output above ====="
