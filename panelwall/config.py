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
    lat: float = _env("PW_LAT", 40.38902863041299)
    lon: float = _env("PW_LON", -75.12736827681987)
    radius_nm: float = _env("PW_RADIUS_NM", 50.0)   # look this far around you
    home_airport: str = "BOS"


@dataclass
class ColorlightConfig:
    iface: str = _env("PW_IFACE", "eth0")


@dataclass
class DataConfig:
    adsb_base: str = _env("PW_ADSB_BASE", "https://api.adsb.lol")
    poll_seconds: float = 5.0            # how often to re-query aircraft positions
    route_cache_seconds: float = 3600.0  # origin/destination rarely changes mid-flight
    http_timeout: float = 6.0


@dataclass
class Config:
    display: DisplayConfig = field(default_factory=DisplayConfig)
    location: LocationConfig = field(default_factory=LocationConfig)
    colorlight: ColorlightConfig = field(default_factory=ColorlightConfig)
    data: DataConfig = field(default_factory=DataConfig)


CONFIG = Config()
