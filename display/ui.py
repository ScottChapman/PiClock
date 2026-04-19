"""Pygame rendering helpers for the PiClock kiosk.

Pure drawing code; no networking. Panels lay themselves out against
a Layout record computed once from the screen size.
"""

from __future__ import annotations

import io
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pygame

REPO_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = REPO_ROOT / "backend" / "static"
IMAGES_DIR = STATIC_DIR / "images"

# Text colours (match the web theme)
COL_TEXT = (187, 238, 255)
COL_TEXT_DIM = (150, 180, 200)
COL_TEXT_MUTED = (110, 130, 150)
COL_PANEL_BG = (0, 0, 0, 90)
COL_PANEL_BORDER = (60, 80, 100)

CARDINALS = ("N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
             "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW")


def wind_cardinal(deg: float) -> str:
    return CARDINALS[int((deg % 360) / 22.5 + 0.5) % 16]


@dataclass
class Layout:
    screen: pygame.Rect
    weather: pygame.Rect
    radar1: pygame.Rect
    radar2: pygame.Rect
    clock: pygame.Rect
    datestrip: pygame.Rect
    forecast: pygame.Rect


def compute_layout(size: tuple[int, int]) -> Layout:
    w, h = size
    pad = max(6, w // 200)
    # Columns 22% / 50% / 28% (matches the web layout the user approved)
    left_w = int(w * 0.22)
    right_w = int(w * 0.28)
    center_w = w - left_w - right_w - pad * 2

    left_x = pad
    center_x = left_x + left_w + pad
    right_x = center_x + center_w + pad

    y = pad
    inner_h = h - pad * 2

    # Left column: weather (28%) / radar1 (36%) / radar2 (36%)
    weather_h = int(inner_h * 0.28)
    radar_h = (inner_h - weather_h - pad * 2) // 2
    weather = pygame.Rect(left_x, y, left_w, weather_h)
    radar1 = pygame.Rect(left_x, y + weather_h + pad, left_w, radar_h)
    radar2 = pygame.Rect(left_x, y + weather_h + pad * 2 + radar_h, left_w, radar_h)

    # Center: clock (square) + date strip below
    clock_side = min(center_w, inner_h - int(inner_h * 0.08))
    clock = pygame.Rect(center_x + (center_w - clock_side) // 2, y, clock_side, clock_side)
    datestrip = pygame.Rect(center_x, y + clock_side, center_w, inner_h - clock_side)

    forecast = pygame.Rect(right_x, y, right_w, inner_h)

    screen_rect = pygame.Rect(0, 0, w, h)
    return Layout(screen_rect, weather, radar1, radar2, clock, datestrip, forecast)


# ----- asset loading ---------------------------------------------------------

@dataclass
class Fonts:
    huge: pygame.font.Font
    large: pygame.font.Font
    medium: pygame.font.Font
    medium_bold: pygame.font.Font
    small: pygame.font.Font
    small_bold: pygame.font.Font
    tiny: pygame.font.Font
    mono_huge: pygame.font.Font


def load_fonts(layout: Layout) -> Fonts:
    # Sizes derived from screen height so the UI scales.
    h = layout.screen.height
    body = "helveticaneue,arial"
    return Fonts(
        huge=pygame.font.SysFont(body, max(48, h // 12)),
        large=pygame.font.SysFont(body, max(28, h // 24)),
        medium=pygame.font.SysFont(body, max(18, h // 38)),
        medium_bold=pygame.font.SysFont(body, max(18, h // 38), bold=True),
        small=pygame.font.SysFont(body, max(14, h // 52)),
        small_bold=pygame.font.SysFont(body, max(14, h // 52), bold=True),
        tiny=pygame.font.SysFont(body, max(11, h // 68)),
        mono_huge=pygame.font.SysFont("couriernew,menlo,monospace", max(96, h // 5), bold=True),
    )


@dataclass
class Assets:
    clockface: pygame.Surface | None
    hour_hand: pygame.Surface | None
    minute_hand: pygame.Surface | None
    second_hand: pygame.Surface | None
    background: pygame.Surface | None
    icons: dict[str, pygame.Surface]
    icon_dir: str


def _safe_load(path: Path) -> pygame.Surface | None:
    try:
        return pygame.image.load(str(path)).convert_alpha()
    except (pygame.error, FileNotFoundError):
        return None


def load_assets(layout: Layout, config: dict | None) -> Assets:
    icon_dir = (config or {}).get("icons") or "icons-lightblue"
    clock_side = layout.clock.width
    face = _safe_load(IMAGES_DIR / "clockface3.png")
    if face is not None:
        # Scale first, then zero out the alpha band where "QUARTZ" sits in
        # the source PNG (~24% below centre). Doing it after smoothscale
        # avoids bilinear-interpolation ghosting at the cleared band's edges.
        face = pygame.transform.smoothscale(face, (clock_side, clock_side))
        hide = pygame.Rect(0, 0, int(clock_side * 0.30), int(clock_side * 0.08))
        hide.center = (clock_side // 2, clock_side // 2 + int(clock_side * 0.245))
        face.fill((0, 0, 0, 0), hide)
    # Hand PNGs are tall+narrow strips — scale so height matches clockface.
    def _scale_hand(name: str) -> pygame.Surface | None:
        img = _safe_load(IMAGES_DIR / name)
        if img is None:
            return None
        ow, oh = img.get_size()
        new_h = clock_side
        new_w = max(1, int(ow * (new_h / oh)))
        return pygame.transform.smoothscale(img, (new_w, new_h))
    hour_hand = _scale_hand("hourhand.png")
    minute_hand = _scale_hand("minhand.png")
    second_hand = _scale_hand("sechand.png")

    background = None
    bg_name = (config or {}).get("background", "")
    if bg_name:
        background = _safe_load(REPO_ROOT / bg_name)
        if background is not None:
            background = pygame.transform.smoothscale(background, layout.screen.size)

    # Pre-load every icon in the chosen set (there are only ~15 PNGs).
    icons: dict[str, pygame.Surface] = {}
    icon_folder = STATIC_DIR / icon_dir
    if icon_folder.is_dir():
        for p in icon_folder.glob("*.png"):
            img = _safe_load(p)
            if img is not None:
                icons[p.stem] = img

    return Assets(face, hour_hand, minute_hand, second_hand, background, icons, icon_dir)


def _icon(assets: Assets, name: str, size: int) -> pygame.Surface | None:
    img = assets.icons.get(name)
    if img is None:
        return None
    return pygame.transform.smoothscale(img, (size, size))


# ----- drawing ---------------------------------------------------------------

def draw_background(screen: pygame.Surface, assets: Assets) -> None:
    screen.fill((0, 0, 0))
    if assets.background is not None:
        screen.blit(assets.background, (0, 0))


def draw_panel_bg(screen: pygame.Surface, rect: pygame.Rect) -> None:
    panel = pygame.Surface(rect.size, pygame.SRCALPHA)
    panel.fill(COL_PANEL_BG)
    screen.blit(panel, rect.topleft)
    pygame.draw.rect(screen, COL_PANEL_BORDER, rect, width=1, border_radius=8)


def draw_clock(
    screen: pygame.Surface,
    layout: Layout,
    assets: Assets,
    fonts: Fonts,
    cfg: dict | None,
    now: datetime,
) -> None:
    digital = bool((cfg or {}).get("digital"))
    if digital:
        _draw_digital(screen, layout, fonts, cfg, now)
    else:
        _draw_analog(screen, layout, assets, now)
    _draw_date(screen, layout, fonts, cfg, now)


def _draw_analog(screen: pygame.Surface, layout: Layout, assets: Assets, now: datetime) -> None:
    rect = layout.clock
    if assets.clockface is not None:
        screen.blit(assets.clockface, rect.topleft)
    cx, cy = rect.center
    hour = now.hour % 12
    minute = now.minute
    second = now.second + now.microsecond / 1_000_000
    hour_angle = hour * 30 + minute * 0.5
    minute_angle = minute * 6 + second * 0.1
    second_angle = second * 6
    for hand, angle in (
        (assets.hour_hand, hour_angle),
        (assets.minute_hand, minute_angle),
        (assets.second_hand, second_angle),
    ):
        if hand is None:
            continue
        rotated = pygame.transform.rotozoom(hand, -angle, 1.0)
        r = rotated.get_rect(center=(cx, cy))
        screen.blit(rotated, r.topleft)


def _draw_digital(screen, layout: Layout, fonts: Fonts, cfg: dict | None, now: datetime) -> None:
    fmt = (cfg or {}).get("digitalformat", "%H:%M:%S")
    text = now.strftime(fmt)
    surf = fonts.mono_huge.render(text, True, COL_TEXT)
    r = surf.get_rect(center=layout.clock.center)
    screen.blit(surf, r.topleft)


def _draw_date(screen, layout: Layout, fonts: Fonts, cfg: dict | None, now: datetime) -> None:
    text = now.strftime("%A, %B %-d, %Y")
    surf = fonts.large.render(text, True, COL_TEXT)
    r = surf.get_rect(center=layout.datestrip.center)
    screen.blit(surf, r.topleft)


def _blit_text(screen: pygame.Surface, text: str, font: pygame.font.Font,
               colour, topleft: tuple[int, int]) -> pygame.Rect:
    surf = font.render(text, True, colour)
    screen.blit(surf, topleft)
    return surf.get_rect(topleft=topleft)


def _units(cfg: dict | None) -> dict[str, str]:
    metric = bool((cfg or {}).get("metric"))
    return {
        "temp": "\u00b0C" if metric else "\u00b0F",
        "speed": "km/h" if metric else "mph",
        "precip": "mm" if metric else "in",
    }


def draw_weather(
    screen: pygame.Surface,
    rect: pygame.Rect,
    weather: dict | None,
    assets: Assets,
    fonts: Fonts,
    cfg: dict | None,
) -> None:
    draw_panel_bg(screen, rect)
    if weather is None:
        _blit_text(screen, "Loading weather…", fonts.medium, COL_TEXT_DIM,
                   (rect.x + 12, rect.y + 12))
        return
    cur = weather.get("current", {})
    units = _units(cfg)
    pad = 10
    x = rect.x + pad
    y = rect.y + pad

    icon_size = min(rect.width // 3, rect.height // 2, 140)
    icon_surf = _icon(assets, cur.get("icon", "cloudy"), icon_size)
    if icon_surf is not None:
        screen.blit(icon_surf, (x, y))

    text_x = x + icon_size + pad
    temp = f"{round(cur.get('temperature', 0))}{units['temp']}"
    temp_surf = fonts.huge.render(temp, True, COL_TEXT)
    screen.blit(temp_surf, (text_x, y))
    desc = cur.get("description", "")
    _blit_text(screen, desc, fonts.medium, COL_TEXT_DIM,
               (text_x, y + temp_surf.get_height()))

    # Meta rows under the icon/temp
    meta_y = y + max(icon_size, temp_surf.get_height() + fonts.medium.get_height()) + pad
    line_h = fonts.small.get_height() + 2

    # "Next rain" headline: first upcoming hour with rain likely
    hourly = (weather.get("forecast") or {}).get("hourly") or []
    next_rain = _next_rain_headline(hourly, units)
    if next_rain:
        surf = fonts.small_bold.render(next_rain, True, (240, 200, 100))
        screen.blit(surf, (x, meta_y))
        meta_y += surf.get_height() + 3

    def _hhmm(iso: str) -> str:
        try:
            return datetime.fromisoformat(iso).strftime("%-I:%M %p")
        except ValueError:
            return iso

    lines: list[str] = []
    lines.append(
        f"Feels {round(cur.get('apparent_temperature', 0))}{units['temp']}  "
        f"Humidity {cur.get('humidity', 0)}%"
    )
    wind_dir = wind_cardinal(cur.get("wind_direction", 0))
    ws = round(cur.get("wind_speed", 0))
    gust = cur.get("wind_gust")
    wind = f"Wind {wind_dir} {ws}{units['speed']}"
    if gust and gust > cur.get("wind_speed", 0) + 3:
        wind += f" g{round(gust)}"
    # Combine wind + pressure on one line to make room for METAR
    lines.append(f"{wind}  {round(cur.get('pressure', 0))} hPa")
    lines.append(
        f"Sun {_hhmm(cur.get('sunrise', ''))} - {_hhmm(cur.get('sunset', ''))}"
    )
    lines.append(f"Moon {cur.get('moon_phase', '')}")

    # Parse METAR into a compact summary line (ceiling + visibility + dewpoint)
    # — the unique info the main API doesn't already supply.
    metar_line = _metar_summary(weather.get("metar"), units)
    if metar_line:
        lines.append(metar_line)

    for ln in lines:
        _blit_text(screen, ln, fonts.small, COL_TEXT_DIM, (x, meta_y))
        meta_y += line_h
        if meta_y > rect.bottom - pad:
            break


def _metar_summary(raw: str | None, units: dict) -> str | None:
    """Best-effort METAR parse → 'OVC 2200' · Vis 10mi · Dew 45°F'. None on fail."""
    if not raw:
        return None
    try:
        from metar import Metar
        m = Metar.Metar(raw)
    except Exception:
        return None
    parts: list[str] = []
    # Sky: lowest cloud layer with ceiling (BKN/OVC) — else first layer
    sky = getattr(m, "sky", None) or []
    ceiling = None
    for cover, height, *_ in sky:
        if cover in ("BKN", "OVC") and height is not None:
            ceiling = (cover, height)
            break
    if ceiling is None and sky:
        cover, height, *_ = sky[0]
        if height is not None:
            ceiling = (cover, height)
    if ceiling is not None:
        cover, height = ceiling
        ft = int(height.value("FT")) if hasattr(height, "value") else int(height)
        parts.append(f"{cover} {ft:,}'")
    vis = getattr(m, "vis", None)
    if vis is not None and hasattr(vis, "value"):
        try:
            miles = vis.value("SM")
            parts.append(f"Vis {miles:g}mi")
        except Exception:
            pass
    dewpt = getattr(m, "dewpt", None)
    if dewpt is not None and hasattr(dewpt, "value"):
        try:
            dp = dewpt.value("F" if units["temp"] == "\u00b0F" else "C")
            parts.append(f"Dew {round(dp)}{units['temp']}")
        except Exception:
            pass
    if not parts:
        return None
    return " \u00b7 ".join(parts)


def _next_rain_headline(hourly: list[dict], units: dict) -> str | None:
    """Return 'Rain likely 9 PM (86%)' if any of the next 12 hours crosses 50%."""
    for h in hourly[:12]:
        pop = int(h.get("precipitation_probability", 0) or 0)
        if pop >= 50:
            label = _time_of(h.get("time", ""))
            # Use weather-code description if it's rain/snow/thunderstorm; else generic
            desc = str(h.get("description", "Rain"))
            word = "Rain"
            lc = desc.lower()
            if "snow" in lc:
                word = "Snow"
            elif "thunder" in lc:
                word = "Storms"
            elif "showers" in lc:
                word = "Showers"
            return f"{word} likely {label} ({pop}%)"
    return None


def draw_forecast(
    screen: pygame.Surface,
    rect: pygame.Rect,
    weather: dict | None,
    assets: Assets,
    fonts: Fonts,
    cfg: dict | None,
) -> None:
    draw_panel_bg(screen, rect)
    if weather is None:
        _blit_text(screen, "Loading forecast…", fonts.medium, COL_TEXT_DIM,
                   (rect.x + 12, rect.y + 12))
        return
    units = _units(cfg)
    wind_degrees = bool((cfg or {}).get("wind_degrees"))
    forecast = weather.get("forecast", {})
    hourly_all = forecast.get("hourly", [])
    hourly = hourly_all[:4]
    daily = forecast.get("daily", [])[:6]
    alerts = weather.get("alerts", []) or []
    today_hourly = forecast.get("today_hourly") or hourly_all

    pad = 12
    x = rect.x + pad
    y = rect.y + pad
    inner_right = rect.right - pad

    # Active-alert banner (top of panel)
    if alerts:
        y = _draw_alert_banner(screen, alerts[0], fonts, x, y, inner_right)

    # Today-at-a-glance diorama ribbon (sky gradient + temp curve + precip).
    diorama_h = 176
    if len(today_hourly) >= 8:
        from .diorama import draw_day_diorama
        draw_day_diorama(
            screen,
            pygame.Rect(x, y, inner_right - x, diorama_h),
            today_hourly,
            daily[0] if daily else None,
            weather.get("current", {}),
            assets,
            fonts,
            units,
            datetime.now(),
        )
        y += diorama_h + 6

    title_h = fonts.small_bold.get_height()
    total_rows = len(hourly) + len(daily)
    remaining = rect.bottom - y - pad - title_h * 2 - 8
    row_h = max(44, remaining // max(1, total_rows))
    icon_size = max(34, int(row_h * 0.78))

    # HOURLY section
    _draw_section_title(screen, fonts, "HOURLY", x, y, inner_right)
    y += title_h + 4
    for i, h in enumerate(hourly):
        _draw_forecast_row(
            screen, fonts, assets,
            x, y, inner_right, row_h, icon_size,
            label=_time_of(h.get("time", "")),
            icon_name=h.get("icon", "cloudy"),
            primary=h.get("description", ""),
            meta=_hourly_meta(h, units, wind_degrees),
            right_top=f"{round(h.get('temperature', 0))}{units['temp']}",
            right_bot=f"feels {round(h.get('apparent_temperature', 0))}\u00b0",
            top_rule=i > 0,
        )
        y += row_h

    # DAILY section
    y += 4
    _draw_section_title(screen, fonts, "DAILY", x, y, inner_right)
    y += title_h + 4
    for i, d in enumerate(daily):
        _draw_forecast_row(
            screen, fonts, assets,
            x, y, inner_right, row_h, icon_size,
            label=d.get("weekday", ""),
            icon_name=d.get("icon", "cloudy"),
            primary=d.get("description", ""),
            meta=_daily_meta(d, units, wind_degrees),
            right_top=f"{round(d.get('temperature_min', 0))}\u00b0/"
                      f"{round(d.get('temperature_max', 0))}{units['temp']}",
            right_bot=_sun_times(d),
            top_rule=i > 0,
        )
        y += row_h
        if y > rect.bottom - row_h // 2:
            break


def _severity_color(severity: str) -> tuple[int, int, int]:
    sev = severity.lower()
    if sev in ("extreme", "severe"):
        return (220, 70, 70)
    if sev == "moderate":
        return (220, 160, 60)
    return (180, 180, 120)


def _draw_alert_banner(screen, alert: dict, fonts: Fonts, x: int, y: int, right: int) -> int:
    event = alert.get("event", "Alert")
    severity = alert.get("severity", "Unknown")
    colour = _severity_color(severity)
    pad_x, pad_y = 8, 5
    surf = fonts.small_bold.render(event, True, (255, 255, 255))
    width = right - x
    height = surf.get_height() + pad_y * 2
    bg = pygame.Surface((width, height), pygame.SRCALPHA)
    bg.fill(colour + (220,))
    screen.blit(bg, (x, y))
    screen.blit(surf, (x + pad_x, y + pad_y))
    return y + height + 6


def _draw_section_title(screen, fonts: Fonts, text: str, x: int, y: int, right: int) -> None:
    # Small-caps-style section label with a thin rule alongside it.
    surf = fonts.small_bold.render(text, True, COL_TEXT_MUTED)
    screen.blit(surf, (x, y))
    line_y = y + surf.get_height() // 2
    pygame.draw.line(screen, COL_PANEL_BORDER,
                     (x + surf.get_width() + 8, line_y),
                     (right, line_y), 1)


def _hourly_meta(h: dict, units: dict, wind_degrees: bool) -> str:
    # Priority order: rain (most actionable) → wind → humidity → UV.
    parts: list[str] = []
    pop = h.get("precipitation_probability", 0) or 0
    precip = h.get("precipitation", 0) or 0
    if pop or precip > 0:
        rain = f"{pop}% rain"
        if precip > 0:
            rain += f" {precip:.2f}{units['precip']}"
        parts.append(rain)
    parts.append(_wind_phrase(h.get("wind_direction", 0),
                              h.get("wind_speed", 0),
                              h.get("wind_gust") or 0,
                              units, wind_degrees))
    parts.append(f"{h.get('humidity', 0)}% humid")
    uv = h.get("uv_index", 0) or 0
    if uv >= 3:
        parts.append(f"UV {round(uv)}")
    return " \u00b7 ".join(parts)


def _daily_meta(d: dict, units: dict, wind_degrees: bool) -> str:
    parts: list[str] = []
    pop = d.get("precipitation_probability", 0) or 0
    precip = d.get("precipitation_sum", 0) or 0
    if pop or precip > 0:
        rain = f"{pop}% rain"
        if precip > 0:
            rain += f" {precip:.2f}{units['precip']}"
        parts.append(rain)
    parts.append(_wind_phrase(d.get("wind_direction", 0),
                              d.get("wind_speed_max", 0),
                              0,
                              units, wind_degrees))
    return " \u00b7 ".join(parts)


def _wind_phrase(direction: int, speed: float, gust: float,
                 units: dict, wind_degrees: bool) -> str:
    wd = f"{direction}\u00b0" if wind_degrees else wind_cardinal(direction)
    ws = round(speed)
    # Use range notation when gusts are notably higher than sustained.
    if gust and gust > speed + 3:
        return f"{wd} {ws}\u2013{round(gust)} {units['speed']}"
    return f"{wd} {ws} {units['speed']}"


def _sun_times(d: dict) -> str:
    def _hhmm(iso: str) -> str:
        try:
            return datetime.fromisoformat(iso).strftime("%-I:%M")
        except (ValueError, TypeError):
            return ""
    return f"{_hhmm(d.get('sunrise', ''))}a / {_hhmm(d.get('sunset', ''))}p"


def _draw_forecast_row(
    screen, fonts: Fonts, assets: Assets,
    x: int, y: int, right: int, row_h: int, icon_size: int,
    label: str, icon_name: str,
    primary: str, meta: str,
    right_top: str, right_bot: str | None,
    top_rule: bool = False,
) -> None:
    if top_rule:
        pygame.draw.line(screen, (*COL_PANEL_BORDER[:3], 100),
                         (x, y), (right, y), 1)
    # Left gutter: time/weekday label — bigger, more prominent
    label_w = max(fonts.small_bold.size("00:00 PM")[0], fonts.small_bold.size("Wed")[0]) + 4
    label_surf = fonts.small_bold.render(label, True, COL_TEXT)
    screen.blit(label_surf, (x, y + (row_h - label_surf.get_height()) // 2))

    # Icon
    icon_x = x + label_w
    icon_surf = _icon(assets, icon_name, icon_size)
    if icon_surf is not None:
        screen.blit(icon_surf, (icon_x, y + (row_h - icon_size) // 2))

    # Right column: temp (bold, medium) over feels/sun-times (tiny, muted)
    right_surfs: list[pygame.Surface] = []
    if right_top:
        right_surfs.append(fonts.medium_bold.render(right_top, True, COL_TEXT))
    if right_bot:
        right_surfs.append(fonts.tiny.render(right_bot, True, COL_TEXT_MUTED))
    right_w = max((s.get_width() for s in right_surfs), default=0)
    right_x = right - right_w
    ry = y + (row_h - sum(s.get_height() for s in right_surfs)) // 2
    for s in right_surfs:
        # Right-align each inside the right column
        screen.blit(s, (right_x + (right_w - s.get_width()), ry))
        ry += s.get_height()

    # Middle column: description (medium) on top, meta (tiny, muted) below
    desc_x = icon_x + icon_size + 8
    max_desc_w = right_x - desc_x - 8
    primary_surf = fonts.medium.render(_clip(primary, fonts.medium, max_desc_w), True, COL_TEXT)
    meta_surf = fonts.tiny.render(_clip(meta, fonts.tiny, max_desc_w), True, COL_TEXT_MUTED)
    total_h = primary_surf.get_height() + meta_surf.get_height()
    ty = y + (row_h - total_h) // 2
    screen.blit(primary_surf, (desc_x, ty))
    screen.blit(meta_surf, (desc_x, ty + primary_surf.get_height()))



def _clip(text: str, font: pygame.font.Font, max_w: int) -> str:
    if font.size(text)[0] <= max_w:
        return text
    while text and font.size(text + "…")[0] > max_w:
        text = text[:-1]
    return text + "…"


def _time_of(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).strftime("%-I %p").lstrip("0")
    except ValueError:
        return iso


def draw_radar(
    screen: pygame.Surface,
    rect: pygame.Rect,
    frame_surface: pygame.Surface | None,
    fonts: Fonts,
    label: str,
    frame_time: int | None,
) -> None:
    draw_panel_bg(screen, rect)
    if frame_surface is None:
        _blit_text(screen, "Radar loading…", fonts.small, COL_TEXT_DIM,
                   (rect.x + 10, rect.y + 10))
        return
    # Cover-scale the pre-rendered PNG (typically 512x512) so it fills the
    # panel, then mask with a rounded rectangle so corners match the chrome.
    src_w, src_h = frame_surface.get_size()
    scale = max(rect.width / src_w, rect.height / src_h)
    dst_w = int(src_w * scale)
    dst_h = int(src_h * scale)
    scaled = pygame.transform.smoothscale(frame_surface, (dst_w, dst_h))
    panel = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
    panel.blit(scaled, ((rect.width - dst_w) // 2, (rect.height - dst_h) // 2))
    mask = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
    pygame.draw.rect(mask, (255, 255, 255, 255), mask.get_rect(), border_radius=8)
    panel.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MIN)
    screen.blit(panel, rect.topleft)

    # Corner label + time — bold, opaque chip so it reads while animating
    if frame_time is not None:
        try:
            ts = datetime.fromtimestamp(frame_time).strftime("%-I:%M %p")
        except (OSError, ValueError):
            ts = ""
        stamp = fonts.small_bold.render(f"{label}  {ts}", True, COL_TEXT)
        pad_x, pad_y = 7, 4
        bg = pygame.Surface(
            (stamp.get_width() + pad_x * 2, stamp.get_height() + pad_y * 2),
            pygame.SRCALPHA,
        )
        bg.fill((0, 0, 0, 210))
        pygame.draw.rect(bg, (255, 255, 255, 40), bg.get_rect(), width=1)
        screen.blit(bg, (rect.x + 6, rect.y + 6))
        screen.blit(stamp, (rect.x + 6 + pad_x, rect.y + 6 + pad_y))
