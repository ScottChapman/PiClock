"""Server-side radar rendering.

Stitches basemap tiles (CartoDB or Google Static Maps) and RainViewer
radar overlay tiles into a single PNG per frame, centred on the
configured lat/lng. The pygame kiosk client cycles through the PNGs to
animate the radar loop — no browser / Leaflet.

Base-map tiles are fetched once per RadarRenderer (the background never
changes); radar-overlay tiles are fetched per frame and composited over
a copy of the cached base map. Frame results are cached in memory keyed
by frame_time.

Uses pygame (not Pillow) for image manipulation so we ride the same
dependency the display client already requires — avoids the
libjpeg/libtiff/zlib chain that Pillow needs on older Raspbian builds.
"""

from __future__ import annotations

import asyncio
import io
import math
import os
from dataclasses import dataclass
from typing import Iterable

import httpx

# The backend process is headless; use SDL's dummy video driver so
# pygame can create surfaces without opening a display.
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
import pygame

from .config import Marker, RadarMap

# Ensure pygame's image subsystem is ready (PNG load/save). This is
# cheap to call repeatedly and required before any Surface work.
pygame.init()

TILE_SIZE = 256
# Fallback tile-based basemap used when no Google Static Maps key is set.
BASEMAP_URL = "https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png"
# Google Static Maps — single pre-rendered image centred on lat/lng at a
# given zoom. Used when Config's ApiKeys.googleapi is populated.
GOOGLE_STATIC_URL = "https://maps.googleapis.com/maps/api/staticmap"
RAINVIEWER_TILE = "{host}{path}/{size}/{z}/{x}/{y}/{color}/{smooth}_{snow}.png"

# As of 2026-04, RainViewer's 256-px tiles only return real data up to z=7;
# at higher zooms they return a 1370-byte "Zoom Level Not Supported" PNG
# (with HTTP 200), which we must avoid compositing onto the basemap.
RAINVIEWER_MAX_NATIVE_ZOOM = 7
_RAINVIEWER_NOT_SUPPORTED_SIZE = 1370  # byte length of the sentinel PNG


def latlng_to_tile(lat: float, lng: float, zoom: int) -> tuple[float, float]:
    """Slippy-map tile coords (float). Integer part = tile index, fraction = pixel offset / TILE_SIZE."""
    lat_rad = math.radians(lat)
    n = 2.0 ** zoom
    x = (lng + 180.0) / 360.0 * n
    y = (1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n
    return x, y


def _marker_color(name: str) -> tuple[int, int, int]:
    table = {
        "red":     (220,  50,  50),
        "blue":    ( 60, 140, 220),
        "green":   ( 60, 200,  90),
        "yellow":  (240, 210,  60),
        "white":   (240, 240, 240),
        "orange":  (240, 150,  60),
    }
    return table.get(name.lower(), (220, 50, 50))


# ---------- pygame helpers ---------------------------------------------------

def _new_surface(size: tuple[int, int], background: tuple[int, int, int, int]) -> pygame.Surface:
    """Allocate an RGBA surface pre-filled with ``background``."""
    surf = pygame.Surface(size, pygame.SRCALPHA)
    surf.fill(background)
    return surf


def _load_png(data: bytes) -> pygame.Surface | None:
    """Decode PNG bytes into an RGBA pygame Surface, or None on failure."""
    try:
        return pygame.image.load(io.BytesIO(data), "tile.png").convert_alpha()
    except (pygame.error, OSError):
        return None


def _resize(surf: pygame.Surface, size: tuple[int, int]) -> pygame.Surface:
    return pygame.transform.smoothscale(surf, size)


def _crop_surface(surf: pygame.Surface, left: int, top: int, w: int, h: int) -> pygame.Surface:
    src = surf.get_rect()
    rect = pygame.Rect(max(0, left), max(0, top), w, h).clip(src)
    out = pygame.Surface((w, h), pygame.SRCALPHA)
    out.blit(surf, (rect.x - left, rect.y - top), rect)
    return out


def _multiply_alpha(surf: pygame.Surface, factor: float) -> None:
    """Scale every pixel's alpha channel by ``factor`` (in-place)."""
    if factor >= 0.999:
        return
    mask = pygame.Surface(surf.get_size(), pygame.SRCALPHA)
    mask.fill((255, 255, 255, max(0, min(255, int(255 * factor)))))
    surf.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)


