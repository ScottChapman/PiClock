"""RainViewer metadata fetcher.

Thin wrapper around RainViewer's public weather-maps index. Returns the
tile server host and the list of recent radar frames. The RadarRenderer
consumes this to fetch + composite tiles per frame.
"""

from __future__ import annotations

import httpx

from .models import RadarFrame, RadarResponse

RAINVIEWER_URL = "https://api.rainviewer.com/public/weather-maps.json"


async def fetch(client: httpx.AsyncClient | None = None) -> RadarResponse:
    owns = client is None
    client = client or httpx.AsyncClient(timeout=10.0)
    try:
        resp = await client.get(RAINVIEWER_URL)
        resp.raise_for_status()
        data = resp.json()
    finally:
        if owns:
            await client.aclose()

    host = data["host"]
    past = [RadarFrame(**f) for f in data["radar"]["past"]]
    nowcast = [RadarFrame(**f) for f in data["radar"].get("nowcast", [])]
    return RadarResponse(
        host=host,
        past=past,
        nowcast=nowcast,
        generated=int(data.get("generated", 0)),
    )
