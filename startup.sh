#!/bin/bash
# PiClock kiosk launcher.
#
# Single pygame process — no uvicorn, no browser. All data fetching
# (weather, radar, alerts) runs in the same event loop as the UI.
# Targeted at 512 MB boards like the Pi Zero 2 W.
#
# Designed to be started from PiClock.desktop (autostart) or crontab:
#   @reboot sh /home/pi/PiClock/startup.sh

set -u

cd "$HOME/PiClock"

if [ -z "${DISPLAY:-}" ]; then
    export DISPLAY=:0
fi

# Wait for X/desktop unless overridden.
MSG="echo Waiting 20 seconds before starting"
DELAY="sleep 20"
if [ "${1:-}" = "-n" ] || [ "${1:-}" = "--no-sleep" ] || [ "${1:-}" = "--no-delay" ]; then
    MSG=""
    DELAY=""
    shift
fi
if [ "${1:-}" = "-d" ] || [ "${1:-}" = "--delay" ]; then
    MSG="echo Waiting $2 seconds before starting"
    DELAY="sleep $2"
    shift 2
fi

$MSG
eval $DELAY

zenity --info --timeout 3 --text "Starting PiClock......." >/dev/null 2>&1 &

# Stop screen blanking
echo "Disabling screen blanking...."
xset s off        >/dev/null 2>&1 || true
xset -dpms        >/dev/null 2>&1 || true
xset s noblank    >/dev/null 2>&1 || true

# Hide mouse cursor
if ! pgrep unclutter >/dev/null 2>&1; then
    unclutter >/dev/null 2>&1 &
fi

echo "Rotating log files...."
rm -f piclock.7.log
for i in 6 5 4 3 2 1; do
    mv -f "piclock.${i}.log" "piclock.$((i+1)).log" 2>/dev/null || true
done

echo "Launching PiClock (pygame) → logs: piclock.1.log"
exec uv run python -m display > piclock.1.log 2>&1
