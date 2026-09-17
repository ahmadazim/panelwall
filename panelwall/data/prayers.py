"""Prayer (athan) and iqama times from a fiveprayers.org display page.

There is no API. The page (https://fiveprayers.org/display/index.php?id=<mosque>) is
server-rendered with PLACEHOLDER athan times; its JavaScript (ptScript_calcs.js, verified
17 Sep 2026) then computes the real times in the browser from two hidden strings:

  #parms  "lat,lon,elev,fajrAng,ishaAng,ishaMinutes,asrFactor,CLCLT,serverDay"
  #fat    "CLCLT;dremain;ciq"     ciq = 6 comma-separated iqama offsets (min) for
                                   fajr,dhuhr,asr,maghrib,isha,jumuah; 0 = use the FIXED time
                                   that PHP wrote into the table (td#fajIq, #dhuIq, ... #fdp)

CLCLT=1 (this account) means "calculate on the client" - we port that calculation exactly,
including its rounding (Fajr/Sunrise floor, the rest ceil). CLCLT=0 means the server
supplied future athan rows in #fat; we parse those too but it is UNVERIFIED (no such page
to test against).

The page is fetched every few hours (config, iqama rules, Jumu'ah time rarely change); the
times themselves are recomputed locally each day.
"""

from __future__ import annotations

import math
import re
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from html import unescape
from zoneinfo import ZoneInfo

from ..config import CONFIG
from .polling import Backoff, DemandPoller, retry_after_seconds

NAMES = ("Fajr", "Sunrise", "Dhuhr", "Asr", "Maghrib", "Isha")      # index order used by the page
IQAMA_NAMES = ("Fajr", "Dhuhr", "Asr", "Maghrib", "Isha")
_ATH_IDS = ("fajAth", "sunAth", "dhuAth", "asrAth", "magAth", "ishAth")
_IQ_IDS = ("fajIq", "dhuIq", "asrIq", "magIq", "ishIq")


@dataclass
class PageConfig:
    lat: float
    lon: float
    elev: float
    fajr_angle: float
    isha_angle: float
    isha_minutes: float          # > 0: Isha = Maghrib + minutes (instead of an angle)
    asr_factor: float            # 1 = standard (Shafi), 2 = Hanafi
    clclt: int                   # 1 = compute on the client
    server_day: int
    iqama_offsets: list          # 6 ints: fajr,dhuhr,asr,maghrib,isha,jumuah
    fixed_iqama: dict            # prayer name -> (h24, m) from the HTML table, used when offset == 0
    jumuah: tuple | None         # (h24, m) fixed Jumu'ah time from td#fdp
    title: str = ""              # #logoBox (mosque / display name)
    location: str = ""           # #dateBox
    method: str = ""             # infoTable first cell, e.g. 'isna'
    server_rows: list = field(default_factory=list)   # CLCLT=0 only: future athan rows (unverified)


@dataclass
class PrayerDay:
    day: date
    athan: dict                  # name -> datetime (tz-aware)
    iqama: dict                  # name -> datetime
    jumuah: datetime | None


# ---- HTML parsing ------------------------------------------------------------------------------
def _text_of_id(html: str, el_id: str) -> str:
    m = re.search(rf"<[a-z]+[^>]*\bid\s*=\s*['\"]{re.escape(el_id)}['\"][^>]*>(.*?)</", html, re.S | re.I)
    if not m:
        return ""
    return unescape(re.sub(r"<[^>]+>", " ", m.group(1))).strip()


def parse_clock(text: str) -> tuple[int, int] | None:
    """'5:05 PM' / '12:30  PM' / '05:05PM' -> (17, 5). None if it isn't a time."""
    m = re.search(r"(\d{1,2})\s*:\s*(\d{2})\s*(AM|PM)?", text, re.I)
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    ap = (m.group(3) or "").upper()
    if ap == "PM" and h < 12:
        h += 12
    if ap == "AM" and h == 12:
        h = 0
    return h % 24, mi


