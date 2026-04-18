# PiClock Web Rewrite Plan

## Context

PiClock is a Raspberry Pi kiosk clock/weather/radar display. It currently runs on Python 2 + PyQt4 — both end-of-life — and has no local development story: you need a Pi with a display to run it at all. The goal is to rewrite it as a **FastAPI backend + vanilla HTML/CSS/JS frontend** displayed via Chromium in kiosk mode. This gives:

- Local dev: `uvicorn` + browser, no Pi required
- Testability: FastAPI TestClient + pytest for all backend logic
- Familiar stack: FastAPI, standard web APIs
- Proper fullscreen kiosk: Chromium `--kiosk` eliminates all Qt window-management issues
- Python 3 throughout

---

## Target Architecture

```
Browser (Chromium --kiosk)
   ↕  HTTP + SSE
FastAPI backend  →  Tomorrow.io / OWM / RainViewer / local temp sensor
   ↕
Config-*.py  (existing files reused via importlib)
```

### Backend: FastAPI (Python 3)
- Fetches and caches weather + radar metadata
- Serves the frontend as static files from `/`
- Pushes updates to frontend via **Server-Sent Events** (SSE) — no WebSocket complexity

### Frontend: Vanilla HTML/CSS/JS (no build step)
- **Leaflet.js** for radar maps (CDN) — replaces all the QPainter tile-stitching code
- Custom RainViewer tile layer on Leaflet (consumes `/api/radar` from backend)
- Plain JS for clock, weather widgets, forecast panel

---

## File Structure

```
PiClock/
  backend/
    main.py         FastAPI app: mounts static files, SSE endpoint, triggers refreshes
    weather.py      Tomorrow.io + OWM fetch logic (ported from PyQtPiClock.py ~lines 400-1100)
    radar.py        RainViewer metadata fetch (ported from Radar class ~lines 1733-1750)
    config.py       Loads existing Clock/Config-*.py via importlib, exposes as dataclass
    models.py       Pydantic models for all API responses
    tests/
      test_weather.py
      test_radar.py
      test_config.py
  frontend/
    index.html      Single page, two CSS-toggled views
    css/
      clock.css     Layout + clock styling
    js/
      app.js        Entry: SSE listener, auto-refresh wiring (no interactive input)
      clock.js      Analog (CSS rotate) or digital clock
      weather.js    Current conditions + forecast panel (9 slots)
      radar.js      Leaflet maps + RainViewer tile animation (2 configurable maps)
  Clock/            KEEP — config files live here, PyQtPiClock.py left intact
  startup.sh        Updated: uvicorn + chromium kiosk (replaces python PyQtPiClock launch)
  pyproject.toml    see Recommended Packages section (managed by uv)
```

---

## Recommended Third-Party Packages

| Package | Why |
|---------|-----|
| `fastapi` + `uvicorn[standard]` | Backend framework + ASGI server |
| `httpx` | Async HTTP client for weather/radar API calls |
| `sse-starlette` | Server-Sent Events with zero boilerplate — replaces manual async generator SSE code |
| `astral` | Sunrise/sunset times + moon phase calculations — replaces the complex existing math in PyQtPiClock.py |
| `jinja2` | Server-side HTML templates; FastAPI includes it via `python-multipart`. Backend renders weather/forecast HTML fragments |
| `metar` | METAR observation parsing (optional, only if Config.METAR is set) |

