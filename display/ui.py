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
        face = pygame.transform.smoothscale(face, (clock_side, clock_side))
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
    bg_url = (config or {}).get("background_url", "")
    if bg_url.startswith("/bg/"):
        bg_path = REPO_ROOT / bg_url[len("/bg/"):]
        background = _safe_load(bg_path)
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
    lines: list[str] = []
    lines.append(f"Feels {round(cur.get('apparent_temperature', 0))}{units['temp']}  "
                 f"Humidity {cur.get('humidity', 0)}%")
    wind_dir = wind_cardinal(cur.get("wind_direction", 0))
    ws = round(cur.get("wind_speed", 0))
    gust = cur.get("wind_gust")
    wind = f"Wind {wind_dir} {ws}{units['speed']}"
    if gust and gust > cur.get("wind_speed", 0) + 3:
        wind += f" g{round(gust)}"
    lines.append(wind)
    lines.append(f"Pressure {round(cur.get('pressure', 0))} hPa")

    def _hhmm(iso: str) -> str:
        try:
            return datetime.fromisoformat(iso).strftime("%-I:%M %p")
        except ValueError:
            return iso

    lines.append(f"Sunrise {_hhmm(cur.get('sunrise', ''))}")
    lines.append(f"Sunset  {_hhmm(cur.get('sunset', ''))}")
    lines.append(f"Moon: {cur.get('moon_phase', '')}")
    metar = weather.get("metar")
    if metar:
        lines.append(metar[:48])

    for ln in lines:
        _blit_text(screen, ln, fonts.small, COL_TEXT_DIM, (x, meta_y))
        meta_y += line_h
        if meta_y > rect.bottom - pad:
            break


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
    hourly = forecast.get("hourly", [])[:5]
    daily = forecast.get("daily", [])[:7]

    pad = 12
    x = rect.x + pad
    y = rect.y + pad
    inner_right = rect.right - pad

    # Distribute vertical space: section titles + 5 hourly + 7 daily rows + small gap.
    title_h = fonts.small_bold.get_height()
    total_rows = len(hourly) + len(daily)
    available = rect.height - pad * 2 - title_h * 2 - 16
    row_h = max(48, available // max(1, total_rows))
    icon_size = max(36, int(row_h * 0.78))

    # HOURLY section
    _draw_section_title(screen, fonts, "HOURLY", x, y, inner_right)
    y += title_h + 4
    for h in hourly:
        _draw_forecast_row(
            screen, fonts, assets,
            x, y, inner_right, row_h, icon_size,
            label=_time_of(h.get("time", "")),
            icon_name=h.get("icon", "cloudy"),
            primary=h.get("description", ""),
            meta=_hourly_meta(h, units, wind_degrees),
            right_top=f"{round(h.get('temperature', 0))}{units['temp']}",
            right_bot=f"feels {round(h.get('apparent_temperature', 0))}\u00b0",
        )
        y += row_h

    # DAILY section
    y += 6
    _draw_section_title(screen, fonts, "DAILY", x, y, inner_right)
    y += title_h + 4
    for d in daily:
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
        )
        y += row_h
        if y > rect.bottom - row_h // 2:
            break


def _draw_section_title(screen, fonts: Fonts, text: str, x: int, y: int, right: int) -> None:
    # Small-caps-style section label with a thin rule alongside it.
    surf = fonts.small_bold.render(text, True, COL_TEXT_MUTED)
    screen.blit(surf, (x, y))
    line_y = y + surf.get_height() // 2
    pygame.draw.line(screen, COL_PANEL_BORDER,
                     (x + surf.get_width() + 8, line_y),
                     (right, line_y), 1)


def _hourly_meta(h: dict, units: dict, wind_degrees: bool) -> str:
    wd = f"{h.get('wind_direction', 0)}\u00b0" if wind_degrees else wind_cardinal(h.get("wind_direction", 0))
    ws = round(h.get("wind_speed", 0))
    wind = f"{wd} {ws}{units['speed']}"
    gust = h.get("wind_gust") or 0
    if gust and gust > h.get("wind_speed", 0) + 3:
        wind += f" g{round(gust)}"
    parts = [wind, f"{h.get('humidity', 0)}%RH"]
    pop = h.get("precipitation_probability", 0) or 0
    precip = h.get("precipitation", 0) or 0
    if pop or precip > 0:
        rain = f"{pop}%"
        if precip > 0:
            rain += f" {precip:.2f}{units['precip']}"
        parts.append(rain)
    uv = h.get("uv_index", 0) or 0
    if uv >= 1:
        parts.append(f"UV{round(uv)}")
    return " \u00b7 ".join(parts)


def _daily_meta(d: dict, units: dict, wind_degrees: bool) -> str:
    wd = f"{d.get('wind_direction', 0)}\u00b0" if wind_degrees else wind_cardinal(d.get("wind_direction", 0))
    ws = round(d.get("wind_speed_max", 0))
    parts = [f"{wd} {ws}{units['speed']}"]
    pop = d.get("precipitation_probability", 0) or 0
    precip = d.get("precipitation_sum", 0) or 0
    if pop or precip > 0:
        rain = f"{pop}%"
        if precip > 0:
            rain += f" {precip:.2f}{units['precip']}"
        parts.append(rain)
    return " \u00b7 ".join(parts)


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
) -> None:
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

    # Hairline row separator
    pygame.draw.line(screen, (*COL_PANEL_BORDER[:3], 100),
                     (x, y + row_h - 1), (right, y + row_h - 1), 1)


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
    # Scale the pre-rendered PNG (typically 512x512) to fit the panel.
    src_w, src_h = frame_surface.get_size()
    scale = min(rect.width / src_w, rect.height / src_h)
    dst_w = int(src_w * scale)
    dst_h = int(src_h * scale)
    scaled = pygame.transform.smoothscale(frame_surface, (dst_w, dst_h))
    dst_x = rect.x + (rect.width - dst_w) // 2
    dst_y = rect.y + (rect.height - dst_h) // 2
    screen.blit(scaled, (dst_x, dst_y))

    # Corner label + time
    if frame_time is not None:
        try:
            ts = datetime.fromtimestamp(frame_time).strftime("%-I:%M %p")
        except (OSError, ValueError):
            ts = ""
        stamp = fonts.tiny.render(f"{label}  {ts}", True, COL_TEXT_DIM)
        pad = 4
        bg = pygame.Surface((stamp.get_width() + pad * 2, stamp.get_height() + pad), pygame.SRCALPHA)
        bg.fill((0, 0, 0, 140))
        screen.blit(bg, (rect.x + 4, rect.y + 4))
        screen.blit(stamp, (rect.x + 4 + pad, rect.y + 4))
