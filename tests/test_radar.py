import httpx
import pytest

from backend import radar


SAMPLE = {
    "version": "2.0",
    "generated": 1713400000,
    "host": "https://tilecache.rainviewer.com",
    "radar": {
        "past": [
            {"time": 1713399000, "path": "/v2/radar/1713399000"},
            {"time": 1713399600, "path": "/v2/radar/1713399600"},
        ],
        "nowcast": [
            {"time": 1713400200, "path": "/v2/radar/nowcast_1713400200"},
        ],
    },
    "satellite": {"infrared": []},
}


@pytest.mark.asyncio
async def test_fetch_parses_host_and_frames():
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url).startswith("https://api.rainviewer.com")
        return httpx.Response(200, json=SAMPLE)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        result = await radar.fetch(client)

    assert result.host == "https://tilecache.rainviewer.com"
    assert len(result.past) == 2
    assert result.past[0].time == 1713399000
    assert len(result.nowcast) == 1