def parse_page(html: str) -> PageConfig:
    html = re.sub(r"<!--.*?-->", "", html, flags=re.S)      # the page has a commented-out <div id="fat">
    parms = [p.strip() for p in _text_of_id(html, "parms").split(",")]
    if len(parms) < 8:
        raise ValueError("page has no #parms - not a fiveprayers display page?")
    num = lambda i, d=0.0: float(parms[i]) if i < len(parms) and parms[i] not in ("", "NaN") else d  # noqa: E731
    fat = [seg.strip() for seg in _text_of_id(html, "fat").split(";")]
    clclt = int(float(fat[0])) if fat and fat[0] else int(num(7, 1))
    dremain = int(float(fat[1])) if len(fat) > 1 and fat[1] else 0
    offsets, rows = [0] * 6, []
    if clclt == 1:
        if len(fat) > 2:
            offsets = [int(float(x)) if x.strip() else 0 for x in fat[2].split(",")][:6]
    else:
        for seg in fat[2: 2 + dremain + 2]:
            cells = seg.split(",")
            if len(cells) >= 7:
                rows.append(cells[1:7])
        if len(fat) > dremain + 4:
            offsets = [int(float(x)) if x.strip() else 0 for x in fat[dremain + 4].split(",")][:6]
    offsets += [0] * (6 - len(offsets))
    fixed = {}
    for name, el in zip(IQAMA_NAMES, _IQ_IDS):
        t = parse_clock(_text_of_id(html, el))
        if t:
            fixed[name] = t
    info = re.search(r'class="infoData".*?<td>(.*?)</td>', html, re.S)
    return PageConfig(
        lat=num(0), lon=num(1), elev=num(2), fajr_angle=num(3), isha_angle=num(4), isha_minutes=num(5),
        asr_factor=num(6, 1.0), clclt=clclt, server_day=int(num(8, 0)),
        iqama_offsets=offsets, fixed_iqama=fixed, jumuah=parse_clock(_text_of_id(html, "fdp")),
        title=_text_of_id(html, "logoBox"), location=_text_of_id(html, "dateBox"),
        method=(unescape(info.group(1)).strip() if info else ""), server_rows=rows)


# ---- the astronomy, ported line for line from ptScript_calcs.js ------------------------------
def _fix(a: float, b: float) -> float:
    a = a - b * math.floor(a / b)
    return a + b if a < 0 else a


def _sin(x): return math.sin(math.radians(x))
def _cos(x): return math.cos(math.radians(x))
def _tan(x): return math.tan(math.radians(x))
def _asin(x): return math.degrees(math.asin(x))
def _acos(x): return math.degrees(math.acos(max(-1.0, min(1.0, x))))
def _atan2(y, x): return math.degrees(math.atan2(y, x))
def _acot(x): return math.degrees(math.atan(1 / x))


def julian_day(year: int, month: int, day: int) -> float:
    if month <= 2:
        year -= 1
        month += 12
    a = math.floor(year / 100)
    b = 2 - a + math.floor(a / 4)
    return math.floor(365.25 * (year + 4716)) + math.floor(30.6001 * (month + 1)) + day + b - 1524.5


def _sun(jd: float) -> tuple[float, float]:
    """(equation of time in hours, declination in degrees)."""
    d = jd - 2451545.0
    g = _fix(357.529 + 0.98560028 * d, 360)
    q = _fix(280.459 + 0.98564736 * d, 360)
    lam = _fix(q + 1.915 * _sin(g) + 0.020 * _sin(2 * g), 360)
    e = 23.439 - 0.00000036 * d
    ra = _atan2(_cos(e) * _sin(lam), _cos(lam)) / 15
    decl = _asin(_sin(e) * _sin(lam))
    eqt = q / 15 - _fix(ra, 24)
    return eqt, decl


