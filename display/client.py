"""Async HTTP client that keeps a DataStore fresh from the backend API.

Runs in the same asyncio loop as the pygame main loop. Exposes a
DataStore holding the latest weather/forecast/radar state — the UI
reads from it every frame; network refresh happens in the background.
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
from dataclasses import dataclass, field

import httpx

log = logging.getLogger("piclock.display.client")


BACKEND_URL = os.environ.get("PICLOCK_BACKEND", "http://127.0.0.1:8000")
WEATHER_POLL_SECONDS = int(os.environ.get("PICLOCK_WEATHER_POLL", "180"))
RADAR_POLL_SECONDS = int(os.environ.get("PICLOCK_RADAR_POLL", "300"))


@dataclass
class DataStore:
    config: dict | None = None
    weather: dict | None = None
    # Per-radar: list of (frame_time, raw_png_bytes). UI converts to pygame Surface.
    radar_frames: list[list[tuple[int, bytes]]] = field(default_factory=list)
    radar_size: tuple[int, int] = (512, 512)
    generation: int = 0   # bumped on every successful refresh — UI watches this
    error: str | None = None


async def _get_json(client: httpx.AsyncClient, path: str) -> dict | None:
    try:
        r = await client.get(BACKEND_URL + path, timeout=15.0)
        if r.status_code != 200:
            log.warning("%s -> HTTP %s", path, r.status_code)
            return None
        return r.json()
    except httpx.HTTPError as e:
        log.warning("%s failed: %s", path, e)
        return None


async def fetch_config(client: httpx.AsyncClient, store: DataStore) -> None:
    data = await _get_json(client, "/api/config")
    if data is not None:
        store.config = data


async def fetch_weather(client: httpx.AsyncClient, store: DataStore) -> None:
    data = await _get_json(client, "/api/weather")
    if data is not None:
        store.weather = data
        store.generation += 1


async def fetch_radar_frames(client: httpx.AsyncClient, store: DataStore) -> None:
    meta = await _get_json(client, "/api/radar-frames")
    if meta is None:
        return
    size = meta.get("size", [512, 512])
    store.radar_size = (int(size[0]), int(size[1]))
    per_radar: list[list[tuple[int, bytes]]] = []
    for radar in meta.get("radars", []):
        frames: list[tuple[int, bytes]] = []
        for f in radar.get("frames", []):
            try:
                r = await client.get(BACKEND_URL + f["url"], timeout=20.0)
                if r.status_code == 200:
                    frames.append((int(f["time"]), r.content))
            except httpx.HTTPError as e:
                log.warning("frame fetch failed: %s", e)
        per_radar.append(frames)
    if per_radar:
        store.radar_frames = per_radar
        store.generation += 1


async def weather_loop(client: httpx.AsyncClient, store: DataStore) -> None:
    while True:
        await asyncio.sleep(WEATHER_POLL_SECONDS)
        await fetch_weather(client, store)


async def radar_loop(client: httpx.AsyncClient, store: DataStore) -> None:
    while True:
        await asyncio.sleep(RADAR_POLL_SECONDS)
        await fetch_radar_frames(client, store)


async def sse_loop(client: httpx.AsyncClient, store: DataStore) -> None:
    """Listen for backend refresh events and trigger the matching fetcher."""
    url = BACKEND_URL + "/api/events"
    while True:
        try:
            async with client.stream("GET", url, timeout=None) as resp:
                if resp.status_code != 200:
                    log.warning("SSE status %s; retrying in 10s", resp.status_code)
                    await asyncio.sleep(10)
                    continue
                event = "message"
                async for line in resp.aiter_lines():
                    if line.startswith("event:"):
                        event = line.split(":", 1)[1].strip()
                    elif line.startswith("data:") and event in ("weather", "radar"):
                        if event == "weather":
                            await fetch_weather(client, store)
                        elif event == "radar":
                            await fetch_radar_frames(client, store)
        except (httpx.HTTPError, asyncio.TimeoutError) as e:
            log.warning("SSE dropped: %s; retrying in 10s", e)
            await asyncio.sleep(10)


async def wait_for_backend(client: httpx.AsyncClient, max_seconds: int = 60) -> bool:
    """Poll /healthz until the backend answers or we give up."""
    url = BACKEND_URL + "/healthz"
    for _ in range(max_seconds):
        try:
            r = await client.get(url, timeout=2.0)
            if r.status_code == 200:
                return True
        except httpx.HTTPError:
            pass
        await asyncio.sleep(1)
    return False
