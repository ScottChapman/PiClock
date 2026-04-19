import dataclasses
from pathlib import Path

import httpx
import pytest

from backend import config, weather


ICONS_DIR = Path(__file__).resolve().parents[1] / "backend" / "static" / "icons-lightblue"


def test_wmo_map_covers_expected_codes():
    for code in (0, 1, 2, 3, 45, 61, 71, 95):
        icon, desc = weather.WMO_MAP[code]
        assert icon
        assert desc


def test_every_icon_exists_on_disk():
    for code, (icon, _) in weather.WMO_MAP.items():
        day_file = ICONS_DIR / f"{icon}.png"
        assert day_file.exists(), f"missing day icon for WMO {code}: {icon}"
        if icon.endswith("-day"):
            night_file = ICONS_DIR / f"{icon.replace('-day', '-night')}.png"
            assert night_file.exists(), f"missing night icon for WMO {code}"


def test_icon_for_switches_to_night_for_clear_codes():
    assert weather.icon_for(0, is_day=True) == "clear-day"
    assert weather.icon_for(0, is_day=False) == "clear-night"
    assert weather.icon_for(2, is_day=True) == "partly-cloudy-day"
    assert weather.icon_for(2, is_day=False) == "partly-cloudy-night"
    # Rain doesn't have a night variant — stays the same
    assert weather.icon_for(61, is_day=False) == "rain"


def test_moon_phase_returns_known_name():
    name, frac = weather.moon_phase_name()
    assert name in {
        "New Moon", "Waxing Crescent", "First Quarter", "Waxing Gibbous",
        "Full Moon", "Waning Gibbous", "Last Quarter", "Waning Crescent",
    }
    assert 0 <= frac <= 1


@pytest.mark.asyncio
async def test_fetch_normalizes_response():
    settings = config.load()
    payload = {
        "current": {
            "time": "2026-04-18T14:00",
            "temperature_2m": 68.0,
            "apparent_temperature": 65.0,
            "weather_code": 2,
            "wind_speed_10m": 10.0,
            "wind_direction_10m": 180,
            "wind_gusts_10m": 18.0,
            "surface_pressure": 1012.0,
            "relative_humidity_2m": 55,
            "precipitation": 0.0,
            "is_day": 1,
        },
        "hourly": {
            "time": [f"2026-04-18T{h:02d}:00" for h in range(14, 24)],
            "temperature_2m": [70.0] * 10,
            "apparent_temperature": [68.0] * 10,
            "relative_humidity_2m": [55] * 10,
            "weather_code": [2] * 10,
            "precipitation": [0.0] * 10,
            "precipitation_probability": [20] * 10,
            "wind_speed_10m": [10.0] * 10,
            "wind_direction_10m": [180] * 10,
            "wind_gusts_10m": [15.0] * 10,
            "cloud_cover": [50] * 10,
            "uv_index": [3.5] * 10,
            "dew_point_2m": [50.0] * 10,
        },
        "daily": {
            "time": ["2026-04-18", "2026-04-19"],
            "weather_code": [2, 61],
            "temperature_2m_max": [75.0, 60.0],
            "temperature_2m_min": [55.0, 50.0],
            "precipitation_sum": [0.0, 0.3],
            "precipitation_probability_max": [20, 80],
            "wind_speed_10m_max": [12.0, 20.0],
            "wind_direction_10m_dominant": [180, 200],
            "sunrise": ["2026-04-18T06:00", "2026-04-19T05:59"],
            "sunset": ["2026-04-18T19:30", "2026-04-19T19:31"],
        },
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    settings_no_metar = dataclasses.replace(settings, METAR="")
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        result = await weather.fetch(settings_no_metar, client)

    assert result.current.temperature == 68.0
    assert result.current.icon == "partly-cloudy-day"
    assert result.current.description == "Partly Cloudy"
    # fixture only supplies 10 hourly slots starting at 14:00; fetcher returns them all
    assert len(result.forecast.hourly) == 10
    assert len(result.forecast.daily) == 2
    assert result.forecast.daily[0].weekday  # non-empty