**Frontend (CDN, no build step):**
| Library | Why |
|---------|-----|
| [Leaflet.js](https://leafletjs.com/) | Interactive maps for radar panels |
| [leaflet-rainviewer](https://github.com/mwasil/Leaflet.RainViewer) | Official RainViewer Leaflet plugin — handles frame fetching, animation, and tile URL construction automatically; replaces all of the custom tile-stitching code |
| [HTMX](https://htmx.org/) | Polls `/api/weather-fragment` and `/api/forecast-fragment` every N minutes and swaps HTML in-place — no manual `fetch()` + JSON parsing in JS for weather data |

With HTMX + Jinja2, the only JS needed is: clock ticking (JS `Date`) and Leaflet radar maps. Everything else is server-rendered HTML fragments refreshed by HTMX attributes.

---

## Background Image

The current app supports a custom background image via `Config.background` (file path). In the web version:
- Backend serves it at `/static/bg/<filename>` from the configured path
- `index.html` applies it as a CSS variable: `body { background-image: var(--bg-image); }`
- Backend injects the URL into the Jinja2 template at render time
- Fallback: solid black if no background configured

---

## Backend API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Serves `frontend/index.html` |
| GET | `/static/*` | Frontend assets + existing weather icons + background image |
| GET | `/api/config` | Config settings the frontend needs (location, units, icon set, radar params, labels) |
| GET | `/api/weather` | Current conditions (temp, feels-like, icon, description, pressure, humidity, wind, sunrise, sunset, moon phase) |
| GET | `/api/forecast` | `{hourly: [...3 periods], daily: [...6 days]}` |
| GET | `/weather-fragment` | Jinja2-rendered HTML for current conditions (consumed by HTMX) |
| GET | `/forecast-fragment` | Jinja2-rendered HTML for forecast panel (consumed by HTMX) |
| GET | `/api/radar` | RainViewer frame paths `{host, past: [{time, path}]}` — frontend builds tile URLs |
| GET | `/api/inside-temp` | Proxy to `localhost:48213/temp` |
| GET | `/api/events` | SSE stream — emits `weather`, `radar`, `inside-temp` events on schedule |

---

## Frontend Layout (single, static)

No keyboard, mouse, or buttons are attached — the display is purely passive. One fixed layout:

**Left column:** weather panel (current conditions) · 2 stacked Leaflet radar maps
**Center:** clock (analog or digital per config)
**Right column:** 9-slot forecast panel (3 hourly + 6 daily)

No view switching, no interactive elements, no keyboard shortcuts.

---

## Key Implementation Notes

### Config loading (`backend/config.py`)
Use `importlib.util.spec_from_file_location` to import the user's existing `Clock/Config-*.py`. No forced migration. Active config determined by symlink or env var `PICLOCK_CONFIG`.

### Weather (`backend/weather.py`)
Port the fetch logic from `PyQtPiClock.py`:
- Tomorrow.io: lines 1451–1484 (3 separate calls → combine into one response)
- OWM: lines 1402–1441
- METAR: lines 1490–1510 (optional, keep as-is with `metar` library)
- Background refresh via `asyncio` task started at app startup
- Use `astral` library for sunrise/sunset and moon phase (replaces existing calculation code)

### Radar (`backend/radar.py`)
Thin proxy — just re-fetches `https://api.rainviewer.com/public/weather-maps.json` and returns it. Frontend handles tile URL construction and Leaflet animation directly. This removes all QPainter tile-stitching code.

### Radar frontend (`frontend/js/radar.js`)
```js
// Leaflet map per radar config entry (2 maps in single layout)
// Use leaflet-rainviewer plugin — it calls RainViewer API directly
// or point it at /api/radar to use the backend proxy
// Plugin handles frame animation loop natively
```

### SSE (`backend/main.py`)
```python
# asyncio.Queue per connected client
# Background tasks push {"event": "weather"} / {"event": "radar"} on schedule
# Frontend listeners call fetch('/api/weather') etc. on receipt
```

### Kiosk (`startup.sh` additions)
```bash
cd ~/PiClock
uv run uvicorn backend.main:app --host 127.0.0.1 --port 8000 --workers 1 &
BACKEND_PID=$!
sleep 3
chromium-browser --kiosk --noerrdialogs --disable-infobars \
  --disable-session-crashed-bubble --app=http://localhost:8000
kill $BACKEND_PID
```

---

## Critical Files to Modify / Create

| File | Action |
|------|--------|
| `backend/main.py` | **Create** |
| `backend/weather.py` | **Create** (port from PyQtPiClock.py lines 400-1100) |
| `backend/radar.py` | **Create** (port from Radar.getRadarFrames, lines 1733-1750) |
| `backend/config.py` | **Create** |
| `backend/models.py` | **Create** |
| `frontend/index.html` | **Create** |
| `frontend/css/clock.css` | **Create** |
| `frontend/js/*.js` | **Create** |
| `startup.sh` | **Modify** (lines 115-132: replace python launch with uvicorn + chromium) |
| `pyproject.toml` | **Create** (`uv init` + add deps) |
| `Clock/Config-*.py` | **Keep unchanged** |
| `Clock/PyQtPiClock.py` | **Keep unchanged** (can be removed later) |

---

## Testing

```bash
# Local dev (no Pi needed)
uv run uvicorn backend.main:app --reload
open http://localhost:8000

# Unit tests
uv run pytest backend/tests/

# Backend API exploration
open http://localhost:8000/docs   # FastAPI auto-docs
```

Test cases to write:
- `test_weather.py`: mock httpx responses, verify normalization (metric/imperial, icon mapping)
- `test_radar.py`: mock RainViewer API, verify frame path extraction
- `test_config.py`: load `Config-Example.py`, verify all fields parsed

---

## Implementation Order

1. `uv init` + `pyproject.toml` + `backend/config.py` (config loading)
2. `backend/models.py` + `backend/main.py` skeleton (static + Jinja2 serving, `/api/config`)
3. `backend/weather.py` + `/api/weather` + `/weather-fragment` + `/forecast-fragment`
4. `backend/radar.py` + `/api/radar`
5. `frontend/index.html` + `clock.js` (working clock locally in browser)
6. Jinja2 templates for weather + forecast fragments; wire up HTMX polling
7. `frontend/js/radar.js` (Leaflet + leaflet-rainviewer plugin)
8. SSE (`/api/events`) for radar refresh trigger
9. Background image: serve from `/static/bg/`, inject URL in template
10. `startup.sh` kiosk update
11. `backend/tests/` test suite