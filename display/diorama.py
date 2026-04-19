"""Day-at-a-glance diorama ribbon.

Replaces the 56px temp sparkline with a ~160px-tall ribbon whose background
is literally the sky through the day (dawn / day / dusk / night), with the
temperature curve, apparent-temperature line, cloud haze, precipitation
columns, sunrise/sunset markers, weather-icon callouts, and a "now" cursor
layered on top.

Input data is the `today_hourly` list (today 00:00 local → tomorrow 00:00
local, inclusive) produced by backend.weather._normalize.
"""

from __future__ import annotations

from datetime import datetime

import pygame

from . import ui as _ui  # for _icon, Assets, Fonts, COL_* palette


# ----- palette --------------------------------------------------------------

# Sky anchors. Hour fractions 0..24; two endpoints pinned to deep night so
# the loop seams cleanly. Pre-dawn / sunrise / morning / midday / late-afternoon /
# sunset / dusk stops are derived per-draw from the actual sunrise/sunset.
_NIGHT_RGB     = (6, 10, 28)
_PREDAWN_RGB   = (30, 30, 70)
_SUNRISE_RGB   = (245, 150, 90)
_MORNING_RGB   = (140, 180, 220)
_MIDDAY_RGB    = (90, 150, 215)
_LATE_RGB      = (180, 180, 200)
_SUNSET_RGB    = (240, 130, 70)
_DUSK_RGB      = (40, 40, 85)

# ----- geometry -------------------------------------------------------------

_ICON_ROW_TOP   = 2
_ICON_ROW_BOT   = 26
_PLOT_TOP       = 30
_PLOT_BOT       = 130
_PRECIP_MAX_H   = 70    # tall-enough bars, drawn from precip baseline upward
_PRECIP_BASE    = 142   # baseline where precip columns originate
_AXIS_Y         = 144
_LEGEND_Y       = 160


# ----- caches ---------------------------------------------------------------

_sky_cache: dict[tuple[float, float, int, int], pygame.Surface] = {}


# ----- helpers --------------------------------------------------------------

