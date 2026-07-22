#!/usr/bin/env bash
# ============================================================
# Diagnose and repair the Hailo PCIe kernel module.
#   sudo bash scripts/hailoDriverFix.sh
#
# Symptom this addresses: hailort packages installed and
# hailo_platform importable, but hailo_pci not loaded and
# /dev/hailo0 missing. Almost always a DKMS build that did not
# run — or failed — against the currently booted kernel.
# ============================================================
if [ -z "${BASH_VERSION:-}" ]; then
    exec bash "$0" "$@"
fi
set -uo pipefail

if [ "$(id -u)" -ne 0 ]; then
    echo "Run with sudo: sudo bash scripts/hailoDriverFix.sh"
    exit 1
fi

section() { echo ""; echo "===== $1 ====="; }

KERNEL="$(uname -r)"
echo "Booted kernel: $KERNEL"

section "1. DKMS status"
if command -v dkms >/dev/null; then
    dkms status || true
else
    echo "dkms not installed"
fi

section "2. Is the module built for THIS kernel?"
find "/lib/modules/${KERNEL}" -name "hailo*.ko*" 2>/dev/null || echo "no hailo module under /lib/modules/${KERNEL}"
echo "--- kernel headers present? (needed to build) ---"
ls -d "/lib/modules/${KERNEL}/build" 2>/dev/null || echo "MISSING — install linux-headers for this kernel"

section "3. modprobe attempt (real error)"
modprobe hailo_pci 2>&1 || true
lsmod | grep -i hailo || echo "hailo_pci NOT loaded"
dmesg 2>/dev/null | grep -i hailo | tail -15

section "4. Rebuilding via DKMS"
if command -v dkms >/dev/null; then
    dkms autoinstall -k "$KERNEL" 2>&1 | tail -25 || true
else
    echo "skipped (no dkms)"
fi

section "5. Build log (if the rebuild failed)"
LOG="$(find /var/lib/dkms -name make.log -newermt '-10 minutes' 2>/dev/null | head -1)"
if [ -n "$LOG" ]; then
    echo "--- $LOG (last 40 lines) ---"
    tail -40 "$LOG"
else
    echo "no recent DKMS make.log found"
fi

section "6. Retry load"
modprobe hailo_pci 2>&1 || true
lsmod | grep -i hailo || echo "hailo_pci still NOT loaded"
ls -l /dev/hailo* 2>/dev/null || echo "/dev/hailo0 still missing"

section "7. Firmware / runtime check"
command -v hailortcli >/dev/null && hailortcli fw-control identify 2>&1 | head -20
echo "(if this reports a device, the accelerator is fully up)"

echo ""
echo "===== done — paste ALL output above ====="
