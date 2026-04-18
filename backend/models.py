"""Pydantic models for API responses."""

from __future__ import annotations

from pydantic import BaseModel


class CurrentWeather(BaseModel):
    temperature: float
    apparent_temperature: float
    humidity: int        # percent
    pressure: float      # hPa
    wind_speed: float
    wind_direction: int  # degrees
    wind_gust: float | None = None
    precipitation: float
    weather_code: int
    icon: str            # icon-set-agnostic base name, e.g. "clear-day"
    description: str
    is_day: bool
    sunrise: str         # ISO 8601 local time
    sunset: str
    moon_phase: str      # e.g. "Waxing Gibbous"
    moon_phase_fraction: float  # 0..1
    observed_at: str     # ISO 8601


class HourlyPoint(BaseModel):
    time: str            # ISO 8601 local
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


class DailyPoint(BaseModel):
    date: str            # ISO 8601 date
    weekday: str         # "Mon", "Tue", ...
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


class ForecastResponse(BaseModel):
    hourly: list[HourlyPoint]
    daily: list[DailyPoint]


class WeatherAlert(BaseModel):
    event: str            # e.g. "Winter Storm Warning"
    severity: str         # Minor|Moderate|Severe|Extreme|Unknown
    headline: str
    ends: str | None = None


class WeatherResponse(BaseModel):
    current: CurrentWeather
    forecast: ForecastResponse
    metar: str | None = None
    alerts: list[WeatherAlert] = []


class RadarFrame(BaseModel):
    time: int
    path: str


class RadarResponse(BaseModel):
    host: str
    past: list[RadarFrame]
    nowcast: list[RadarFrame] = []
    generated: int


class MarkerModel(BaseModel):
    location: tuple[float, float]
    color: str
    size: str


class RadarMapModel(BaseModel):
    center: tuple[float, float]
    zoom: int
    satellite: bool
    markers: list[MarkerModel]


class ConfigResponse(BaseModel):
    location: tuple[float, float]
    metric: bool
    wind_degrees: bool
    icons: str
    textcolor: str
    digital: bool
    digitalformat: str
    clockUTC: bool
    radar_refresh_minutes: int
    weather_refresh_minutes: int
    background_url: str
    radars: list[RadarMapModel]
    labels: dict[str, str]
