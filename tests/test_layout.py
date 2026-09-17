"""compute_layout must keep every panel inside the screen.

The right-hand column used to overhang by one pad at every resolution:
the layout reserved two horizontal pads when it needs four (left margin,
two inter-column gaps, right margin).
"""

import pygame
import pytest

from display import ui

SIZES = [(1920, 1080), (1280, 720), (1024, 600), (800, 480), (480, 320)]


@pytest.fixture(autouse=True)
def _pygame():
    pygame.init()
    yield
    pygame.quit()


@pytest.mark.parametrize("size", SIZES)
def test_panels_stay_within_the_screen(size):
    layout = ui.compute_layout(size)
    screen = pygame.Rect(0, 0, *size)
    for name in ("weather", "radar1", "radar2", "clock", "datestrip", "forecast"):
        rect = getattr(layout, name)
        assert screen.contains(rect), f"{name} {rect} escapes the {size} screen"


@pytest.mark.parametrize("size", SIZES)
def test_margins_are_symmetric(size):
    layout = ui.compute_layout(size)
    pad = max(6, size[0] // 200)
    assert layout.weather.x == pad
    assert size[0] - layout.forecast.right == pad
    assert layout.weather.y == pad
    assert size[1] - layout.forecast.bottom == pad


@pytest.mark.parametrize("size", SIZES)
def test_columns_do_not_overlap(size):
    layout = ui.compute_layout(size)
    assert layout.weather.right <= layout.clock.left
    assert layout.datestrip.right <= layout.forecast.left
