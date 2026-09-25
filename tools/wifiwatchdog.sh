#!/bin/bash
# wifiwatchdog.sh — recover the Pi 3's Wi-Fi when it gets stuck.
#
# The Pi 3's BCM43430 radio can wedge so that NetworkManager never
# reassociates (Sep 24 2026: down 13 h until a manual reboot). Run as root
# once a minute; tools/pi-setup.sh installs it. It probes the gateway, not
# the internet, so an ISP outage doesn't trigger recovery.
#
#   gateway unreachable >= 10 min  ->  reload the brcmfmac driver (once)
#   gateway unreachable >= 20 min  ->  reboot, unless up for less than 60 min
#
# Actions are logged to the journal:  journalctl -t wifiwatchdog
# DRY_RUN=1 logs what it would do instead of doing it.

set -u

IFACE=${IFACE:-wlan0}
STATE=${STATE:-/run/wifiwatchdog}   # tmpfs, so a reboot starts fresh
RELOAD_AFTER=600
REBOOT_AFTER=1200
MIN_UPTIME=3600

log() { logger -t wifiwatchdog "$*"; }
act() { if [ "${DRY_RUN:-0}" = 1 ]; then log "DRY_RUN would run: $*"; else "$@"; fi; }

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
    read -r since reloaded <"$STATE"
else
    since=$now reloaded=0
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
fi

echo "$since $reloaded" >"$STATE"
