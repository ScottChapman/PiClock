#!/bin/bash
# pi-setup.sh — one-time hardening for the Pi running PiClock.
#
# Run this ON THE PI (not the Mac):
#   ~/PiClock/tools/pi-setup.sh
#
# Does four idempotent things, safe to re-run:
#   1. Disables Wi-Fi power save in the NetworkManager profile (persists
#      across reboots).
#   2. Installs tools/netwatch.sh as a once-a-minute cron job, so every
#      outage leaves a record of the Pi's network state.
#   3. Makes the systemd journal persistent (Raspberry Pi OS ships it
#      volatile), so logs from before a reboot survive.
#   4. Installs tools/wifiwatchdog.sh as a root cron job that re-activates
#      the Wi-Fi connection, then reloads the driver, then reboots, when the
#      Wi-Fi stays down. PiClock's "DNS wedge" outages were the Pi's Wi-Fi
#      staying down until someone rebooted it.
#      Re-run this script after changing wifiwatchdog.sh to reinstall it.

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

# ---- 3. persistent journal ------------------------------------------------

# Sorts after the vendor's 40-rpi-volatile-storage.conf, so it wins.
JOURNAL_CONF=/etc/systemd/journald.conf.d/persistent.conf
if [ -f "$JOURNAL_CONF" ]; then
    log "persistent journal already configured"
else
    log "making the journal persistent (requires sudo)..."
    sudo mkdir -p "$(dirname "$JOURNAL_CONF")" \
        && printf '[Journal]\nStorage=persistent\n' | sudo tee "$JOURNAL_CONF" >/dev/null \
        && sudo systemctl restart systemd-journald \
        && sudo journalctl --flush \
        || fail "failed to configure the persistent journal"
fi

# ---- 4. install the Wi-Fi watchdog ----------------------------------------

# Root runs a root-owned copy, not the user-writable one in the checkout.
WATCHDOG_SRC="$SCRIPT_DIR/wifiwatchdog.sh"
WATCHDOG_BIN=/usr/local/sbin/piclock-wifiwatchdog
WATCHDOG_CRON=/etc/cron.d/piclock-wifiwatchdog

[ -f "$WATCHDOG_SRC" ] || fail "expected $WATCHDOG_SRC to exist"
log "installing Wi-Fi watchdog to $WATCHDOG_BIN (requires sudo)..."
sudo install -m 755 -o root -g root "$WATCHDOG_SRC" "$WATCHDOG_BIN" \
    && echo "* * * * * root $WATCHDOG_BIN >/dev/null 2>&1" | sudo tee "$WATCHDOG_CRON" >/dev/null \
    && sudo chmod 644 "$WATCHDOG_CRON" \
    || fail "failed to install the Wi-Fi watchdog"

log "done. Check progress later with: tail -f ~/netwatch.log"
log "watchdog actions: journalctl -t wifiwatchdog"
