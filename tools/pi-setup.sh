#!/bin/bash
# pi-setup.sh — one-time hardening for the Pi running PiClock.
#
# Run this ON THE PI (not the Mac):
#   ~/PiClock/tools/pi-setup.sh
#
# Does two idempotent things, safe to re-run:
#   1. Disables Wi-Fi power save in the NetworkManager profile (persists
#      across reboots). The Pi 3's brcmfmac chip has a known failure mode
#      where the radio powers down between packets and doesn't wake back
#      up cleanly — every socket call then fails instantly with
#      "Temporary failure in name resolution" until the Pi is rebooted.
#      That matches PiClock's DNS-wedge outages exactly.
#   2. Installs tools/netwatch.sh as a once-a-minute cron job, so the next
#      wedge (if any) leaves a record of whether the network was actually
#      down or something else happened.

set -u

log()  { echo "[pi-setup] $*"; }
fail() { echo "[pi-setup] ERROR: $*" >&2; exit 1; }

if [ "$(uname -s)" != "Linux" ]; then
    fail "this script is meant to run on the Pi, not the Mac"
fi

command -v nmcli >/dev/null 2>&1 || fail "nmcli not found — is NetworkManager installed?"

# ---- 1. disable Wi-Fi power save ------------------------------------------

IFACE=$(ip route show default 2>/dev/null | awk '{for (i=1;i<NF;i++) if ($i=="dev") {print $(i+1); exit}}')
IFACE=${IFACE:-wlan0}

CONN=$(nmcli -t -f NAME,DEVICE connection show --active | awk -F: -v d="$IFACE" '$2==d{print $1; exit}')
if [ -z "$CONN" ]; then
    fail "no active NetworkManager connection found on $IFACE — run 'nmcli connection show' and pass the name manually"
fi

CURRENT=$(nmcli -g 802-11-wireless.powersave connection show "$CONN" 2>/dev/null)
log "Wi-Fi connection: '$CONN' on $IFACE (current powersave setting: ${CURRENT:-unset})"

if [ "$CURRENT" = "2" ]; then
    log "power save already disabled in the saved profile — nothing to change"
else
    log "disabling power save (requires sudo)..."
    sudo nmcli connection modify "$CONN" 802-11-wireless.powersave 2 \
        || fail "nmcli modify failed"
    sudo nmcli connection up "$CONN" \
        || fail "nmcli connection up failed"
fi

LIVE=$(iw dev "$IFACE" get power_save 2>/dev/null)
log "live state: $LIVE"
case "$LIVE" in
    *off*) log "confirmed: power save is off" ;;
    *)     log "WARNING: expected 'Power save: off', got '$LIVE' — check manually" ;;
esac

# ---- 2. install the netwatch cron job -------------------------------------

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NETWATCH="$SCRIPT_DIR/netwatch.sh"
CRON_LINE="* * * * * $NETWATCH >/dev/null 2>&1"

if [ ! -x "$NETWATCH" ]; then
    fail "expected $NETWATCH to exist and be executable"
fi

if crontab -l 2>/dev/null | grep -qF "$NETWATCH"; then
    log "netwatch cron job already installed"
else
    log "installing netwatch cron job (logs to ~/netwatch.log)"
    (crontab -l 2>/dev/null; echo "$CRON_LINE") | crontab - \
        || fail "failed to install crontab entry"
fi

log "done. Check progress later with: tail -f ~/netwatch.log"