# ---------- tile-math helpers -----------------------------------------------

@dataclass(frozen=True)
class _TileBox:
    """Integer tile range + pixel crop offsets for the final output image."""
    min_tx: int
    max_tx: int
    min_ty: int
    max_ty: int
    crop_left: float
    crop_top: float
    width: int
    height: int

    @property
    def tiles_wide(self) -> int:
        return self.max_tx - self.min_tx + 1

    @property
    def tiles_tall(self) -> int:
        return self.max_ty - self.min_ty + 1

    def iter_tiles(self) -> Iterable[tuple[int, int]]:
        for ty in range(self.min_ty, self.max_ty + 1):
            for tx in range(self.min_tx, self.max_tx + 1):
                yield tx, ty


def _compute_box(center: tuple[float, float], zoom: int, size: tuple[int, int]) -> _TileBox:
    w, h = size
    fx, fy = latlng_to_tile(center[0], center[1], zoom)
    half_w = w / (2 * TILE_SIZE)
    half_h = h / (2 * TILE_SIZE)
    min_tx = math.floor(fx - half_w)
    max_tx = math.floor(fx + half_w)
    min_ty = math.floor(fy - half_h)
    max_ty = math.floor(fy + half_h)
    n = 2 ** zoom
    min_tx = max(0, min_tx)
    max_tx = min(n - 1, max_tx)
    min_ty = max(0, min_ty)
    max_ty = min(n - 1, max_ty)
    crop_left = (fx - min_tx) * TILE_SIZE - w / 2
    crop_top = (fy - min_ty) * TILE_SIZE - h / 2
    return _TileBox(min_tx, max_tx, min_ty, max_ty, crop_left, crop_top, w, h)


# ---------- fetchers --------------------------------------------------------

async def _fetch_tile(client: httpx.AsyncClient, url: str) -> pygame.Surface | None:
    try:
        resp = await client.get(url, timeout=10.0)
        if resp.status_code != 200:
            return None
        # RainViewer's "Zoom Level Not Supported" sentinel: skip so we don't
        # paint the error image over the basemap when compositing.
        if len(resp.content) == _RAINVIEWER_NOT_SUPPORTED_SIZE and "rainviewer" in url:
            return None
        return _load_png(resp.content)
    except (httpx.HTTPError, OSError):
        return None


async def _fetch_grid(
    client: httpx.AsyncClient,
    url_tmpl: str,
    box: _TileBox,
    zoom: int,
    background: tuple[int, int, int, int] = (17, 17, 17, 255),
    **extra: object,
) -> pygame.Surface:
    """Fetch every tile in the box in parallel; composite onto one RGBA surface.

    ``background`` is the fallback fill behind tiles. Opaque for basemaps
    (failure shows a dark placeholder); fully transparent for overlays so
    missing radar tiles don't paint solid rectangles over the basemap.
    """
    coords = list(box.iter_tiles())
    urls = [url_tmpl.format(z=zoom, x=tx, y=ty, **extra) for tx, ty in coords]
    tiles = await asyncio.gather(*(_fetch_tile(client, u) for u in urls))

    composite = _new_surface(
        (box.tiles_wide * TILE_SIZE, box.tiles_tall * TILE_SIZE),
        background,
    )
    for (tx, ty), tile in zip(coords, tiles):
        if tile is None:
            continue
        dx = (tx - box.min_tx) * TILE_SIZE
        dy = (ty - box.min_ty) * TILE_SIZE
        composite.blit(tile, (dx, dy))
    return composite


def _crop(composite: pygame.Surface, box: _TileBox) -> pygame.Surface:
    left = int(round(box.crop_left))
    top = int(round(box.crop_top))
    return _crop_surface(composite, left, top, box.width, box.height)


async def _fetch_google_static(
    client: httpx.AsyncClient,
    center: tuple[float, float],
    zoom: int,
    size: tuple[int, int],
    satellite: bool,
    api_key: str,
) -> pygame.Surface | None:
    """Fetch a single Google Static Maps image centred on ``center`` at ``zoom``.

    Returns None on any failure (missing/invalid key, quota, network) so the
    caller can fall back to the tile-based basemap.
    """
    maptype = "hybrid" if satellite else "roadmap"
    params = {
        "center": f"{center[0]},{center[1]}",
        "zoom": str(zoom),
        "size": f"{size[0]}x{size[1]}",
        "maptype": maptype,
        "key": api_key,
    }
    try:
        resp = await client.get(GOOGLE_STATIC_URL, params=params, timeout=15.0)
        if resp.status_code != 200:
            return None
        return _load_png(resp.content)
    except (httpx.HTTPError, OSError):
        return None


