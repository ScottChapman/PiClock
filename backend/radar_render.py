"""Server-side radar rendering.

Stitches CartoDB base-map tiles and RainViewer radar tiles into a single
PNG per frame, centred on the configured lat/lng. The pygame kiosk client
cycles through the PNGs to animate the radar loop — no browser / Leaflet.

Base-map tiles are fetched once per RadarRenderer (the background never
changes); radar-overlay tiles are fetched per frame and composited over
a copy of the cached base map. Frame results are cached in memory keyed
by (radar_id, frame_time).
"""

from __future__ import annotations

import asyncio
import io
import math
from dataclasses import dataclass
from typing import Iterable

import httpx
from PIL import Image, ImageDraw

from .config import Marker, RadarMap

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
    # world wrap isn't worth handling — radar stays on-continent
    n = 2 ** zoom
    min_tx = max(0, min_tx)
    max_tx = min(n - 1, max_tx)
    min_ty = max(0, min_ty)
    max_ty = min(n - 1, max_ty)
    crop_left = (fx - min_tx) * TILE_SIZE - w / 2
    crop_top = (fy - min_ty) * TILE_SIZE - h / 2
    return _TileBox(min_tx, max_tx, min_ty, max_ty, crop_left, crop_top, w, h)


async def _fetch_tile(client: httpx.AsyncClient, url: str) -> Image.Image | None:
    try:
        resp = await client.get(url, timeout=10.0)
        if resp.status_code != 200:
            return None
        # RainViewer returns a 1370-byte "Zoom Level Not Supported" PNG with
        # HTTP 200 at zooms > 7 — skip those so we don't paint them over the
        # basemap. Real radar tiles are either much smaller (empty) or much
        # larger (data), so this size check is stable.
        if len(resp.content) == _RAINVIEWER_NOT_SUPPORTED_SIZE and "rainviewer" in url:
            return None
        img = Image.open(io.BytesIO(resp.content)).convert("RGBA")
        return img
    except (httpx.HTTPError, OSError):
        return None


async def _fetch_grid(
    client: httpx.AsyncClient,
    url_tmpl: str,
    box: _TileBox,
    zoom: int,
    background: tuple[int, int, int, int] = (17, 17, 17, 255),
    **extra: object,
) -> Image.Image:
    """Fetch every tile in the box in parallel; composite into one RGBA image.

    ``background`` is the fallback fill used for missing tiles. Pass an opaque
    colour for the basemap (so failures show a dark placeholder) and a fully
    transparent ``(0, 0, 0, 0)`` for overlays so missing radar tiles don't
    paint solid rectangles over the basemap.
    """
    coords = list(box.iter_tiles())
    urls = [url_tmpl.format(z=zoom, x=tx, y=ty, **extra) for tx, ty in coords]
    tiles = await asyncio.gather(*(_fetch_tile(client, u) for u in urls))

    composite = Image.new(
        "RGBA",
        (box.tiles_wide * TILE_SIZE, box.tiles_tall * TILE_SIZE),
        background,
    )
    for (tx, ty), tile in zip(coords, tiles):
        if tile is None:
            continue
        dx = (tx - box.min_tx) * TILE_SIZE
        dy = (ty - box.min_ty) * TILE_SIZE
        composite.alpha_composite(tile, dest=(dx, dy))
    return composite


def _crop(composite: Image.Image, box: _TileBox) -> Image.Image:
    left = int(round(box.crop_left))
    top = int(round(box.crop_top))
    return composite.crop((left, top, left + box.width, top + box.height))


async def _fetch_google_static(
    client: httpx.AsyncClient,
    center: tuple[float, float],
    zoom: int,
    size: tuple[int, int],
    satellite: bool,
    api_key: str,
) -> Image.Image | None:
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
        return Image.open(io.BytesIO(resp.content)).convert("RGBA")
    except (httpx.HTTPError, OSError):
        return None


def _draw_markers(
    img: Image.Image,
    box: _TileBox,
    zoom: int,
    markers: Iterable[Marker],
) -> None:
    draw = ImageDraw.Draw(img)
    for m in markers:
        mx, my = latlng_to_tile(m.location[0], m.location[1], zoom)
        px = (mx - box.min_tx) * TILE_SIZE - box.crop_left
        py = (my - box.min_ty) * TILE_SIZE - box.crop_top
        r = 8 if m.size == "large" else 5
        color = _marker_color(m.color)
        draw.ellipse(
            (px - r, py - r, px + r, py + r),
            fill=color + (230,),
            outline=(255, 255, 255, 230),
            width=2,
        )


class RadarRenderer:
    """Per-radar-panel renderer. Caches base map + composited frames.

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
        # Radar is rendered covering the same geographic area as the basemap
        # but at its lower native resolution; then upscaled to `size`.
        radar_render_size = (max(1, size[0] // scale), max(1, size[1] // scale))
        self._radar_box = _compute_box(cfg.center, self._radar_zoom, radar_render_size)
        self._basemap: Image.Image | None = None
        self._lock = asyncio.Lock()
        # frame cache: time -> PNG bytes
        self._frames: dict[int, bytes] = {}

    @property
    def zoom(self) -> int:
        return self._basemap_zoom

    async def ensure_basemap(self, client: httpx.AsyncClient) -> Image.Image:
        if self._basemap is not None:
            return self._basemap
        async with self._lock:
            if self._basemap is not None:
                return self._basemap
            if self.google_api_key:
                img = await _fetch_google_static(
                    client,
                    center=self.cfg.center,
                    zoom=self._basemap_zoom,
                    size=self.size,
                    satellite=self.cfg.satellite,
                    api_key=self.google_api_key,
                )
                if img is not None:
                    self._basemap = img
                    return img
                # Fall through to CartoDB if Google failed (bad key, quota, etc.)
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
    ) -> bytes:
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
        if overlay.mode != "RGBA":
            overlay = overlay.convert("RGBA")
        # Upscale the radar to the basemap's pixel size when zoom differs.
        if overlay.size != self.size:
            overlay = overlay.resize(self.size, Image.BILINEAR)
        # Dial radar opacity down a touch so the basemap labels remain readable.
        alpha = overlay.split()[-1].point(lambda a: int(a * 0.75))
        overlay.putalpha(alpha)
        frame = base.copy()
        frame.alpha_composite(overlay)
        _draw_markers(frame, self._basemap_box, self._basemap_zoom, self.cfg.markers)
        buf = io.BytesIO()
        frame.convert("RGB").save(buf, format="PNG", optimize=False)
        png = buf.getvalue()
        self._frames[frame_time] = png
        return png

    def prune(self, keep_times: set[int]) -> None:
        """Drop cached PNG bytes for frames no longer in the active list."""
        for t in list(self._frames):
            if t not in keep_times:
                self._frames.pop(t, None)
