from GoogleMercatorProjection import LatLng
from PyQt4.QtGui import QColor

wuprefix = 'http://api.wunderground.com/api/'
wulocation = LatLng(42.5911248,-71.5692887)
noaastream = 'http://audioplayer.wunderground.com/CW5897/Auburn.mp3'
# background = 'images/clockbackground-kevin.png'
background = 'images/BaxterDark.jpg'
squares1 = 'images/squares1.png'
squares2 = 'images/squares2.png'
icons = 'icons-lightblue'
textcolor = '#bef'
clockface = 'images/clockface3.png'
hourhand = 'images/hourhand.png'
minhand = 'images/minhand.png'
sechand = 'images/sechand.png'

metric = 0  #0 = English, 1 = Metric
radar_refresh = 10      # minutes
weather_refresh = 30    # minutes
wind_degrees = 0        # Wind in degrees instead of cardinal 0 = cardinal, 1 = degrees
satellite = 0           # Depreciated: use 'satellite' key in radar section, on a per radar basis
                        # if this is used, all radar blocks will get satellite images
METAR = 'KFIT'
# METAR = 'KASH'
# METAR = ''
                        
fontattr = ''   # gives all text additional attributes using QT style notation
                # example: fontattr = 'font-weight: bold; '
                
dimcolor = QColor('#000000')    # These are to dim the radar images, if needed.
dimcolor.setAlpha(0)            # see and try Config-Example-Bedside.py

# Language Specific wording
wuLanguage = "EN"   # Weather Undeground Language code (https://www.wunderground.com/weather/api/d/docs?d=language-support&MR=1)
DateLocale = ''  # The Python Locale for date/time (locale.setlocale) -- '' for default Pi Setting
                            # Locales must be installed in your Pi.. to check what is installed
                            # locale -a
                            # to install locales
                            # sudo dpkg-reconfigure locales
LPressure = "Pressure "
LHumidity = "Humidity "
LWind = "Wind "
Lgusting = " gusting "
LFeelslike = "Feels like "
LPrecip1hr = " Precip 1hr:"
LToday = "Today: "
LSunRise = "Sun Rise:"
LSet = " Set: "
LMoonPhase = " Moon Phase:"
LInsideTemp = "Inside Temp "
LRain = " Rain: "
LSnow = " Snow: "

radar1 = {
    'center' : LatLng(42.5911248,-71.5692887),  # the center of your radar block
    'zoom' : 6, # this is a google maps zoom factor, bigger = smaller area
    'satellite' : 0,    # 1 => show satellite images instead of radar (colorized IR images)
    'markers' : (   # google maps markers can be overlayed
        {
        'location' : LatLng(42.5911248,-71.5692887),
        'color' : 'red',
        'size' : 'small',
        },          # dangling comma is on purpose.
        )
    }

    
radar2 = {
    'center' : LatLng(42.5911248,-71.5692887),
    'zoom' : 10,
    'satellite' : 0,
    'markers' : (
        {
        'location' : LatLng(42.5911248,-71.5692887),
        'color' : 'red',
        'size' : 'small',
        },
        )
    }

    
radar3 = {
    'center' : LatLng(42.5911248,-71.5692887),
    'zoom' : 6,
    'satellite' : 0,
    'markers' : (
        {
        'location' : LatLng(42.5911248,-71.5692887),
        'color' : 'red',
        'size' : 'small',
        },
        )
    }

radar4 = {
    'center' : LatLng(42.5911248,-71.5692887),
    'zoom' : 11,
    'satellite' : 0,
    'markers' : (
        {
        'location' : LatLng(42.5911248,-71.5692887),
        'color' : 'red',
        'size' : 'small',
        },
        )
    }
