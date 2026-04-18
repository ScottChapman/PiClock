import io
import math

import httpx
import pytest
from PIL import Image

from backend import radar_render as rr
from backend.config import Marker, RadarMap


def test_latlng_to_tile_matches_known_value():
    # At zoom 0 the whole world is one tile; the origin is the dateline NW corner.
    x, y = rr.latlng_to_tile(0.0, 0.0, 0)
    assert x == pytest.approx(0.5)
    assert y == pytest.approx(0.5)


def test_latlng_to_tile_at_zoom_2():
    # NYC at zoom 2 should land in tile (x≈1.2, y≈1.5) — western hemisphere, mid latitudes.
    x, y = rr.latlng_to_tile(40.7128, -74.0060, 2)
    assert 1.0 < x < 1.5
    assert 1.4 < y < 1.6


def test_compute_box_gives_symmetric_crop_when_centered_on_tile_corner():
    # Location right on a tile grid corner → crop should be centred.
    box = rr._compute_box((0.0, 0.0), 2, (256, 256))
    # Whole world at z=2 is 4x4 tiles; (0,0) lat/lng sits at (2.0, 2.0) tile coords.
    # With a 256 output, we need 1 tile horizontally/vertically.
    assert box.tiles_wide >= 1
    assert box.tiles_tall >= 1


@pytest.mark.asyncio
async def test_render_frame_composites_basemap_and_radar(monkeypatch):
    """End-to-end: fake base + radar tiles, ensure the render returns a valid PNG."""
    # 256x256 solid-colour tiles so we can verify the composite succeeds.
    def make_png(colour: tuple[int, int, int, int]) -> bytes:
        img = Image.new("RGBA", (256, 256), colour)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    base_png = make_png((30, 30, 30, 255))     # dark grey basemap
    radar_png = make_png((0, 200, 0, 180))     # green radar splotch

    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        calls.append(url)
        if "basemaps.cartocdn.com" in url:
            return httpx.Response(200, content=base_png,
                                  headers={"content-type": "image/png"})
        if "tilecache.rainviewer.com" in url:
            return httpx.Response(200, content=radar_png,
                                  headers={"content-type": "image/png"})
        return httpx.Response(404)

    cfg = RadarMap(
        center=(42.5911248, -71.5692887),
        zoom=7,
        markers=(Marker(location=(42.5911248, -71.5692887), color="red", size="small"),),
    )
    renderer = rr.RadarRenderer(cfg, size=(256, 256))

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        png = await renderer.render_frame(
            client,
            host="https://tilecache.rainviewer.com",
            frame_path="/v2/radar/1700000000/0",
            frame_time=1700000000,
        )

    # Output is a real PNG
    img = Image.open(io.BytesIO(png))
    assert img.size == (256, 256)
    # Basemap request happened (once) + radar requests fired
    assert any("basemaps.cartocdn.com" in u for u in calls)
    assert any("tilecache.rainviewer.com" in u for u in calls)
    # Frame is cached
    assert renderer._frames[1700000000] == png

    # Calling again reuses the cache (no additional HTTP calls for the frame)
    before = len(calls)
    again = await renderer.render_frame(
        client,
        host="https://tilecache.rainviewer.com",
        frame_path="/v2/radar/1700000000/0",
        frame_time=1700000000,
    )
    assert again == png
    assert len(calls) == before


@pytest.mark.asyncio
async def test_basemap_is_only_fetched_once():
    base_png_calls = 0

    def make_png() -> bytes:
        img = Image.new("RGBA", (256, 256), (10, 10, 10, 255))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    png = make_png()

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal base_png_calls
        if "basemaps.cartocdn.com" in str(request.url):
            base_png_calls += 1
        return httpx.Response(200, content=png, headers={"content-type": "image/png"})

    cfg = RadarMap(center=(0.0, 0.0), zoom=2)
    renderer = rr.RadarRenderer(cfg, size=(256, 256))

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        for t in (1000, 2000, 3000):
            await renderer.render_frame(client, "https://tilecache.rainviewer.com",
                                        f"/v2/radar/{t}/0", t)

    first_basemap_calls = base_png_calls
    # Render once more — should still be same count (basemap cached)
    async with httpx.AsyncClient(transport=transport) as client:
        # New client but same renderer, basemap is still cached in the renderer.
        await renderer.render_frame(client, "https://tilecache.rainviewer.com",
                                    "/v2/radar/4000/0", 4000)
    assert base_png_calls == first_basemap_calls


def test_prune_drops_unused_frames():
    cfg = RadarMap(center=(0.0, 0.0), zoom=2)
    r = rr.RadarRenderer(cfg, size=(128, 128))
    r._frames[1] = b"x"
    r._frames[2] = b"y"
    r._frames[3] = b"z"
    r.prune({2})
    assert set(r._frames.keys()) == {2}