def _draw_markers(
    surf: pygame.Surface,
    box: _TileBox,
    zoom: int,
    markers: Iterable[Marker],
) -> None:
    for m in markers:
        mx, my = latlng_to_tile(m.location[0], m.location[1], zoom)
        px = int(round((mx - box.min_tx) * TILE_SIZE - box.crop_left))
        py = int(round((my - box.min_ty) * TILE_SIZE - box.crop_top))
        r = 8 if m.size == "large" else 5
        color = _marker_color(m.color) + (230,)
        pygame.draw.circle(surf, color, (px, py), r)
        pygame.draw.circle(surf, (255, 255, 255, 230), (px, py), r, width=2)


class RadarRenderer:
    """Per-radar-panel renderer. Caches base map + composited frame bytes.

    Basemap is fetched at cfg.zoom for full detail; radar is fetched at
    min(cfg.zoom, 7) — RainViewer's native cap — and then upscaled to
    match the basemap's pixel area. When cfg.zoom <= 7 the scale factor
    is 1 and this is a no-op.
    """

    def __init__(
        self,
        cfg: RadarMap,
        size: tuple[int, int] = (512, 512),
        google_api_key: str = "",
    ):
        self.cfg = cfg
        self.size = size
        self.google_api_key = google_api_key
        self._basemap_zoom = cfg.zoom
        self._radar_zoom = min(cfg.zoom, RAINVIEWER_MAX_NATIVE_ZOOM)
        self._basemap_box = _compute_box(cfg.center, self._basemap_zoom, size)
        scale = 2 ** (self._basemap_zoom - self._radar_zoom)
        radar_render_size = (max(1, size[0] // scale), max(1, size[1] // scale))
        self._radar_box = _compute_box(cfg.center, self._radar_zoom, radar_render_size)
        self._basemap: pygame.Surface | None = None
        self._lock = asyncio.Lock()
        self._frames: dict[int, pygame.Surface] = {}

    @property
    def zoom(self) -> int:
        return self._basemap_zoom

    async def ensure_basemap(self, client: httpx.AsyncClient) -> pygame.Surface:
        if self._basemap is not None:
            return self._basemap
        async with self._lock:
            if self._basemap is not None:
                return self._basemap
            if self.google_api_key:
                surf = await _fetch_google_static(
                    client,
                    center=self.cfg.center,
                    zoom=self._basemap_zoom,
                    size=self.size,
                    satellite=self.cfg.satellite,
                    api_key=self.google_api_key,
                )
                if surf is not None:
                    self._basemap = surf
                    return surf
            composite = await _fetch_grid(client, BASEMAP_URL, self._basemap_box, self._basemap_zoom)
            cropped = _crop(composite, self._basemap_box)
            self._basemap = cropped
            return cropped

    async def render_frame(
        self,
        client: httpx.AsyncClient,
        host: str,
        frame_path: str,
        frame_time: int,
    ) -> pygame.Surface:
        """Return the composited frame as a pygame Surface (no PNG round-trip)."""
        if frame_time in self._frames:
            return self._frames[frame_time]
        base = await self.ensure_basemap(client)
        overlay_big = await _fetch_grid(
            client,
            RAINVIEWER_TILE,
            self._radar_box,
            self._radar_zoom,
            background=(0, 0, 0, 0),
            host=host,
            path=frame_path,
            size=TILE_SIZE,
            color=2,
            smooth=1,
            snow=1,
        )
        overlay = _crop(overlay_big, self._radar_box)
        if overlay.get_size() != self.size:
            overlay = _resize(overlay, self.size)
        _multiply_alpha(overlay, 0.75)
        frame = base.copy()
        frame.blit(overlay, (0, 0))
        _draw_markers(frame, self._basemap_box, self._basemap_zoom, self.cfg.markers)
        self._frames[frame_time] = frame
        return frame

    def prune(self, keep_times: set[int]) -> None:
        """Drop cached Surfaces for frames no longer in the active list."""
        for t in list(self._frames):
            if t not in keep_times:
                self._frames.pop(t, None)
