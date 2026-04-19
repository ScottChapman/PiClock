from pathlib import Path

from backend import config


def test_loads_real_config():
    s = config.load()
    assert len(s.location) == 2
    assert isinstance(s.location[0], float)
    assert s.icons in ("icons-lightblue", "icons-darkblue", "icons-darkgreen")
    assert s.weather_refresh_minutes > 0
    assert s.radar_refresh_minutes > 0
    assert len(s.radars) == 2
    assert s.radars[0].zoom > 0
    assert all(len(m.location) == 2 for r in s.radars for m in r.markers)


def test_labels_have_defaults():
    s = config.load()
    assert s.labels.feelslike
    assert s.labels.humidity
    assert s.labels.wind


def test_loads_from_custom_path(tmp_path: Path):
    p = tmp_path / "Config.py"
    p.write_text(
        "location = (10.0, 20.0)\n"
        "metric = True\n"
        "radar_refresh = 5\n"
        "weather_refresh = 15\n"
        "background = 'foo.jpg'\n"
        "icons = 'icons-darkblue'\n"
        "radar1 = {'center': (10.0, 20.0), 'zoom': 7}\n"
    )
    s = config.load(p)
    assert s.location == (10.0, 20.0)
    assert s.metric is True
    assert s.radar_refresh_minutes == 5
    assert s.icons == "icons-darkblue"
    assert len(s.radars) == 1