def compute_athan_hours(cfg: PageConfig, day: date, tz_hours: float) -> list[float]:
    """Decimal local hours for Fajr, Sunrise, Dhuhr, Asr, Maghrib, Isha - the JS `times` array
    after its three refinement passes, before rounding."""
    jd = julian_day(day.year, day.month, day.day)
    lat, lon = cfg.lat, cfg.lon

    def zenith(t):
        return _fix(12 - _sun(jd + t / 24)[0], 24)

    def talpha(angle, decl):
        return _acos((-_sin(angle) - _sin(decl) * _sin(lat)) / (_cos(decl) * _cos(lat))) / 15

    def at_angle(t, angle, up=False):
        ta = talpha(angle, _sun(jd + t / 24)[1])
        return zenith(t) + (-ta if up else ta)

    def asr(t):
        decl = _sun(jd + t / 24)[1]
        angle = -_acot(cfg.asr_factor + _tan(abs(lat - decl)))
        return at_angle(t, angle)

    times = [5.0, 7.0, 12.0, 15.0, 17.0, 19.0]
    shift = tz_hours - lon / 15
    for _ in range(3):
        times[2] = zenith(times[2]) + shift
        angle = 0.833 + 0.0347 * math.sqrt(max(cfg.elev, 0.0))
        times[1] = at_angle(times[1], angle, up=True) + shift
        times[4] = at_angle(times[4], angle) + shift
        times[0] = at_angle(times[0], cfg.fajr_angle, up=True) + shift
        if cfg.isha_angle > 0:
            times[5] = at_angle(times[5], cfg.isha_angle) + shift
        if cfg.isha_minutes > 0:
            times[5] = times[4] + cfg.isha_minutes / 60
        times[3] = asr(times[3]) + shift
    return times


def board_time(t: float, rnd: str) -> tuple[int, int]:
    """Decimal hours -> (h24, m) with the page's rounding ('floor' | 'ceil' | 'round')."""
    hrs = math.floor(t)
    frac = (t - hrs) * 60
    mins = {"ceil": math.ceil, "floor": math.floor}.get(rnd, round)(frac)
    if mins == 60:
        mins, hrs = 0, hrs + 1
    return int(hrs) % 24, int(mins)


_ROUNDING = ("floor", "floor", "ceil", "ceil", "ceil", "ceil")


def athan_for(cfg: PageConfig, day: date, tz: ZoneInfo) -> dict:
    """name -> (h24, m) for the six athan-table rows of `day`."""
    if cfg.clclt == 1 or not cfg.server_rows:
        off = datetime(day.year, day.month, day.day, 12, tzinfo=tz).utcoffset()
        hours = compute_athan_hours(cfg, day, off.total_seconds() / 3600 if off else 0.0)
        return {n: board_time(h, r) for n, h, r in zip(NAMES, hours, _ROUNDING)}
    row = cfg.server_rows[0]                           # UNVERIFIED path (CLCLT=0)
    return {n: (parse_clock(c) or (0, 0)) for n, c in zip(NAMES, row)}


def day_times(cfg: PageConfig, day: date, tz: ZoneInfo) -> PrayerDay:
    ath = athan_for(cfg, day, tz)
    mk = lambda hm: datetime(day.year, day.month, day.day, hm[0], hm[1], tzinfo=tz)  # noqa: E731
    athan = {n: mk(hm) for n, hm in ath.items()}
    iqama = {}
    for j, name in enumerate(IQAMA_NAMES):
        offset = cfg.iqama_offsets[j] if j < len(cfg.iqama_offsets) else 0
        if offset > 0:
            iqama[name] = athan[name] + timedelta(minutes=offset)
        elif name in cfg.fixed_iqama:
            iqama[name] = mk(cfg.fixed_iqama[name])
    jum = None
    joff = cfg.iqama_offsets[5] if len(cfg.iqama_offsets) > 5 else 0
    if joff != 0:
        jum = athan["Dhuhr"] + timedelta(minutes=joff)
    elif cfg.jumuah:
        jum = mk(cfg.jumuah)
    return PrayerDay(day=day, athan=athan, iqama=iqama, jumuah=jum)


