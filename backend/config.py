"""Load the user's Config.py (at repo root) into a typed dataclass.

Config.py is plain Python so it can be edited directly. We load it via importlib
rather than `import Config` so the same backend works from any CWD.
"""

from __future__ import annotations

import importlib.util
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = Path(os.environ.get("PICLOCK_CONFIG", REPO_ROOT / "Config.py"))


@dataclass(frozen=True)
class Marker:
    location: tuple[float, float]
    color: str = "red"
    size: str = "small"


@dataclass(frozen=True)
class RadarMap:
    center: tuple[float, float]
    zoom: int
    satellite: bool = False
    markers: tuple[Marker, ...] = ()


@dataclass(frozen=True)
class Labels:
    pressure: str = "Pressure "
    humidity: str = "Humidity "
    wind: str = "Wind "
    gusting: str = " gusting "
    feelslike: str = "Feels like "
    precip1hr: str = " Precip 1hr:"
    today: str = "Today: "
    sunrise: str = "Sun Rise:"
    sunset: str = " Set: "
    moonphase: str = " Moon Phase:"
    rain: str = " Rain: "
    snow: str = " Snow: "


@dataclass(frozen=True)
class Settings:
    location: tuple[float, float]
    metric: bool
    radar_refresh_minutes: int
    weather_refresh_minutes: int
    wind_degrees: bool
    background: str
    icons: str
    textcolor: str
    digital: bool
    digitalformat: str
    clockUTC: bool
    METAR: str
    date_locale: str
    labels: Labels
    radars: tuple[RadarMap, ...]
    google_api_key: str = ""

    @property
    def latitude(self) -> float:
        return self.location[0]

    @property
    def longitude(self) -> float:
        return self.location[1]


def _coerce_marker(raw: dict[str, Any]) -> Marker:
    loc = raw["location"]
    return Marker(
        location=(float(loc[0]), float(loc[1])),
        color=str(raw.get("color", "red")),
        size=str(raw.get("size", "small")),
    )


def _coerce_radar(raw: dict[str, Any]) -> RadarMap:
    center = raw["center"]
    markers = tuple(_coerce_marker(m) for m in raw.get("markers", ()))
    return RadarMap(
        center=(float(center[0]), float(center[1])),
        zoom=int(raw.get("zoom", 6)),
        satellite=bool(raw.get("satellite", False)),
        markers=markers,
    )


def load(path: Path | None = None) -> Settings:
    """Load Config.py from disk and return a Settings dataclass."""
    target = Path(path) if path else CONFIG_PATH
    spec = importlib.util.spec_from_file_location("user_config", target)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load config at {target}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def get(name: str, default: Any = None) -> Any:
        return getattr(module, name, default)

    labels = Labels(
        pressure=get("LPressure", "Pressure "),
        humidity=get("LHumidity", "Humidity "),
        wind=get("LWind", "Wind "),
        gusting=get("Lgusting", " gusting "),
        feelslike=get("LFeelslike", "Feels like "),
        precip1hr=get("LPrecip1hr", " Precip 1hr:"),
        today=get("LToday", "Today: "),
        sunrise=get("LSunRise", "Sun Rise:"),
        sunset=get("LSet", " Set: "),
        moonphase=get("LMoonPhase", " Moon Phase:"),
        rain=get("LRain", " Rain: "),
        snow=get("LSnow", " Snow: "),
    )

    radars_raw = []
    for key in ("radar1", "radar2"):
        r = get(key)
        if r:
            radars_raw.append(_coerce_radar(r))

    location_raw = get("location", (0.0, 0.0))

    # Pull googleapi from ApiKeys.py. Search order (first hit wins):
    #   1. $PICLOCK_APIKEYS   — explicit override
    #   2. ~/.config/piclock/ApiKeys.py  — XDG-ish user config
    #   3. ~/ApiKeys.py       — simple home-dir drop-in
    #   4. <repo>/ApiKeys.py  — legacy location (kept for existing setups)
    # Keeping credentials outside the repo means they don't get git-tracked.
    google_api_key = ""
    candidates: list[Path] = []
    env_override = os.environ.get("PICLOCK_APIKEYS")
    if env_override:
        candidates.append(Path(env_override).expanduser())
    home = Path.home()
    candidates += [
        home / ".config" / "piclock" / "ApiKeys.py",
        home / "ApiKeys.py",
        target.parent / "ApiKeys.py",
    ]
    for apikeys_path in candidates:
        if not apikeys_path.is_file():
            continue
        apikeys_spec = importlib.util.spec_from_file_location("user_apikeys", apikeys_path)
        if apikeys_spec is None or apikeys_spec.loader is None:
            continue
        apikeys_mod = importlib.util.module_from_spec(apikeys_spec)
        try:
            apikeys_spec.loader.exec_module(apikeys_mod)
            google_api_key = str(getattr(apikeys_mod, "googleapi", "") or "")
            break
        except Exception:
            continue

    return Settings(
        location=(float(location_raw[0]), float(location_raw[1])),
        metric=bool(get("metric", False)),
        radar_refresh_minutes=int(get("radar_refresh", 10)),
        weather_refresh_minutes=int(get("weather_refresh", 30)),
        wind_degrees=bool(get("wind_degrees", False)),
        background=str(get("background", "")),
        icons=str(get("icons", "icons-lightblue")),
        textcolor=str(get("textcolor", "#bef")),
        digital=bool(get("digital", False)),
        digitalformat=str(get("digitalformat", "%H:%M:%S")),
        clockUTC=bool(get("clockUTC", False)),
        METAR=str(get("METAR", "") or ""),
        date_locale=str(get("DateLocale", "") or ""),
        labels=labels,
        radars=tuple(radars_raw),
        google_api_key=google_api_key,
    )