def _hour_frac(iso: str) -> float:
    dt = datetime.fromisoformat(iso)
    return dt.hour + dt.minute / 60.0 + dt.second / 3600.0


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _lerp_rgb(c1: tuple[int, int, int], c2: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return (
        int(_lerp(c1[0], c2[0], t)),
        int(_lerp(c1[1], c2[1], t)),
        int(_lerp(c1[2], c2[2], t)),
    )


def _interp_stops(stops: list[tuple[float, tuple[int, int, int]]], x: float) -> tuple[int, int, int]:
    if x <= stops[0][0]:
        return stops[0][1]
    if x >= stops[-1][0]:
        return stops[-1][1]
    for (x0, c0), (x1, c1) in zip(stops, stops[1:]):
        if x0 <= x <= x1:
            t = (x - x0) / (x1 - x0) if x1 != x0 else 0.0
            return _lerp_rgb(c0, c1, t)
    return stops[-1][1]


def _sky_stops(sr: float, ss: float) -> list[tuple[float, tuple[int, int, int]]]:
    sr = max(1.0, min(23.0, sr))
    ss = max(sr + 2.0, min(23.5, ss))
    mid = (sr + ss) / 2.0
    stops: list[tuple[float, tuple[int, int, int]]] = [
        (0.0,                    _NIGHT_RGB),
        (max(0.0, sr - 0.75),    _PREDAWN_RGB),
        (sr,                     _SUNRISE_RGB),
        (sr + 1.0,               _MORNING_RGB),
        (mid,                    _MIDDAY_RGB),
        (ss - 1.0,               _LATE_RGB),
        (ss,                     _SUNSET_RGB),
        (min(24.0, ss + 0.75),   _DUSK_RGB),
        (24.0,                   _NIGHT_RGB),
    ]
    # Guarantee monotonic anchors — edge cases with tight sunrise/sunset.
    out: list[tuple[float, tuple[int, int, int]]] = []
    last = -1.0
    for h, c in stops:
        if h <= last:
            h = last + 0.001
        out.append((h, c))
        last = h
    return out


def _sky_surface(band_w: int, band_h: int, sr: float, ss: float) -> pygame.Surface:
    key = (round(sr, 2), round(ss, 2), band_w, band_h)
    cached = _sky_cache.get(key)
    if cached is not None:
        return cached
    stops = _sky_stops(sr, ss)
    surf = pygame.Surface((band_w, band_h)).convert()
    for px in range(band_w):
        hf = px / max(1, band_w - 1) * 24.0
        col = _interp_stops(stops, hf)
        pygame.draw.line(surf, col, (px, 0), (px, band_h - 1))
    _sky_cache[key] = surf
    return surf


# ----- sub-renderers --------------------------------------------------------

def _draw_cloud_haze(
    target: pygame.Surface, rect: pygame.Rect, points: list[dict],
) -> None:
    if not points:
        return
    n = len(points)
    strip_w = max(1, rect.width // max(1, n - 1 if n > 1 else 1))
    for i, p in enumerate(points[:-1]):
        cc = int(p.get("cloud_cover", 0) or 0)
        if cc <= 0:
            continue
        alpha = int(min(80, cc / 100.0 * 80))
        strip = pygame.Surface((strip_w, rect.height), pygame.SRCALPHA)
        strip.fill((235, 240, 250, alpha))
        x = rect.x + int(i / max(1, n - 1) * rect.width)
        target.blit(strip, (x, rect.y))


def _draw_precip_columns(
    target: pygame.Surface, rect: pygame.Rect, points: list[dict],
    baseline_y: int, max_h: int,
) -> None:
    if not points:
        return
    n = len(points)
    step = rect.width / max(1, n - 1)
    col_w = max(1, int(step * 0.9))
    for i, p in enumerate(points):
        pop = int(p.get("precipitation_probability", 0) or 0)
        if pop <= 0:
            continue
        precip = float(p.get("precipitation", 0) or 0)
        h = int(max_h * pop / 100.0)
        if h <= 0:
            continue
        colour = (50, 110, 200, 210) if precip > 0 else (80, 160, 220, 150)
        col = pygame.Surface((col_w, h), pygame.SRCALPHA)
        col.fill(colour)
        x = rect.x + int(i * step) - col_w // 2
        target.blit(col, (x, baseline_y - h))


def _temp_y(t: float, t_min: float, t_max: float) -> int:
    if t_max == t_min:
        return (_PLOT_TOP + _PLOT_BOT) // 2
    frac = (t - t_min) / (t_max - t_min)
    return int(_PLOT_BOT - frac * (_PLOT_BOT - _PLOT_TOP))


def _draw_temp_layer(
    target: pygame.Surface, rect: pygame.Rect, points: list[dict],
    t_min: float, t_max: float,
) -> None:
    if len(points) < 2:
        return
    n = len(points)
    step = rect.width / max(1, n - 1)

    # Gradient fill under the curve — single warm-amber translucent polygon.
    poly: list[tuple[int, int]] = []
    for i, p in enumerate(points):
        x = rect.x + int(i * step)
        y = rect.y + _temp_y(float(p.get("temperature", 0) or 0), t_min, t_max)
        poly.append((x, y))
    poly.append((rect.x + rect.width, rect.y + _PLOT_BOT))
    poly.append((rect.x, rect.y + _PLOT_BOT))

    fill = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
    local = [(px - rect.x, py - rect.y) for (px, py) in poly]
    pygame.draw.polygon(fill, (255, 210, 140, 140), local)
    target.blit(fill, rect.topleft)

    # Single clean warm-white polyline with a 2px dark underglow.
    line_pts = [
        (rect.x + int(i * step), rect.y + _temp_y(float(p.get("temperature", 0) or 0), t_min, t_max))
        for i, p in enumerate(points)
    ]
    shadow_pts = [(x, y + 2) for (x, y) in line_pts]
    pygame.draw.lines(target, (0, 0, 0), False, shadow_pts, 3)
    pygame.draw.lines(target, (255, 240, 200), False, line_pts, 3)


def _draw_apparent_line(
    target: pygame.Surface, rect: pygame.Rect, points: list[dict],
    t_min: float, t_max: float,
) -> None:
    if len(points) < 2:
        return
    n = len(points)
    step = rect.width / max(1, n - 1)
    # Build dashed path (4px on / 4px off) along the polyline.
    surf = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
    for i in range(n - 1):
        t0 = float(points[i].get("apparent_temperature", 0) or 0)
        t1 = float(points[i + 1].get("apparent_temperature", 0) or 0)
        x0 = int(i * step)
        x1 = int((i + 1) * step)
        y0 = _temp_y(t0, t_min, t_max)
        y1 = _temp_y(t1, t_min, t_max)
        _dashed_line(surf, (40, 50, 70, 220), (x0, y0), (x1, y1), dash=5, gap=4, width=2)
    target.blit(surf, rect.topleft)


def _dashed_line(
    surf: pygame.Surface, colour: tuple[int, int, int, int],
    p0: tuple[int, int], p1: tuple[int, int],
    dash: int, gap: int, width: int,
) -> None:
    x0, y0 = p0
    x1, y1 = p1
    dx, dy = x1 - x0, y1 - y0
    length = (dx * dx + dy * dy) ** 0.5
    if length == 0:
        return
    ux, uy = dx / length, dy / length
    pos = 0.0
    on = True
    while pos < length:
        step = dash if on else gap
        seg = min(step, length - pos)
        sx, sy = x0 + ux * pos, y0 + uy * pos
        ex, ey = x0 + ux * (pos + seg), y0 + uy * (pos + seg)
        if on:
            pygame.draw.line(surf, colour, (int(sx), int(sy)), (int(ex), int(ey)), width)
        pos += seg
        on = not on


def _draw_sun_markers(
    target: pygame.Surface, rect: pygame.Rect, fonts: _ui.Fonts,
    sr: float, ss: float,
) -> None:
    band_w = rect.width
    for hf, glyph in ((sr, "\u2600"), (ss, "\u263d")):
        if hf <= 0 or hf >= 24:
            continue
        x = rect.x + int(hf / 24.0 * band_w)
        # Dotted vertical line.
        for y in range(rect.y + 2, rect.y + rect.height - 2, 4):
            pygame.draw.line(target, (255, 255, 255), (x, y), (x, y + 2), 1)
        glyph_surf = fonts.small.render(glyph, True, (255, 230, 180))
        target.blit(glyph_surf, (x - glyph_surf.get_width() // 2,
                                 rect.y + _PLOT_BOT - glyph_surf.get_height() - 2))


def _draw_now_cursor(
    target: pygame.Surface, rect: pygame.Rect, fonts: _ui.Fonts,
    now_hf: float, current_temp: float, unit_label: str,
) -> None:
    if now_hf < 0 or now_hf > 24:
        return
    x = rect.x + int(now_hf / 24.0 * rect.width)
    pygame.draw.line(target, (255, 230, 120), (x, rect.y + 2), (x, rect.y + _PLOT_BOT), 2)
    text = f"{round(current_temp)}{unit_label}"
    surf = fonts.small_bold.render(text, True, (255, 255, 255))
    chip = pygame.Surface((surf.get_width() + 10, surf.get_height() + 4), pygame.SRCALPHA)
    chip.fill((0, 0, 0, 180))
    pygame.draw.rect(chip, (255, 230, 120), chip.get_rect(), width=1)
    chip.blit(surf, (5, 2))
    cx = max(rect.x, min(rect.right - chip.get_width(), x - chip.get_width() // 2))
    target.blit(chip, (cx, rect.y + 2))


def _draw_hour_axis(target: pygame.Surface, rect: pygame.Rect, fonts: _ui.Fonts) -> None:
    for hf, label in ((6.0, "6a"), (12.0, "12p"), (18.0, "6p")):
        x = rect.x + int(hf / 24.0 * rect.width)
        surf = fonts.tiny.render(label, True, _ui.COL_TEXT_MUTED)
        target.blit(surf, (x - surf.get_width() // 2, rect.y + _AXIS_Y))


def _draw_legend(target: pygame.Surface, rect: pygame.Rect, fonts: _ui.Fonts) -> None:
    # Key row below the axis so it doesn't collide with hour labels.
    y = rect.y + _LEGEND_Y
    gap = 6
    glyph_w = 12
    items = (
        ("line", (255, 240, 200, 255), "temp"),
        ("dash", (20, 30, 50, 255),    "feels"),
        ("bar",  (80, 160, 220, 220),  "rain"),
    )
    # Measure total width so we can centre the key on the band.
    label_surfs = [fonts.tiny.render(t, True, _ui.COL_TEXT) for _, _, t in items]
    total = sum(s.get_width() + glyph_w + 4 for s in label_surfs) + gap * (len(items) - 1)
    x = rect.x + (rect.width - total) // 2
    gy = y + fonts.tiny.get_height() // 2
    for (kind, colour, _), surf in zip(items, label_surfs):
        if kind == "line":
            pygame.draw.line(target, colour[:3], (x, gy), (x + glyph_w, gy), 2)
        elif kind == "dash":
            pygame.draw.line(target, colour[:3], (x, gy), (x + 4, gy), 2)
            pygame.draw.line(target, colour[:3], (x + glyph_w - 4, gy), (x + glyph_w, gy), 2)
        elif kind == "bar":
            bar = pygame.Surface((glyph_w - 2, 8), pygame.SRCALPHA)
            bar.fill(colour)
            target.blit(bar, (x + 1, gy - 4))
        target.blit(surf, (x + glyph_w + 4, y))
        x += glyph_w + 4 + surf.get_width() + gap


def _draw_icon_callouts(
    target: pygame.Surface, rect: pygame.Rect, assets: _ui.Assets,
    points: list[dict], now_hf: float,
) -> None:
    if not points:
        return
    target_hours = (9.0, 13.0, 18.0)
    n = len(points)
    for hf in target_hours:
        if abs(hf - now_hf) < 0.6:
            continue  # collides with now-cursor chip
        idx = min(n - 1, max(0, int(hf)))
        icon_name = points[idx].get("icon") or "cloudy"
        icon = _ui._icon(assets, icon_name, _ICON_ROW_BOT - _ICON_ROW_TOP)
        if icon is None:
            continue
        x = rect.x + int(hf / 24.0 * rect.width) - icon.get_width() // 2
        target.blit(icon, (x, rect.y + _ICON_ROW_TOP))


def _draw_min_max_chips(
    target: pygame.Surface, rect: pygame.Rect, fonts: _ui.Fonts,
    t_min: float, t_max: float, unit_label: str,
) -> None:
    hi_text = f"hi {round(t_max)}{unit_label}"
    lo_text = f"lo {round(t_min)}{unit_label}"
    for text, pos in (
        (hi_text, (rect.x + 6, rect.y + 4)),
        (lo_text, (rect.right - fonts.tiny.size(lo_text)[0] - 6,
                   rect.y + _PLOT_BOT - fonts.tiny.get_height() - 4)),
    ):
        surf = fonts.tiny.render(text, True, _ui.COL_TEXT)
        chip = pygame.Surface((surf.get_width() + 6, surf.get_height() + 2), pygame.SRCALPHA)
        chip.fill((0, 0, 0, 160))
        target.blit(chip, (pos[0] - 3, pos[1] - 1))
        target.blit(surf, pos)


# ----- entry point ----------------------------------------------------------

def draw_day_diorama(
    screen: pygame.Surface,
    rect: pygame.Rect,
    today_hourly: list[dict],
    daily_today: dict | None,
    current: dict,
    assets: _ui.Assets,
    fonts: _ui.Fonts,
    units: dict,
    now_local: datetime,
) -> None:
    if not today_hourly:
        return

    # Sunrise/sunset hour fractions for today; default to 6a/6p if missing.
    sr = 6.0
    ss = 18.0
    if daily_today:
        try:
            sr = _hour_frac(daily_today["sunrise"])
            ss = _hour_frac(daily_today["sunset"])
        except (KeyError, ValueError, TypeError):
            pass

    # 1) Sky gradient background.
    sky = _sky_surface(rect.width, rect.height, sr, ss)
    screen.blit(sky, rect.topleft)

    # 2) Cloud haze overlay (plot region only — skip bottom axis band).
    haze_rect = pygame.Rect(rect.x, rect.y, rect.width, _PLOT_BOT)
    _draw_cloud_haze(screen, haze_rect, today_hourly)

    # 3) Precipitation columns from baseline.
    _draw_precip_columns(
        screen,
        pygame.Rect(rect.x, rect.y, rect.width, rect.height),
        today_hourly,
        baseline_y=rect.y + _PRECIP_BASE,
        max_h=_PRECIP_MAX_H,
    )

    # Temperature range for y-projection. Clamp ≥ 8° for flat-day legibility.
    temps = [float(p.get("temperature", 0) or 0) for p in today_hourly]
    app_temps = [float(p.get("apparent_temperature", 0) or 0) for p in today_hourly]
    pool = temps + app_temps
    t_min = min(pool) - 2
    t_max = max(pool) + 2
    if t_max - t_min < 8:
        mid = (t_min + t_max) / 2
        t_min, t_max = mid - 4, mid + 4

    # 4+5) Temperature gradient fill + polyline.
    _draw_temp_layer(screen, rect, today_hourly, t_min, t_max)

    # 6) Apparent-temperature dashed line.
    _draw_apparent_line(screen, rect, today_hourly, t_min, t_max)

    # 7) Sunrise/sunset markers.
    _draw_sun_markers(screen, rect, fonts, sr, ss)

    # 8) Icon callouts along the top.
    now_hf = now_local.hour + now_local.minute / 60.0
    _draw_icon_callouts(screen, rect, assets, today_hourly, now_hf)

    # 9) Now-cursor + chip.
    current_t = float(current.get("temperature", 0) or 0) if current else 0.0
    _draw_now_cursor(screen, rect, fonts, now_hf, current_t, units.get("temp", "\u00b0"))

    # 10) Hour axis + legend.
    _draw_hour_axis(screen, rect, fonts)
    _draw_legend(screen, rect, fonts)

    # 11) Min/max chips.
    _draw_min_max_chips(screen, rect, fonts,
                       min(temps), max(temps), units.get("temp", "\u00b0"))

    # Frame border — subtle, matches panel chrome.
    pygame.draw.rect(screen, _ui.COL_PANEL_BORDER, rect, width=1)
