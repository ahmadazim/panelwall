"""Open-Meteo forecast (free, keyless). Verified live 15 Sep 2026; fixtures/openmeteo.json is a capture.

  GET {base}/v1/forecast?latitude=..&longitude=..
      &current=temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m,wind_direction_10m,uv_index
      &hourly=temperature_2m,weather_code,precipitation_probability
      &daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,sunrise,sunset
      &temperature_unit=fahrenheit&wind_speed_unit=kn&timezone=America%2FNew_York&forecast_days=7
  -> {"current": {"time": "2026-09-15T00:15", "temperature_2m": 57.2, ...},
      "hourly": {"time": [...168 local ISO strings], "temperature_2m": [...], "weather_code": [...],
                 "precipitation_probability": [...]},
      "daily":  {"time": ["2026-09-15", ...], "weather_code": [...], "temperature_2m_max": [...],
                 "temperature_2m_min": [...], "precipitation_probability_max": [...], "sunrise": [...], "sunset": [...]}}

All times are LOCAL to the requested timezone and carry no offset - they are kept as
naive datetimes and compared with a naive local 'now'.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime

from ..config import CONFIG
from .polling import Backoff, DemandPoller, retry_after_seconds

# WMO weather_code -> (glyph name, word)
_WMO = [
    ((0, 0), ("sun", "CLEAR")),
    ((1, 2), ("partly", "PARTLY CLOUDY")),
    ((3, 3), ("cloud", "OVERCAST")),
    ((45, 48), ("fog", "FOG")),
    ((51, 57), ("rain", "DRIZZLE")),
    ((61, 67), ("rain", "RAIN")),
    ((71, 77), ("snow", "SNOW")),
    ((80, 82), ("rain", "SHOWERS")),
    ((85, 86), ("snow", "SNOW SHOWERS")),
    ((95, 99), ("storm", "THUNDERSTORM")),
]
COMPASS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")


def wmo(code: int | None) -> tuple[str, str]:
    if code is None:
        return "cloud", "UNKNOWN"
    for (lo, hi), val in _WMO:
        if lo <= code <= hi:
            return val
    return "cloud", "UNKNOWN"


def is_precip(code: int | None) -> bool:
    """Drizzle, rain, snow, showers, thunderstorm - anything worth interrupting for."""
    return code is not None and code >= 51


def compass(deg: float | None) -> str:
    if deg is None:
        return ""
    return COMPASS[int((deg % 360 + 22.5) // 45) % 8]


@dataclass
class Hour:
    time: datetime          # naive local
    temp: float | None
    code: int | None
    precip: int | None      # probability %


@dataclass
class Day:
    date: datetime          # naive local, midnight
    code: int | None
    hi: float | None
    lo: float | None
    precip: int | None
    sunrise: datetime | None
    sunset: datetime | None


@dataclass
class Forecast:
    time: datetime | None
    temp: float | None
    feels: float | None
    humidity: int | None
    code: int | None
    wind_kn: float | None
    wind_dir: float | None
    uv: float | None
    hourly: list[Hour] = field(default_factory=list)
    daily: list[Day] = field(default_factory=list)

    def hours_from(self, now: datetime, n: int = 12) -> list[Hour]:
        """The n hourly entries starting at the current hour (now truncated to the hour)."""
        start = now.replace(minute=0, second=0, microsecond=0)
        idx = next((i for i, h in enumerate(self.hourly) if h.time >= start), None)
        if idx is None:
            return []
        return self.hourly[idx: idx + n]

    def today(self) -> Day | None:
        return self.daily[0] if self.daily else None


def _dt(s) -> datetime | None:
    try:
        return datetime.fromisoformat(s) if s else None
    except (TypeError, ValueError):
        return None


def _num(v, cast=float):
    try:
        return cast(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def parse_forecast(doc: dict) -> Forecast:
    doc = doc or {}
    cur = doc.get("current") or {}
    fc = Forecast(time=_dt(cur.get("time")), temp=_num(cur.get("temperature_2m")), feels=_num(cur.get("apparent_temperature")),
                  humidity=_num(cur.get("relative_humidity_2m"), int), code=_num(cur.get("weather_code"), int),
                  wind_kn=_num(cur.get("wind_speed_10m")), wind_dir=_num(cur.get("wind_direction_10m")), uv=_num(cur.get("uv_index")))
    h = doc.get("hourly") or {}
    times = h.get("time") or []
    temps, codes, pp = h.get("temperature_2m") or [], h.get("weather_code") or [], h.get("precipitation_probability") or []
    for i, t in enumerate(times):
        dt = _dt(t)
        if dt is None:
            continue
        fc.hourly.append(Hour(dt, _num(temps[i]) if i < len(temps) else None, _num(codes[i], int) if i < len(codes) else None,
                              _num(pp[i], int) if i < len(pp) else None))
    d = doc.get("daily") or {}
    dtimes = d.get("time") or []

    def col(name, i, cast=float):
        arr = d.get(name) or []
        return _num(arr[i], cast) if i < len(arr) else None

    for i, t in enumerate(dtimes):
        dt = _dt(t)
        if dt is None:
            continue
        sr, ss = (d.get("sunrise") or [None] * len(dtimes)), (d.get("sunset") or [None] * len(dtimes))
        fc.daily.append(Day(dt, col("weather_code", i, int), col("temperature_2m_max", i), col("temperature_2m_min", i),
                            col("precipitation_probability_max", i, int), _dt(sr[i] if i < len(sr) else None), _dt(ss[i] if i < len(ss) else None)))
    return fc


class OpenMeteoClient:
    def __init__(self, base: str | None = None, timeout: float | None = None):
        self.base = (base or CONFIG.forecast.base).rstrip("/")
        self.timeout = timeout or CONFIG.data.http_timeout
        self.last_error: str | None = None
        self.backoff = Backoff()

    def url(self, lat: float, lon: float) -> str:
        q = {"latitude": f"{lat:.4f}", "longitude": f"{lon:.4f}",
             "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m,wind_direction_10m,uv_index",
             "hourly": "temperature_2m,weather_code,precipitation_probability",
             "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,sunrise,sunset",
             "temperature_unit": "fahrenheit", "wind_speed_unit": "kn", "timezone": CONFIG.forecast.timezone, "forecast_days": "7"}
        return f"{self.base}/v1/forecast?" + urllib.parse.urlencode(q)

    def fetch(self, lat: float, lon: float) -> dict | None:
        req = urllib.request.Request(self.url(lat, lon), headers={"User-Agent": "panelwall/0.1", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                doc = json.loads(r.read().decode("utf-8", "replace"))
            self.last_error = None
            self.backoff.reset()
            return doc
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = self.backoff.note(retry_after_seconds(e.headers))
                self.last_error = f"HTTP 429 rate limited by Open-Meteo; retrying in {int(wait)} s"
            else:
                self.last_error = f"HTTP {e.code} open-meteo"
        except Exception as e:
            self.last_error = f"{type(e).__name__}: {e}"
        return None


class ForecastFeed(DemandPoller):
    """Polls every CONFIG.forecast.poll_seconds. `forecast` is replaced whole on success.
    `alert_until` is set 60 s ahead when the current weather_code changes INTO precipitation."""

    ALERT_SECONDS = 60.0

    def __init__(self, client: OpenMeteoClient | None = None, static: dict | None = None):
        self.client = client or OpenMeteoClient()
        self.forecast: Forecast | None = None
        self.updated_at = 0.0
        self.alert_until = 0.0
        self._last_code: int | None = None
        self._fixed_now: datetime | None = None
        self._init_demand()
        self._thread = None
        if static is not None:
            self._fixed_now = _dt(static.get("_now"))
            self._ingest(static)
            self.updated_at = time.time()
        else:
            self._thread = threading.Thread(target=self._poll_loop, daemon=True, name="meteo-poll")
            self._thread.start()

    def now(self) -> datetime:
        """Naive local time, comparable with Open-Meteo's local timestamps."""
        return self._fixed_now or datetime.now()

    @property
    def last_error(self) -> str | None:
        return self.client.last_error

    def _ingest(self, doc: dict) -> None:
        fc = parse_forecast(doc)
        if fc.time is None and not fc.hourly and not fc.daily:
            return
        if self._last_code is not None and fc.code != self._last_code and is_precip(fc.code):
            self.alert_until = time.time() + self.ALERT_SECONDS
        self._last_code = fc.code
        self.forecast = fc

    def _poll_loop(self):
        self._wait_wanted()
        while not self._stop.is_set():
            loc = CONFIG.location
            doc = self.client.fetch(loc.lat, loc.lon)
            if doc is not None:
                self._ingest(doc)
                self.updated_at = time.time()
            self._sleep_or_pause(max(CONFIG.forecast.poll_seconds, self.client.backoff.remaining()))

    def status(self) -> dict:
        fc = self.forecast
        return {"updated_at": self.updated_at or None, "last_error": self.last_error, "paused": self.paused,
                "temp": fc.temp if fc else None, "code": fc.code if fc else None, "alert": time.time() < self.alert_until}

    def close(self):
        self._stop.set()
