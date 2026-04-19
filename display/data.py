"""In-process data refresh for the pygame kiosk.

Replaces the old httpx/SSE client that talked to a FastAPI backend on
localhost. Since the kiosk is now a single process, we call backend
modules (weather, radar, radar_render) directly and keep the result in
a DataStore the UI reads every frame.
"""

from __future__ import annotations

import asyncio
import logging
import os

import httpx
import pygame

from backend import config as config_module
from backend import radar as radar_module
from backend import weather as weather_module
from backend.models import RadarFrame, WeatherResponse
from backend.radar_render import RadarRenderer

log = logging.getLogger("piclock.data")

WEATHER_REFRESH_MINUTES = int(os.environ.get("PICLOCK_WEATHER_POLL_MIN", "30"))
RADAR_REFRESH_MINUTES = int(os.environ.get("PICLOCK_RADAR_POLL_MIN", "10"))
RADAR_FRAME_LIMIT = int(os.environ.get("PICLOCK_RADAR_FRAME_LIMIT", "6"))
RADAR_RENDER_SIZE = (512, 512)


class DataStore:
    """Holds the latest weather + per-radar animation frames in memory."""

    def __init__(self) -> None:
        self.settings = config_module.load()
        self.weather: WeatherResponse | None = None
        self.radar_meta: radar_module.RadarResponse | None = None
        # renderers is one-per-Config radar; each caches basemap + recent frames
        self.renderers: list[RadarRenderer] = [
            RadarRenderer(r, size=RADAR_RENDER_SIZE, google_api_key=self.settings.google_api_key)
            for r in self.settings.radars
        ]
        # Per-radar ordered list of (frame_time, Surface) — what the UI cycles through
        self.radar_frames: list[list[tuple[int, pygame.Surface]]] = [[] for _ in self.renderers]
        # Bumped whenever weather or radar changes — the UI diffs on this
        self.generation: int = 0
        self._http: httpx.AsyncClient | None = None

    @property
    def http(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=20.0)
        return self._http

    async def close(self) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    async def refresh_weather(self) -> None:
        try:
            self.weather = await weather_module.fetch(self.settings, self.http)
            self.generation += 1
        except Exception:
            log.exception("weather refresh failed")

    async def refresh_radar(self) -> None:
        """Fetch frame list and render every frame on every configured radar."""
        if not self.renderers:
            return
        try:
            self.radar_meta = await radar_module.fetch(self.http)
        except Exception:
            log.exception("radar metadata fetch failed")
            return
        frames: list[RadarFrame] = list(self.radar_meta.past[-RADAR_FRAME_LIMIT:])
        if not frames:
            return

        # Render each frame on each renderer concurrently — the basemap is
        # already cached after the first call, so subsequent frames only hit
        # the radar tile server.
        tasks: list = []
        for r in self.renderers:
            for f in frames:
                tasks.append(r.render_frame(self.http, self.radar_meta.host, f.path, f.time))
        await asyncio.gather(*tasks, return_exceptions=True)

        keep_times = {f.time for f in frames}
        new_frames: list[list[tuple[int, pygame.Surface]]] = []
        for r in self.renderers:
            per_radar = [(t, r._frames[t]) for t in sorted(r._frames) if t in keep_times]
            r.prune(keep_times)
            new_frames.append(per_radar)
        self.radar_frames = new_frames
        self.generation += 1


async def weather_loop(store: DataStore) -> None:
    interval = max(60, store.settings.weather_refresh_minutes * 60)
    while True:
        await asyncio.sleep(interval)
        await store.refresh_weather()


async def radar_loop(store: DataStore) -> None:
    interval = max(60, store.settings.radar_refresh_minutes * 60)
    while True:
        await asyncio.sleep(interval)
        await store.refresh_radar()
