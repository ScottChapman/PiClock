"""Open-Meteo weather fetch and normalization.

Single endpoint returns current conditions, hourly forecast, daily forecast,
and sunrise/sunset. No API key required.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime

import httpx
from astral import moon

from .config import Settings
from .models import (
    CurrentWeather,
    DailyPoint,
    ForecastResponse,
    HourlyPoint,
    WeatherAlert,
    WeatherResponse,
)

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

_CURRENT_FIELDS = (
    "temperature_2m,apparent_temperature,weather_code,wind_speed_10m,"
    "wind_direction_10m,wind_gusts_10m,surface_pressure,"
    "relative_humidity_2m,precipitation,is_day"
)
_HOURLY_FIELDS = (
    "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,"
    "precipitation,precipitation_probability,wind_speed_10m,wind_direction_10m,"
    "wind_gusts_10m,cloud_cover,uv_index,dew_point_2m"
)
_DAILY_FIELDS = (
    "weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,"
    "precipitation_probability_max,wind_speed_10m_max,wind_direction_10m_dominant,"
    "sunrise,sunset"
)

# WMO weather-interpretation code → (icon base name, human description)
# Icon names match files in the legacy/Clock/icons-*/ sets.
# Reference: https://open-meteo.com/en/docs (WMO Weather interpretation codes)
WMO_MAP: dict[int, tuple[str, str]] = {
    0:  ("clear-day",          "Clear"),
    1:  ("clear-day",          "Mainly Clear"),
    2:  ("partly-cloudy-day",  "Partly Cloudy"),
    3:  ("cloudy",             "Overcast"),
    45: ("fog",                "Fog"),
    48: ("fog",                "Depositing Rime Fog"),
    51: ("rain",               "Light Drizzle"),
    53: ("rain",               "Drizzle"),
    55: ("rain",               "Heavy Drizzle"),
    56: ("sleet",              "Freezing Drizzle"),
    57: ("sleet",              "Heavy Freezing Drizzle"),
    61: ("rain",               "Light Rain"),
    63: ("rain",               "Rain"),
    65: ("rain",               "Heavy Rain"),
    66: ("sleet",              "Freezing Rain"),
    67: ("sleet",              "Heavy Freezing Rain"),
    71: ("snow",               "Light Snow"),
    73: ("snow",               "Snow"),
    75: ("snow",               "Heavy Snow"),
    77: ("snow",               "Snow Grains"),
    80: ("rain",               "Light Showers"),
    81: ("rain",               "Showers"),
    82: ("rain",               "Heavy Showers"),
    85: ("snow",               "Snow Showers"),
    86: ("snow",               "Heavy Snow Showers"),
    95: ("thunderstorm",       "Thunderstorm"),
    96: ("thunderstorm",       "Thunderstorm with Hail"),
    99: ("thunderstorm",       "Thunderstorm with Heavy Hail"),
}


def icon_for(code: int, is_day: bool = True) -> str:
    base, _ = WMO_MAP.get(code, ("cloudy", "Unknown"))
    if not is_day and base in ("clear-day", "partly-cloudy-day"):
        return base.replace("-day", "-night")
    return base


def describe(code: int) -> str:
    _, desc = WMO_MAP.get(code, ("cloudy", "Unknown"))
    return desc


_MOON_PHASES = [
    (1.84566, "New Moon"),
    (5.53699, "Waxing Crescent"),
    (9.22831, "First Quarter"),
    (12.91963, "Waxing Gibbous"),
    (16.61096, "Full Moon"),
    (20.30228, "Waning Gibbous"),
    (23.99361, "Last Quarter"),
    (27.68493, "Waning Crescent"),
]


def moon_phase_name(today: date | None = None) -> tuple[str, float]:
    """Return (name, fraction 0..1) for the moon phase today."""
    d = today or date.today()
    age = moon.phase(d)  # 0..~29.53
    for cutoff, name in _MOON_PHASES:
        if age < cutoff:
            return name, age / 29.53
    return "New Moon", age / 29.53


def _weekday(dt: datetime) -> str:
    return dt.strftime("%a")


def _normalize(data: dict, settings: Settings) -> WeatherResponse:
    cur = data["current"]
    daily = data["daily"]
    hourly = data["hourly"]

    is_day = bool(cur.get("is_day", 1))
    code = int(cur["weather_code"])
    moon_name, moon_frac = moon_phase_name()

    current = CurrentWeather(
        temperature=float(cur["temperature_2m"]),
        apparent_temperature=float(cur["apparent_temperature"]),
        humidity=int(cur["relative_humidity_2m"]),
        pressure=float(cur["surface_pressure"]),
        wind_speed=float(cur["wind_speed_10m"]),
        wind_direction=int(cur["wind_direction_10m"]),
        wind_gust=float(cur["wind_gusts_10m"]) if cur.get("wind_gusts_10m") is not None else None,
        precipitation=float(cur.get("precipitation", 0.0)),
        weather_code=code,
        icon=icon_for(code, is_day),
        description=describe(code),
        is_day=is_day,
        sunrise=daily["sunrise"][0],
        sunset=daily["sunset"][0],
        moon_phase=moon_name,
        moon_phase_fraction=moon_frac,
        observed_at=cur["time"],
    )

    # Hourly: pick next 9 slots starting from the hour after now
    now = datetime.fromisoformat(cur["time"])
    hourly_points: list[HourlyPoint] = []
    for i, t in enumerate(hourly["time"]):
        dt = datetime.fromisoformat(t)
        if dt < now:
            continue
        hc = int(hourly["weather_code"][i])
        hourly_points.append(HourlyPoint(
            time=t,
            temperature=float(hourly["temperature_2m"][i]),
            apparent_temperature=float(hourly["apparent_temperature"][i]),
            humidity=int(hourly["relative_humidity_2m"][i] or 0),
            weather_code=hc,
            icon=icon_for(hc, _is_daylight_for(t, daily)),
            description=describe(hc),
            precipitation=float(hourly["precipitation"][i] or 0.0),
            precipitation_probability=int(hourly["precipitation_probability"][i] or 0),
            wind_speed=float(hourly["wind_speed_10m"][i] or 0.0),
            wind_direction=int(hourly["wind_direction_10m"][i] or 0),
            wind_gust=float(hourly["wind_gusts_10m"][i] or 0.0),
            cloud_cover=int(hourly["cloud_cover"][i] or 0),
            uv_index=float(hourly["uv_index"][i] or 0.0),
            dewpoint=float(hourly["dew_point_2m"][i] or 0.0),
        ))
        if len(hourly_points) >= 24:
            break

    daily_points: list[DailyPoint] = []
    for i, d in enumerate(daily["time"]):
        dc = int(daily["weather_code"][i])
        daily_points.append(DailyPoint(
            date=d,
            weekday=_weekday(datetime.fromisoformat(d)),
            temperature_max=float(daily["temperature_2m_max"][i]),
            temperature_min=float(daily["temperature_2m_min"][i]),
            weather_code=dc,
            icon=icon_for(dc, True),
            description=describe(dc),
            precipitation_sum=float(daily["precipitation_sum"][i] or 0.0),
            precipitation_probability=int(daily["precipitation_probability_max"][i] or 0),
            wind_speed_max=float(daily["wind_speed_10m_max"][i] or 0.0),
            wind_direction=int(daily["wind_direction_10m_dominant"][i] or 0),
            sunrise=daily["sunrise"][i],
            sunset=daily["sunset"][i],
        ))

    return WeatherResponse(
        current=current,
        forecast=ForecastResponse(hourly=hourly_points[:24], daily=daily_points[:7]),
    )


def _is_daylight_for(iso_time: str, daily: dict) -> bool:
    dt = datetime.fromisoformat(iso_time)
    iso_date = dt.date().isoformat()
    try:
        idx = daily["time"].index(iso_date)
    except ValueError:
        return True
    sunrise = datetime.fromisoformat(daily["sunrise"][idx])
    sunset = datetime.fromisoformat(daily["sunset"][idx])
    return sunrise <= dt <= sunset


async def fetch(settings: Settings, client: httpx.AsyncClient | None = None) -> WeatherResponse:
    params = {
        "latitude": settings.latitude,
        "longitude": settings.longitude,
        "current": _CURRENT_FIELDS,
        "hourly": _HOURLY_FIELDS,
        "daily": _DAILY_FIELDS,
        "timezone": "auto",
        "temperature_unit": "celsius" if settings.metric else "fahrenheit",
        "wind_speed_unit": "kmh" if settings.metric else "mph",
        "precipitation_unit": "mm" if settings.metric else "inch",
    }
    owns = client is None
    client = client or httpx.AsyncClient(timeout=15.0)
    try:
        resp = await client.get(OPEN_METEO_URL, params=params)
        resp.raise_for_status()
        data = resp.json()
    finally:
        if owns:
            await client.aclose()

    weather = _normalize(data, settings)
    if settings.METAR:
        weather.metar = await _fetch_metar(settings.METAR)
    weather.alerts = await _fetch_alerts(settings.latitude, settings.longitude)
    return weather


_METAR_URL = "https://tgftp.nws.noaa.gov/data/observations/metar/stations/{station}.TXT"
_NWS_ALERTS_URL = "https://api.weather.gov/alerts/active"
_NWS_HEADERS = {"User-Agent": "PiClock/1.0 (contact github.com/ScottChapman/PiClock)"}


async def _fetch_metar(station: str) -> str | None:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(_METAR_URL.format(station=station))
        if resp.status_code != 200:
            return None
        lines = resp.text.strip().splitlines()
        return lines[-1] if lines else None
    except (httpx.HTTPError, asyncio.TimeoutError):
        return None


async def _fetch_alerts(lat: float, lng: float) -> list[WeatherAlert]:
    """NWS active alerts for a point. Returns [] on any failure (non-US, offline)."""
    params = {"point": f"{lat},{lng}"}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(_NWS_ALERTS_URL, params=params, headers=_NWS_HEADERS)
        if resp.status_code != 200:
            return []
        features = resp.json().get("features", [])
    except (httpx.HTTPError, asyncio.TimeoutError, ValueError):
        return []
    alerts: list[WeatherAlert] = []
    for f in features:
        p = f.get("properties", {})
        alerts.append(WeatherAlert(
            event=str(p.get("event", "Alert")),
            severity=str(p.get("severity", "Unknown")),
            headline=str(p.get("headline") or p.get("event", "")),
            ends=p.get("ends") or p.get("expires"),
        ))
    return alerts
