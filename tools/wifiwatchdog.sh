#!/bin/bash
# wifiwatchdog.sh — recover the Pi 3's Wi-Fi when it gets stuck.
#
# The Pi 3's BCM43430 radio can wedge so that NetworkManager never
# reassociates (Sep 24 2026: down 13 h until a manual reboot). NetworkManager
# can also give up on its own: on Sep 26 it read handshake timeouts as a wrong
# password, failed the connection with "no-secrets" and stopped autoconnecting
# for 85 min. Only an explicit "nmcli connection up" clears that block.
#
# Run as root once a minute; tools/pi-setup.sh installs it. It probes the
# gateway, not the internet, so an ISP outage doesn't trigger recovery.
#
#   gateway unreachable >=  5 min  ->  nmcli connection up, every 5 min
#   gateway unreachable >= 10 min  ->  reload the brcmfmac driver (once)
#   gateway unreachable >= 20 min  ->  reboot, unless up for less than 60 min
#
# Actions are logged to the journal:  journalctl -t wifiwatchdog
# DRY_RUN=1 logs what it would do instead of doing it.
# CONN=<name or uuid> overrides which NetworkManager profile to bring up.

set -u

IFACE=${IFACE:-wlan0}
STATE=${STATE:-/run/wifiwatchdog}   # tmpfs, so a reboot starts fresh
LOCK=${LOCK:-$STATE.lock}
RECONNECT_AFTER=300
RECONNECT_EVERY=300
RELOAD_AFTER=600
REBOOT_AFTER=1200
MIN_UPTIME=3600

log() { logger -t wifiwatchdog "$*"; }
act() { if [ "${DRY_RUN:-0}" = 1 ]; then log "DRY_RUN would run: $*"; else "$@"; fi; }

# The Wi-Fi profile for $IFACE, by UUID. After a "no-secrets" failure the
# device has no active connection, so look through the saved profiles.
wifi_conn() {
    if [ -n "${CONN:-}" ]; then echo "$CONN"; return; fi
    local uuid type ifname
    while IFS=: read -r uuid type; do
        [ "$type" = 802-11-wireless ] || continue
        ifname=$(nmcli -g connection.interface-name connection show "$uuid" 2>/dev/null)
        if [ -z "$ifname" ] || [ "$ifname" = "$IFACE" ]; then
            echo "$uuid"
            return
        fi
    done < <(nmcli -g UUID,TYPE connection show 2>/dev/null)
}

# Cron starts a run every minute; a slow nmcli or modprobe must not overlap
# with the next one.
exec 9>"$LOCK"
flock -n 9 || exit 0

gw=$(ip route show default dev "$IFACE" 2>/dev/null | awk '{print $3; exit}')
if [ -n "$gw" ] && ping -c1 -W3 "$gw" >/dev/null 2>&1; then
    if [ -f "$STATE" ]; then
        log "$IFACE recovered (gateway $gw reachable)"
        rm -f "$STATE"
    fi
    exit 0
fi

now=$(date +%s)
if [ -f "$STATE" ]; then
    read -r since reloaded reconnected <"$STATE"
    reconnected=${reconnected:-0}   # state files from before the reconnect step
else
    since=$now reloaded=0 reconnected=0
    log "$IFACE: gateway ${gw:-none} unreachable, starting outage clock"
fi
down=$((now - since))
uptime_s=$(cut -d. -f1 /proc/uptime)

if [ "$down" -ge "$REBOOT_AFTER" ] && [ "$uptime_s" -ge "$MIN_UPTIME" ]; then
    log "$IFACE down ${down}s, driver reload didn't help; rebooting"
    act systemctl reboot
elif [ "$down" -ge "$RELOAD_AFTER" ] && [ "$reloaded" = 0 ]; then
    log "$IFACE down ${down}s; reloading brcmfmac"
    # timeout: unloading can hang if the SDIO bus itself is wedged
    act timeout 60 modprobe -r brcmfmac_wcc brcmfmac
    act modprobe brcmfmac
    reloaded=1
elif [ "$down" -ge "$RECONNECT_AFTER" ] && [ $((now - reconnected)) -ge "$RECONNECT_EVERY" ]; then
    conn=$(wifi_conn)
    if [ -n "$conn" ]; then
        log "$IFACE down ${down}s; nmcli connection up $conn"
        act timeout 120 nmcli --wait 90 connection up "$conn" \
            || log "$IFACE: nmcli connection up failed (exit $?)"
    else
        log "$IFACE down ${down}s; no Wi-Fi profile found to bring up"
    fi
    reconnected=$now
fi

echo "$since $reloaded $reconnected" >"$STATE"
