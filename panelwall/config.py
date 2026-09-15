"""Central configuration. Edit this file (or override via environment variables)."""

import os
from dataclasses import dataclass, field


def _env(name: str, default):
    v = os.environ.get(name)
    if v is None:
        return default
    return type(default)(v)


@dataclass
class DisplayConfig:
    width: int = 256          # 4 panels x 64 px
    height: int = 64          # 2 panels x 32 px
    fps: float = 20.0         # LEDVision's default is 20 Hz; the card is happy up to ~60
    brightness: int = 0xBF    # 0..255, written into the 0x0107 display frame


@dataclass
class LocationConfig:
    # Where the display physically is. Used for "what's overhead" queries.
    # Default: downtown Boston. Replace with your apartment's coordinates.
    lat: float = _env("PW_LAT", 40.7128)
    lon: float = _env("PW_LON", -74.0060)
    radius_nm: float = _env("PW_RADIUS_NM", 250.0)   # look this far around you
    home_airport: str = "BOS"


@dataclass
class ColorlightConfig:
    iface: str = _env("PW_IFACE", "eth0")


@dataclass
class DataConfig:
    adsb_base: str = _env("PW_ADSB_BASE", "https://api.adsb.lol")
    poll_seconds: float = _env("PW_POLL_SECONDS", 15.0)   # adsb.lol 429s when polled harder; feeds pause when their panel is off screen
    routes_base: str = _env("PW_ROUTES_BASE", "https://api.adsbdb.com")   # "" disables route lookups
    route_lookups_per_poll: int = 2      # be polite to adsbdb: a busy sky fills in over a few polls
    route_cache_seconds: float = 3600.0  # origin/destination rarely changes mid-flight
    http_timeout: float = 6.0


@dataclass
class MbtaConfig:
    # MBTA V3 API. Works with no key (20 req/min, we use 8); a free key raises the limit.
    base: str = _env("PW_MBTA_BASE", "https://api-v3.mbta.com")
    api_key: str = _env("MBTA_API_KEY", "")
    route: str = _env("PW_MBTA_ROUTE", "Red")
    home_stop: str = _env("PW_MBTA_STOP", "place-harsq")     # Harvard
    branch: str = _env("PW_MBTA_BRANCH", "Braintree")        # Red Line forks after JFK/UMass
    direction_names: tuple[str, str] = ("ASHMONT/BRAINTREE", "ALEWIFE")   # direction_id 0, 1
    poll_seconds: float = _env("PW_MBTA_POLL", 30.0)      # 2 requests per poll -> 4/min, well under the keyless 20/min


def _teams(default):
    """PW_TEAMS='mlb:BOS:SOX,nfl:NE:PATS' -> [(league, abbreviation, label), ...]"""
    v = os.environ.get("PW_TEAMS")
    if not v:
        return default
    out = []
    for item in v.split(","):
        parts = item.strip().split(":")
        if len(parts) >= 2:
            out.append((parts[0].lower(), parts[1].upper(), (parts[2] if len(parts) > 2 else parts[1]).upper()))
    return out or default


@dataclass
class SportsConfig:
    # ESPN's public scoreboard JSON (undocumented, keyless, long-stable). Tracked teams:
    # (league, ESPN abbreviation, <=6-char label for the display). Any city works.
    base: str = _env("PW_ESPN_BASE", "https://site.api.espn.com/apis/site/v2/sports")
    city: str = _env("PW_CITY", "BOSTON")
    teams: list = field(default_factory=lambda: _teams([
        ("mlb", "BOS", "SOX"), ("nfl", "NE", "PATS"), ("nba", "BOS", "CELTS"), ("nhl", "BOS", "B'S")]))
    poll_live_seconds: float = 60.0      # while a tracked game is in progress (one request per league)
    poll_idle_seconds: float = 600.0
    days_ahead: int = 7                  # scoreboard window: yesterday .. today+days_ahead


@dataclass
class ForecastConfig:
    base: str = _env("PW_METEO_BASE", "https://api.open-meteo.com")
    timezone: str = _env("PW_TZ", "America/New_York")
    poll_seconds: float = 1800.0         # forecasts don't change faster than this
    view_seconds: float = 20.0           # WEEK <-> HOURLY alternation


@dataclass
class FlightWallConfig:
    """The FlightWall Widescreen replica card (channels/flightwall.py)."""
    title: str = _env("PW_FW_TITLE", "airline")           # airline | flight   (row 1: 'Southwest Airlines' or 'WN 1187')
    cycle_seconds: float = _env("PW_FW_CYCLE", 5.0)       # FlightWall app: 5 / 3 / 2 s per flight
    units: str = _env("PW_FW_UNITS", "imperial")          # imperial (ft, kts, ft/m) | metric (m/km, kph, kph)
    max_flights: int = 5                                  # cycle the nearest N; '+M more' beyond that
    no_flights: str = _env("PW_FW_IDLE", "dots")          # dots | clock
    clocks: list = field(default_factory=lambda: [("EST", "America/New_York")])   # up to 3 (label, IANA tz)
    hour24: bool = True
    show_seconds: bool = True
    home_airport: str = _env("PW_HOME", "BOS")


@dataclass
class Config:
    display: DisplayConfig = field(default_factory=DisplayConfig)
    location: LocationConfig = field(default_factory=LocationConfig)
    colorlight: ColorlightConfig = field(default_factory=ColorlightConfig)
    data: DataConfig = field(default_factory=DataConfig)
    mbta: MbtaConfig = field(default_factory=MbtaConfig)
    sports: SportsConfig = field(default_factory=SportsConfig)
    forecast: ForecastConfig = field(default_factory=ForecastConfig)
    flightwall: FlightWallConfig = field(default_factory=FlightWallConfig)


CONFIG = Config()
