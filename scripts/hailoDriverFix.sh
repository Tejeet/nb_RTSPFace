#!/usr/bin/env bash
# ============================================================
# Diagnose and repair the Hailo PCIe kernel module.
#   sudo bash scripts/hailoDriverFix.sh
#
# Symptom this addresses: hailort packages installed and
# hailo_platform importable, but `modprobe hailo_pci` says the
# module does not exist for the booted kernel.
#
# Root cause it fixes: hailort-pcie-driver is an arch:all package
# that ships DKMS *source*. If dkms (or the kernel headers) are
# missing, no module is ever compiled and /dev/hailo0 never
# appears — with no error at install time.
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
have()    { command -v "$1" >/dev/null 2>&1; }

KERNEL="$(uname -r)"
echo "Booted kernel: $KERNEL"

section "1. What the driver package installed"
dpkg -L hailort-pcie-driver 2>/dev/null | grep -E "/usr/src|\.ko|dkms" | head -20 \
    || echo "hailort-pcie-driver not installed"
echo "--- DKMS source trees ---"
ls -d /usr/src/*hailo* 2>/dev/null || echo "none under /usr/src"

section "2. Build prerequisites"
have dkms && echo "dkms: $(dkms --version 2>&1 | head -1)" || echo "dkms: NOT INSTALLED  <-- blocks the build"
[ -d "/lib/modules/${KERNEL}/build" ] \
    && echo "headers: present (/lib/modules/${KERNEL}/build)" \
    || echo "headers: MISSING  <-- blocks the build"

section "3. Installing missing prerequisites"
NEED=""
have dkms || NEED="$NEED dkms"
[ -d "/lib/modules/${KERNEL}/build" ] || NEED="$NEED linux-headers-rpi-2712"
if [ -n "$NEED" ]; then
    echo "installing:$NEED"
    apt-get update -qq
    # shellcheck disable=SC2086
    apt-get install -y $NEED || echo "apt install failed"
else
    echo "nothing missing"
fi

section "4. Registering and building the module with DKMS"
BUILT=0
if have dkms; then
    for src in /usr/src/*hailo*; do
        [ -d "$src" ] || continue
        conf="$src/dkms.conf"
        [ -f "$conf" ] || { echo "$src has no dkms.conf, skipping"; continue; }
        NAME="$(sed -n 's/^PACKAGE_NAME=["'\'']*\([^"'\'' ]*\).*/\1/p' "$conf" | head -1)"
        VER="$(sed -n 's/^PACKAGE_VERSION=["'\'']*\([^"'\'' ]*\).*/\1/p' "$conf" | head -1)"
        [ -n "$NAME" ] && [ -n "$VER" ] || { echo "cannot parse $conf"; continue; }
        echo "--- $NAME/$VER from $src ---"
        dkms add -m "$NAME" -v "$VER" 2>&1 | tail -3
        dkms build -m "$NAME" -v "$VER" -k "$KERNEL" 2>&1 | tail -15
        dkms install -m "$NAME" -v "$VER" -k "$KERNEL" --force 2>&1 | tail -5
        BUILT=1
    done
    [ "$BUILT" -eq 1 ] || echo "no hailo DKMS source found to build"
    echo "--- dkms status ---"
    dkms status 2>/dev/null | grep -i hailo || echo "(no hailo entry)"
else
    echo "dkms still unavailable — cannot build"
fi

section "5. Build log (only shown if something failed)"
LOG="$(find /var/lib/dkms -name make.log -newermt '-15 minutes' 2>/dev/null | head -1)"
if [ -n "$LOG" ]; then
    echo "--- $LOG (last 40 lines) ---"
    tail -40 "$LOG"
else
    echo "no recent make.log (usually means the build succeeded or never ran)"
fi

section "6. Loading the module"
depmod -a "$KERNEL" 2>/dev/null || true
modprobe hailo_pci 2>&1 || true
lsmod | grep -i hailo || echo "hailo_pci NOT loaded"
ls -l /dev/hailo* 2>/dev/null || echo "/dev/hailo0 still missing"
dmesg 2>/dev/null | grep -i hailo | tail -10

section "7. Runtime check"
CLI=""
for c in hailortcli /usr/local/bin/hailortcli /opt/hailo/bin/hailortcli; do
    have "$c" && { CLI="$c"; break; }
done
if [ -n "$CLI" ]; then
    echo "--- $CLI fw-control identify ---"
    "$CLI" fw-control identify 2>&1 | head -20
else
    echo "hailortcli not found in PATH (sudo's secure_path may exclude /usr/local/bin)"
    echo "try as your normal user: hailortcli fw-control identify"
fi

echo ""
echo "===== done — paste ALL output above ====="
