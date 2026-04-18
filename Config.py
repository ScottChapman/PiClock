# PiClock configuration — plain Python, no Qt / Google deps.
# Edit this file to adjust your PiClock display.
# Loaded at startup by backend/config.py.

# --- Location ---
location = (42.5911248, -71.5692887)   # (latitude, longitude) for weather queries

# --- Units & refresh ---
metric = False              # False = imperial (°F, mph), True = metric (°C, km/h)
radar_refresh = 10          # minutes between radar updates
weather_refresh = 30        # minutes between weather updates
wind_degrees = False        # False = cardinal (N/NE/…), True = numeric degrees

# --- Display / theme ---
background = 'BaxterDark.jpg'   # background image filename at repo root; served via /static/bg/
icons = 'icons-lightblue'       # icon set: icons-lightblue | icons-darkblue | icons-darkgreen
textcolor = '#bef'              # CSS color for primary text

# --- Clock ---
digital = False             # False = analog, True = digital
digitalformat = '%H:%M:%S'  # strftime format when digital=True
clockUTC = False            # True = display UTC, False = local time

# --- METAR (optional) — leave '' to disable ---
METAR = 'KFIT'

# --- Language labels ---
DateLocale = ''             # Python locale for date/time; '' = system default
LPressure = 'Pressure '
LHumidity = 'Humidity '
LWind = 'Wind '
Lgusting = ' gusting '
LFeelslike = 'Feels like '
LPrecip1hr = ' Precip 1hr:'
LToday = 'Today: '
LSunRise = 'Sun Rise:'
LSet = ' Set: '
LMoonPhase = ' Moon Phase:'
LRain = ' Rain: '
LSnow = ' Snow: '

# --- Radar maps (2 panels in the web layout) ---
# Each is a dict; markers is optional list of {location, color, size}.

radar1 = {
    'center': (42.5911248, -71.5692887),
    'zoom': 7,
    'satellite': True,
    'markers': [
        {'location': (42.5911248, -71.5692887), 'color': 'red', 'size': 'small'},
    ],
}

radar2 = {
    'center': (42.5911248, -71.5692887),
    'zoom': 10,
    'satellite': True,
    'markers': [
        {'location': (42.5911248, -71.5692887), 'color': 'red', 'size': 'small'},
    ],
}
