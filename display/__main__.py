"""Pygame kiosk entry point. ``uv run python -m display``."""

from __future__ import annotations

import asyncio
import io
import logging
import os
import sys
import time
from datetime import datetime, timezone

import httpx
import pygame

from . import client as client_mod
from . import ui

log = logging.getLogger("piclock.display")

FPS = 30                       # main-loop frame rate
RADAR_FRAME_MS = 600           # time between radar-frame swaps


def _select_size() -> tuple[int, int]:
    """Use PICLOCK_DISPLAY_SIZE=WxH if set; else Info()'s current mode."""
    env = os.environ.get("PICLOCK_DISPLAY_SIZE")
    if env and "x" in env:
        try:
            w, h = env.lower().split("x", 1)
            return int(w), int(h)
        except ValueError:
            pass
    info = pygame.display.Info()
    return info.current_w, info.current_h


def _is_kiosk() -> bool:
    return os.environ.get("PICLOCK_WINDOWED", "0") != "1"


def _decode_frames(
    store: client_mod.DataStore,
    cache: dict[tuple[int, int], pygame.Surface],
) -> list[list[tuple[int, pygame.Surface]]]:
    """Turn the raw PNG bytes in the store into pygame Surfaces (cached)."""
    out: list[list[tuple[int, pygame.Surface]]] = []
    active_keys: set[tuple[int, int]] = set()
    for idx, radar in enumerate(store.radar_frames):
        decoded: list[tuple[int, pygame.Surface]] = []
        for frame_time, png in radar:
            key = (idx, frame_time)
            active_keys.add(key)
            surf = cache.get(key)
            if surf is None:
                try:
                    surf = pygame.image.load(io.BytesIO(png)).convert()
                except pygame.error as e:
                    log.warning("frame decode failed: %s", e)
                    continue
                cache[key] = surf
            decoded.append((frame_time, surf))
        out.append(decoded)
    # Prune stale surfaces
    for key in list(cache):
        if key not in active_keys:
            cache.pop(key, None)
    return out


def _handle_events() -> bool:
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            return False
        if event.type == pygame.KEYDOWN and event.key in (pygame.K_ESCAPE, pygame.K_q):
            return False
    return True


async def run() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    pygame.init()
    try:
        size = _select_size()
        flags = pygame.FULLSCREEN | pygame.SCALED if _is_kiosk() else 0
        screen = pygame.display.set_mode(size, flags)
        pygame.display.set_caption("PiClock")
        pygame.mouse.set_visible(False)

        layout = ui.compute_layout(screen.get_size())
        fonts = ui.load_fonts(layout)

        async with httpx.AsyncClient() as http:
            store = client_mod.DataStore()

            if not await client_mod.wait_for_backend(http):
                log.error("backend never answered /healthz; giving up")
                return 2
            await client_mod.fetch_config(http, store)
            await client_mod.fetch_weather(http, store)
            await client_mod.fetch_radar_frames(http, store)

            assets = ui.load_assets(layout, store.config)

            bg_tasks = [
                asyncio.create_task(client_mod.weather_loop(http, store)),
                asyncio.create_task(client_mod.radar_loop(http, store)),
                asyncio.create_task(client_mod.sse_loop(http, store)),
            ]

            surface_cache: dict[tuple[int, int], pygame.Surface] = {}
            radar_idx = [0, 0]
            last_advance_ms = pygame.time.get_ticks()
            last_icon_dir = (store.config or {}).get("icons")

            running = True
            try:
                while running:
                    running = _handle_events()
                    # Re-load icon set if Config.py changed (rare, but cheap).
                    current_icon_dir = (store.config or {}).get("icons")
                    if current_icon_dir and current_icon_dir != last_icon_dir:
                        assets = ui.load_assets(layout, store.config)
                        last_icon_dir = current_icon_dir

                    radar_decoded = _decode_frames(store, surface_cache)

                    now_ms = pygame.time.get_ticks()
                    if now_ms - last_advance_ms >= RADAR_FRAME_MS:
                        last_advance_ms = now_ms
                        for i, frames in enumerate(radar_decoded):
                            if i >= len(radar_idx):
                                continue
                            if frames:
                                radar_idx[i] = (radar_idx[i] + 1) % len(frames)

                    now = datetime.now(timezone.utc) if (store.config or {}).get("clockUTC") else datetime.now()

                    ui.draw_background(screen, assets)
                    ui.draw_weather(screen, layout.weather, store.weather, assets, fonts, store.config)

                    for i, panel_rect in enumerate((layout.radar1, layout.radar2)):
                        if i < len(radar_decoded) and radar_decoded[i]:
                            t, surf = radar_decoded[i][radar_idx[i] % len(radar_decoded[i])]
                        else:
                            t, surf = None, None
                        ui.draw_radar(screen, panel_rect, surf, fonts, f"R{i+1}", t)

                    ui.draw_clock(screen, layout, assets, fonts, store.config, now)
                    ui.draw_forecast(screen, layout.forecast, store.weather, assets, fonts, store.config)

                    pygame.display.flip()
                    await asyncio.sleep(1 / FPS)
            finally:
                for t in bg_tasks:
                    t.cancel()
                await asyncio.gather(*bg_tasks, return_exceptions=True)
    finally:
        pygame.quit()
    return 0


def main() -> int:
    try:
        return asyncio.run(run())
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
