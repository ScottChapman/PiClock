"""FastAPI application: serves the PiClock web UI."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sse_starlette.sse import EventSourceResponse

from . import config as config_module
from . import radar as radar_module
from . import weather as weather_module
from .models import ConfigResponse, MarkerModel, RadarMapModel, RadarResponse, WeatherResponse
from .radar_render import RadarRenderer

log = logging.getLogger("piclock")

BACKEND_DIR = Path(__file__).resolve().parent
REPO_ROOT = BACKEND_DIR.parent
STATIC_DIR = BACKEND_DIR / "static"
TEMPLATES_DIR = BACKEND_DIR / "templates"


RADAR_RENDER_SIZE = (512, 512)
RADAR_FRAME_LIMIT = 6


class AppState:
    def __init__(self) -> None:
        self.settings = config_module.load()
        self.http: httpx.AsyncClient | None = None
        self.weather: WeatherResponse | None = None
        self.radar: RadarResponse | None = None
        self.subscribers: set[asyncio.Queue[str]] = set()
        self._tasks: list[asyncio.Task] = []
        self.renderers: list[RadarRenderer] = [
            RadarRenderer(
                cfg,
                size=RADAR_RENDER_SIZE,
                google_api_key=self.settings.google_api_key,
            )
            for cfg in self.settings.radars
        ]

    async def start(self) -> None:
        self.http = httpx.AsyncClient(timeout=15.0)
        await self._refresh_weather()
        await self._refresh_radar()
        self._tasks.append(asyncio.create_task(self._weather_loop()))
        self._tasks.append(asyncio.create_task(self._radar_loop()))

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
        if self.http is not None:
            await self.http.aclose()

    async def _refresh_weather(self) -> None:
        try:
            self.weather = await weather_module.fetch(self.settings, self.http)
            await self._broadcast("weather")
        except Exception:
            log.exception("weather refresh failed")

    async def _refresh_radar(self) -> None:
        try:
            self.radar = await radar_module.fetch(self.http)
            await self._prerender_frames()
            await self._broadcast("radar")
        except Exception:
            log.exception("radar refresh failed")

    def _active_frames(self) -> list:
        if self.radar is None:
            return []
        return list(self.radar.past[-RADAR_FRAME_LIMIT:])

    async def _prerender_frames(self) -> None:
        """Render and cache every frame for every radar; drop stale ones."""
        if not self.renderers or self.radar is None or self.http is None:
            return
        frames = self._active_frames()
        keep_times = {f.time for f in frames}
        tasks = []
        for r in self.renderers:
            for f in frames:
                tasks.append(r.render_frame(self.http, self.radar.host, f.path, f.time))
        # Gather is fine — tiles-per-frame are serial inside render_frame, but
        # different frames/renderers run concurrently.
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        for r in self.renderers:
            r.prune(keep_times)

    async def _weather_loop(self) -> None:
        interval = max(60, self.settings.weather_refresh_minutes * 60)
        while True:
            await asyncio.sleep(interval)
            await self._refresh_weather()

    async def _radar_loop(self) -> None:
        interval = max(60, self.settings.radar_refresh_minutes * 60)
        while True:
            await asyncio.sleep(interval)
            await self._refresh_radar()

    async def _broadcast(self, event: str) -> None:
        for q in list(self.subscribers):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    state = AppState()
    app.state.app_state = state
    await state.start()
    try:
        yield
    finally:
        await state.stop()


app = FastAPI(title="PiClock", lifespan=lifespan)

STATIC_DIR.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR, follow_symlink=True), name="static")
# Background image served directly from repo root
app.mount("/bg", StaticFiles(directory=REPO_ROOT), name="bg")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


_CARDINALS = ("N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
              "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW")


def _wind_cardinal(deg: float) -> str:
    idx = int((deg % 360) / 22.5 + 0.5) % 16
    return _CARDINALS[idx]


def _time_of(iso: str) -> str:
    from datetime import datetime
    try:
        return datetime.fromisoformat(iso).strftime("%I:%M %p").lstrip("0")
    except Exception:
        return iso


templates.env.globals["wind_cardinal"] = _wind_cardinal
templates.env.globals["time_of"] = _time_of


def _state(request: Request) -> AppState:
    return request.app.state.app_state


def _config_response(state: AppState) -> ConfigResponse:
    s = state.settings
    radars = [
        RadarMapModel(
            center=r.center,
            zoom=r.zoom,
            satellite=r.satellite,
            markers=[MarkerModel(location=m.location, color=m.color, size=m.size) for m in r.markers],
        )
        for r in s.radars
    ]
    return ConfigResponse(
        location=s.location,
        metric=s.metric,
        wind_degrees=s.wind_degrees,
        icons=s.icons,
        textcolor=s.textcolor,
        digital=s.digital,
        digitalformat=s.digitalformat,
        clockUTC=s.clockUTC,
        radar_refresh_minutes=s.radar_refresh_minutes,
        weather_refresh_minutes=s.weather_refresh_minutes,
        background_url=f"/bg/{s.background}" if s.background else "",
        radars=radars,
        labels={
            "pressure": s.labels.pressure,
            "humidity": s.labels.humidity,
            "wind": s.labels.wind,
            "gusting": s.labels.gusting,
            "feelslike": s.labels.feelslike,
            "precip1hr": s.labels.precip1hr,
            "today": s.labels.today,
            "sunrise": s.labels.sunrise,
            "sunset": s.labels.sunset,
            "moonphase": s.labels.moonphase,
            "rain": s.labels.rain,
            "snow": s.labels.snow,
        },
    )


@app.get("/healthz", response_class=PlainTextResponse)
def healthz() -> str:
    return "ok"


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    state = _state(request)
    cfg = _config_response(state)
    units = _units(state)
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"cfg": cfg, "units": units},
    )


def _units(state: AppState) -> dict[str, str]:
    metric = state.settings.metric
    return {
        "temp": "°C" if metric else "°F",
        "speed": "km/h" if metric else "mph",
        "precip": "mm" if metric else "in",
        "pressure": "hPa",
    }


@app.get("/api/config", response_model=ConfigResponse)
async def api_config(request: Request) -> ConfigResponse:
    return _config_response(_state(request))


@app.get("/api/weather", response_model=WeatherResponse)
async def api_weather(request: Request) -> WeatherResponse | JSONResponse:
    state = _state(request)
    if state.weather is None:
        return JSONResponse({"error": "weather not yet available"}, status_code=503)
    return state.weather


@app.get("/api/radar", response_model=RadarResponse)
async def api_radar(request: Request) -> RadarResponse | JSONResponse:
    state = _state(request)
    if state.radar is None:
        return JSONResponse({"error": "radar not yet available"}, status_code=503)
    return state.radar


@app.get("/api/radar-frames")
async def api_radar_frames(request: Request) -> JSONResponse:
    """List pre-rendered radar frame URLs the pygame client cycles through."""
    state = _state(request)
    frames = state._active_frames()
    out = []
    for idx, _ in enumerate(state.renderers):
        out.append({
            "id": idx,
            "frames": [
                {"time": f.time, "url": f"/api/radar-frame/{idx}/{f.time}.png"}
                for f in frames
            ],
        })
    return JSONResponse({"radars": out, "size": list(RADAR_RENDER_SIZE)})


@app.get("/api/radar-frame/{radar_id}/{frame_time}.png")
async def api_radar_frame(request: Request, radar_id: int, frame_time: int) -> Response:
    state = _state(request)
    if radar_id < 0 or radar_id >= len(state.renderers):
        raise HTTPException(status_code=404, detail="unknown radar id")
    renderer = state.renderers[radar_id]
    png = renderer._frames.get(frame_time)
    if png is None:
        # Render on demand — handles races with a concurrent refresh.
        if state.radar is None or state.http is None:
            raise HTTPException(status_code=503, detail="radar not ready")
        match = next((f for f in state._active_frames() if f.time == frame_time), None)
        if match is None:
            raise HTTPException(status_code=404, detail="stale frame")
        png = await renderer.render_frame(state.http, state.radar.host, match.path, match.time)
    return Response(content=png, media_type="image/png", headers={"Cache-Control": "public, max-age=60"})


@app.get("/weather-fragment", response_class=HTMLResponse)
async def weather_fragment(request: Request) -> HTMLResponse:
    state = _state(request)
    return templates.TemplateResponse(
        request=request,
        name="weather_fragment.html",
        context={
            "w": state.weather,
            "cfg": _config_response(state),
            "units": _units(state),
        },
    )


@app.get("/forecast-fragment", response_class=HTMLResponse)
async def forecast_fragment(request: Request) -> HTMLResponse:
    state = _state(request)
    return templates.TemplateResponse(
        request=request,
        name="forecast_fragment.html",
        context={
            "w": state.weather,
            "cfg": _config_response(state),
            "units": _units(state),
        },
    )


@app.get("/api/events")
async def events(request: Request) -> EventSourceResponse:
    state = _state(request)
    queue: asyncio.Queue[str] = asyncio.Queue(maxsize=32)
    state.subscribers.add(queue)

    async def generator() -> AsyncIterator[dict]:
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield {"event": event, "data": "updated"}
                except asyncio.TimeoutError:
                    yield {"event": "ping", "data": "keepalive"}
        finally:
            state.subscribers.discard(queue)

    return EventSourceResponse(generator())
