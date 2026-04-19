"""Plain-dataclass models shared between weather/radar fetchers and the UI.

These used to be pydantic BaseModels back when a FastAPI HTTP server
sat between the fetchers and the UI. Since the kiosk runs everything
in-process now, we don't need validation or JSON serialisation — a
dataclass is lighter, faster to construct, and drops the pydantic
dependency entirely.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CurrentWeather:
    temperature: float
    apparent_temperature: float
    humidity: int           # percent
    pressure: float         # hPa
    wind_speed: float
    wind_direction: int     # degrees
    wind_gust: float | None
    precipitation: float
    weather_code: int
    icon: str               # icon-set-agnostic base name, e.g. "clear-day"
    description: str
    is_day: bool
    sunrise: str            # ISO 8601 local time
    sunset: str
    moon_phase: str         # e.g. "Waxing Gibbous"
    moon_phase_fraction: float  # 0..1
    observed_at: str        # ISO 8601


@dataclass
class HourlyPoint:
    time: str               # ISO 8601 local
    temperature: float
    apparent_temperature: float
    humidity: int
    weather_code: int
    icon: str
    description: str
    precipitation: float
    precipitation_probability: int
    wind_speed: float
    wind_direction: int
    wind_gust: float
    cloud_cover: int
    uv_index: float
    dewpoint: float


@dataclass
class DailyPoint:
    date: str               # ISO 8601 date
    weekday: str            # "Mon", "Tue", …
    temperature_max: float
    temperature_min: float
    weather_code: int
    icon: str
    description: str
    precipitation_sum: float
    precipitation_probability: int
    wind_speed_max: float
    wind_direction: int
    sunrise: str
    sunset: str


@dataclass
class ForecastResponse:
    hourly: list[HourlyPoint]
    daily: list[DailyPoint]
    today_hourly: list[HourlyPoint] = field(default_factory=list)


@dataclass
class WeatherAlert:
    event: str              # e.g. "Winter Storm Warning"
    severity: str           # Minor | Moderate | Severe | Extreme | Unknown
    headline: str
    ends: str | None = None


@dataclass
class WeatherResponse:
    current: CurrentWeather
    forecast: ForecastResponse
    metar: str | None = None
    alerts: list[WeatherAlert] = field(default_factory=list)


@dataclass
class RadarFrame:
    time: int
    path: str


@dataclass
class RadarResponse:
    host: str
    past: list[RadarFrame]
    generated: int
    nowcast: list[RadarFrame] = field(default_factory=list)
