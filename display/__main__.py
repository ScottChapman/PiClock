"""Pygame kiosk entry point. ``uv run python -m display``.

Everything runs in-process: weather + radar fetchers, tile rendering,
and the pygame UI share one asyncio event loop. No HTTP server, no
serialization round-trips.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import os
import sys
from datetime import datetime, timezone

import pygame

from . import data as data_mod
from . import ui

log = logging.getLogger("piclock.display")

FPS = 30                       # main-loop frame rate
RADAR_FRAME_MS = 600           # time between radar-frame swaps


def _select_size() -> tuple[int, int]:
    """Use PICLOCK_DISPLAY_SIZE=WxH if set; else the display's current mode."""
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


def _handle_events() -> bool:
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            return False
        if event.type == pygame.KEYDOWN and event.key in (pygame.K_ESCAPE, pygame.K_q):
            return False
    return True


def _settings_as_dict(settings) -> dict:
    """Dataclass → dict the UI understands. Mostly a 1:1 mapping."""
    d = dataclasses.asdict(settings)
    # UI reads labels as a dict under this key
    return d


def _weather_as_dict(weather) -> dict | None:
    return dataclasses.asdict(weather) if weather is not None else None


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

        store = data_mod.DataStore()
        # Prime the UI with initial data before the main loop starts drawing.
        await store.refresh_weather()
        await store.refresh_radar()

        cfg_dict = _settings_as_dict(store.settings)
        assets = ui.load_assets(layout, cfg_dict)

        bg_tasks = [
            asyncio.create_task(data_mod.weather_loop(store)),
            asyncio.create_task(data_mod.radar_loop(store)),
        ]

        radar_idx = [0, 0]
        last_advance_ms = pygame.time.get_ticks()
        last_icon_dir = cfg_dict.get("icons")

        running = True
        try:
            while running:
                running = _handle_events()

                # Pick up Config.py edits (icon set, clockUTC, etc.) cheaply.
                current_icon_dir = cfg_dict.get("icons")
                if current_icon_dir and current_icon_dir != last_icon_dir:
                    assets = ui.load_assets(layout, cfg_dict)
                    last_icon_dir = current_icon_dir

                now_ms = pygame.time.get_ticks()
                if now_ms - last_advance_ms >= RADAR_FRAME_MS:
                    last_advance_ms = now_ms
                    for i, frames in enumerate(store.radar_frames):
                        if i >= len(radar_idx):
                            continue
                        if frames:
                            radar_idx[i] = (radar_idx[i] + 1) % len(frames)

                now = datetime.now(timezone.utc) if cfg_dict.get("clockUTC") else datetime.now()
                weather_dict = _weather_as_dict(store.weather)

                ui.draw_background(screen, assets)
                ui.draw_weather(screen, layout.weather, weather_dict, assets, fonts, cfg_dict)

                for i, panel_rect in enumerate((layout.radar1, layout.radar2)):
                    if i < len(store.radar_frames) and store.radar_frames[i]:
                        frames = store.radar_frames[i]
                        t, surf = frames[radar_idx[i] % len(frames)]
                    else:
                        t, surf = None, None
                    ui.draw_radar(screen, panel_rect, surf, fonts, f"R{i+1}", t)

                ui.draw_clock(screen, layout, assets, fonts, cfg_dict, now)
                ui.draw_forecast(screen, layout.forecast, weather_dict, assets, fonts, cfg_dict)

                pygame.display.flip()
                await asyncio.sleep(1 / FPS)
        finally:
            for t in bg_tasks:
                t.cancel()
            await asyncio.gather(*bg_tasks, return_exceptions=True)
            await store.close()
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
