#!/bin/bash
# Startup script for the PiClock.
#
# Starts the FastAPI backend under uvicorn and launches the pygame kiosk
# display (display/__main__.py). The pygame client is much lighter than a
# full browser — targeted at 512MB-RAM boards like the Pi Zero 2 W.
# The legacy PyQt4 launcher is preserved at legacy/startup.sh.orig for reference.
#
# Designed to be started from PiClock.desktop (autostart) or crontab:
#   @reboot sh /home/pi/PiClock/startup.sh

set -u

cd "$HOME/PiClock"

if [ -z "${DISPLAY:-}" ]; then
    export DISPLAY=:0
fi

# Wait for X/desktop unless overridden.
MSG="echo Waiting 45 seconds before starting"
DELAY="sleep 45"
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

PORT=8000
BACKEND_URL="http://127.0.0.1:${PORT}"

echo "Rotating log files...."
rm -f uvicorn.7.log
for i in 6 5 4 3 2 1; do
    mv -f "uvicorn.${i}.log" "uvicorn.$((i+1)).log" 2>/dev/null || true
done

echo "Starting PiClock backend (uvicorn) → logs: uvicorn.1.log"
uv run uvicorn backend.main:app --host 127.0.0.1 --port "${PORT}" --workers 1 \
    > uvicorn.1.log 2>&1 &
BACKEND_PID=$!

# Wait for /healthz (max 20s)
echo "Waiting for backend to become ready...."
for _ in $(seq 1 20); do
    if curl -fsS "${BACKEND_URL}/healthz" >/dev/null 2>&1; then
        break
    fi
    sleep 1
done

if ! curl -fsS "${BACKEND_URL}/healthz" >/dev/null 2>&1; then
    echo "Backend failed to start — tail of uvicorn.1.log:"
    tail -40 uvicorn.1.log
    kill "${BACKEND_PID}" 2>/dev/null
    exit 1
fi

echo "Launching pygame kiosk display…"
export PICLOCK_BACKEND="${BACKEND_URL}"
uv run python -m display

echo "Display exited; stopping backend."
kill "${BACKEND_PID}" 2>/dev/null
wait "${BACKEND_PID}" 2>/dev/null || true
