#!/bin/bash
# netwatch.sh — record the Pi's network state once a minute, so the next
# PiClock DNS wedge tells us whether the app is wedged or the Pi is offline.
#
#   netwatch.sh --info     one-off platform summary (model, OS, Wi-Fi, power)
#   netwatch.sh            append one status line to ~/netwatch.log
#
# Install as a cron job:
#   crontab -e
#   * * * * * /home/scott/PiClock/tools/netwatch.sh >/dev/null 2>&1
#
# Every check runs in a fresh process. If `dns=ok` while PiClock is logging
# "Temporary failure in name resolution", the wedge is inside the app process.
# If dns fails here too, the Pi itself has lost the network.

set -u

LOG="$HOME/netwatch.log"
STATE="$HOME/.netwatch.state"
PROBE_HOST="api.rainviewer.com"

iface() {
    local dev
    dev=$(ip route show default 2>/dev/null | awk '{for (i=1;i<NF;i++) if ($i=="dev") {print $(i+1); exit}}')
    echo "${dev:-wlan0}"
}

ok_fail() { if "$@" >/dev/null 2>&1; then echo ok; else echo FAIL; fi; }

throttled() {
    command -v vcgencmd >/dev/null 2>&1 || { echo n/a; return; }
    vcgencmd get_throttled 2>/dev/null | cut -d= -f2
}

info() {
    local IF; IF=$(iface)
    echo "model:        $(tr -d '\0' </proc/device-tree/model 2>/dev/null)"
    echo "os:           $(. /etc/os-release 2>/dev/null; echo "$PRETTY_NAME")"
    echo "kernel:       $(uname -r)"
    echo "glibc:        $(ldd --version 2>/dev/null | head -1)"
    echo "booted:       $(uptime -s)"
    echo "memory:       $(free -m | awk '/^Mem:/{print $2" MB total, "$7" MB available"}')"
    echo "throttled:    $(throttled)   (0x0 = no undervoltage or throttling, ever since boot)"
    echo "interface:    $IF ($(cat /sys/class/net/"$IF"/operstate 2>/dev/null))"
    echo "wifi power:   $(iw dev "$IF" get power_save 2>/dev/null || echo n/a)"
    echo "network svc:  $(for s in NetworkManager dhcpcd systemd-networkd systemd-resolved; do
                            printf '%s=%s ' "$s" "$(systemctl is-active "$s" 2>/dev/null)"; done)"
    echo "resolv.conf:  $(ls -l /etc/resolv.conf | awk '{print $NF == "/etc/resolv.conf" ? "regular file" : "-> "$NF}')"
    sed 's/^/              /' /etc/resolv.conf
}

detail() {
    local IF; IF=$(iface)
    echo "---- detail $(date '+%F %T') ----"
    echo "## ip addr";   ip addr
    echo "## ip route";  ip route; ip -6 route
    echo "## resolv.conf ($(stat -Lc %y /etc/resolv.conf 2>/dev/null))"; cat /etc/resolv.conf
    echo "## wifi link"; iw dev "$IF" link 2>&1
    echo "## throttled"; throttled
    echo "## network service journal"
    journalctl -n 40 --no-pager -u NetworkManager -u dhcpcd 2>&1
    echo "## kernel wifi messages"
    journalctl -k -n 400 --no-pager 2>/dev/null | grep -iE 'brcm|wlan|mmc|under-voltage' | tail -30
    echo "---- end detail ----"
}

if [ "${1:-}" = "--info" ]; then
    info
    exit 0
fi

IF=$(iface)
GW=$(ip route show default 2>/dev/null | awk '{print $3; exit}')
DNS=$(awk '/^nameserver/{print $2}' /etc/resolv.conf 2>/dev/null | paste -sd, -)
APP=$(pgrep -f 'python -m display' | head -1)

# getent ahosts goes through getaddrinfo, the same call Python makes.
dns=$(ok_fail timeout 10 getent ahosts "$PROBE_HOST")

line="$(date '+%F %T') boot=$(uptime -s | cut -c1-16) app=${APP:-none}"
line+=" $IF=$(cat /sys/class/net/"$IF"/operstate 2>/dev/null)"
line+=" ip=$(ip -4 -o addr show dev "$IF" 2>/dev/null | awk '{print $4; exit}')"
line+=" gw=${GW:-none} ns=${DNS:-none}"
line+=" rc=$(stat -Lc %y /etc/resolv.conf 2>/dev/null | cut -c6-19 | tr ' ' T)"
line+=" ping_gw=$( [ -n "$GW" ] && ok_fail ping -c1 -W2 "$GW" || echo n/a)"
line+=" ping_ip=$(ok_fail ping -c1 -W2 1.1.1.1)"
line+=" dns=$dns throttled=$(throttled)"
echo "$line" >>"$LOG"

# Dump the full picture once, on the first failing minute of each outage.
prev=$(cat "$STATE" 2>/dev/null)
echo "$dns" >"$STATE"
if [ "$dns" = FAIL ] && [ "$prev" != FAIL ]; then
    detail >>"$LOG" 2>&1
fi

# Keep the log bounded (~one line a minute is ~2 MB a week).
if [ "$(wc -c <"$LOG")" -gt 5000000 ]; then
    tail -n 20000 "$LOG" >"$LOG.tmp" && mv "$LOG.tmp" "$LOG"
fi