def next_event(today: PrayerDay, tomorrow: PrayerDay, now: datetime) -> tuple[str, str, datetime]:
    """(prayer name, 'ATHAN' | 'IQAMA' | 'JUMUAH', when) - the page's 'Remaining to' logic:
    the soonest upcoming athan or iqama; on Friday, Jumu'ah stands in for Dhuhr."""
    cands = []
    for d in (today, tomorrow):
        friday = d.day.weekday() == 4
        for name, t in d.athan.items():
            if name == "Sunrise":
                continue
            if friday and name == "Dhuhr" and d.jumuah:
                continue
            cands.append((t, name, "ATHAN"))
        for name, t in d.iqama.items():
            if friday and name == "Dhuhr" and d.jumuah:
                continue
            cands.append((t, name, "IQAMA"))
        if friday and d.jumuah:
            cands.append((d.jumuah, "Jumu'ah", "JUMUAH"))
    future = sorted(c for c in cands if c[0] > now)
    if not future:
        return "Fajr", "ATHAN", tomorrow.athan["Fajr"]
    t, name, kind = future[0]
    return name, kind, t


# ---- client + feed -------------------------------------------------------------------------------
class PrayersClient:
    def __init__(self, url: str | None = None, timeout: float | None = None):
        self.url = url or CONFIG.prayers.url
        self.timeout = timeout or CONFIG.data.http_timeout
        self.last_error: str | None = None
        self.backoff = Backoff()

    def fetch_html(self) -> str | None:
        req = urllib.request.Request(self.url, headers={"User-Agent": "panelwall/0.1", "Accept": "text/html"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                html = r.read().decode("utf-8", "replace")
            self.last_error = None
            self.backoff.reset()
            return html
        except urllib.error.HTTPError as e:
            if e.code in (429, 503):
                wait = self.backoff.note(retry_after_seconds(e.headers))
                self.last_error = f"HTTP {e.code} from fiveprayers.org; retrying in {int(wait)} s"
            else:
                self.last_error = f"HTTP {e.code} fiveprayers.org"
        except Exception as e:
            self.last_error = f"{type(e).__name__}: {e}"
        return None


class PrayersFeed(DemandPoller):
    """Fetches the page every CONFIG.prayers.poll_seconds; `config` is the parsed PageConfig.
    Times are computed on demand per day (cheap) and cached by date."""

    def __init__(self, client: PrayersClient | None = None, static_html: str | None = None, now: datetime | None = None):
        self.client = client or PrayersClient()
        self.tz = ZoneInfo(CONFIG.prayers.timezone)
        self.config: PageConfig | None = None
        self.updated_at = 0.0
        self.parse_error: str | None = None
        self._fixed_now = now
        self._cache: dict[date, PrayerDay] = {}
        self._init_demand()
        self._thread = None
        if static_html is not None:
            self._ingest(static_html)
            self.updated_at = time.time()
        else:
            self._thread = threading.Thread(target=self._poll_loop, daemon=True, name="prayers-poll")
            self._thread.start()

    @property
    def last_error(self) -> str | None:
        return self.client.last_error or self.parse_error

    def now(self) -> datetime:
        return self._fixed_now or datetime.now(self.tz)

    def _ingest(self, html: str) -> None:
        try:
            self.config = parse_page(html)
            self.parse_error = None
            self._cache.clear()
        except Exception as e:
            self.parse_error = f"page parse: {type(e).__name__}: {e}"

    def _poll_loop(self):
        self._startup_grace()
        self._wait_wanted()
        while not self._stop.is_set():
            html = self.client.fetch_html()
            if html is not None:
                self._ingest(html)
                self.updated_at = time.time()
            self._sleep_or_pause(max(CONFIG.prayers.poll_seconds, self.client.backoff.remaining()))

    def times_for(self, day: date) -> PrayerDay | None:
        if self.config is None:
            return None
        if day not in self._cache:
            if len(self._cache) > 8:
                self._cache.clear()
            self._cache[day] = day_times(self.config, day, self.tz)
        return self._cache[day]

    def today(self) -> PrayerDay | None:
        return self.times_for(self.now().date())

    def upcoming(self) -> tuple[str, str, datetime] | None:
        now = self.now()
        t, tm = self.times_for(now.date()), self.times_for(now.date() + timedelta(days=1))
        return next_event(t, tm, now) if t and tm else None

    def status(self) -> dict:
        return {"updated_at": self.updated_at or None, "last_error": self.last_error, "paused": self.paused,
                "title": self.config.title if self.config else None, "method": self.config.method if self.config else None}

    def close(self):
        self._stop.set()
