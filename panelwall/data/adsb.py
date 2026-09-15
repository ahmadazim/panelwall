"""Live aircraft near a point, from adsb.lol (free, no key) or any readsb-style API.

Endpoints (adsb.lol; airplanes.live has the same /v2/point shape):
  GET  {base}/v2/point/{lat}/{lon}/{radius_nm}      -> {"ac": [...], "now": ..., ...}
  GET  {routes_base}/v0/callsign/{callsign}         -> adsbdb: {"response": {"flightroute": {origin: {iata_code,
                                                       latitude, longitude}, destination: {...}}}}; 404 = unknown

adsb.lol's own POST /api/0/routeset was verified DEAD on 15 Sep 2026 (HTTP 201, empty
body, even for airline callsigns) - routes now come from api.adsbdb.com, which was
verified live the same night. `parse_route` (routeset shape) is kept for reference.

Rate limits: adsb.lol's are "dynamic based on load" and it answers 429 when unhappy.
AdsbClient honours Retry-After and otherwise backs off 15 s -> 5 min; the feed waits.

Per-aircraft fields we use (readsb naming):
  hex, flight (callsign), r (registration), t (type designator), desc,
  alt_baro (ft or "ground"), gs (knots), track (deg), baro_rate (ft/min),
  lat, lon, seen (s since last msg)

Everything network-facing is wrapped so a dead API yields an empty list,
never an exception in the render loop. Run `python -m panelwall probe` on
the Pi to see the raw JSON and confirm the shapes.
"""

from __future__ import annotations

import json
import math
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from ..config import CONFIG
from .airlines import parse_callsign, short_flight
from .aircraft_types import type_name


@dataclass
class Aircraft:
    hex: str
    callsign: str
    registration: str
    type_code: str
    altitude: int | None       # feet; None if unknown; 0 if on ground
    on_ground: bool
    speed: int | None          # knots
    track: int | None          # degrees
    vrate: int | None          # ft/min, + climbing
    lat: float | None
    lon: float | None
    distance_nm: float | None  # from the display location
    origin: str = ""           # IATA, e.g. "BOS"
    destination: str = ""
    extra: dict = field(default_factory=dict)

    # ---- display helpers -----------------------------------------------
    @property
    def flight(self) -> str:
        return short_flight(self.callsign) or self.registration or self.hex.upper()

    @property
    def airline(self) -> str:
        return parse_callsign(self.callsign)[1]

    @property
    def type_name(self) -> str:
        return type_name(self.type_code)

    @property
    def route(self) -> str:
        if self.origin and self.destination:
            return f"{self.origin}>{self.destination}"
        return ""

    @property
    def phase(self) -> str:
        if self.on_ground:
            return "GROUND"
        if self.vrate is None:
            return "LEVEL"
        if self.vrate > 300:
            return "CLIMBING"
        if self.vrate < -300:
            return "DESCENDING"
        return "LEVEL"


def _haversine_nm(lat1, lon1, lat2, lon2) -> float:
    r = 3440.065
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


class ApiError(Exception):
    """HTTP error with the response body attached, so probe can show what the server said."""

    def __init__(self, status: int, body: str, retry_after: float | None = None):
        short = " ".join(body.split())[:120]          # nginx's 429 page is mostly whitespace/HTML
        super().__init__(f"HTTP {status}" + (f": {short!r}" if short else ""))
        self.status, self.body, self.retry_after = status, body, retry_after


def _request(url: str, timeout: float, body: dict | None = None) -> tuple[int, str]:
    headers = {"User-Agent": "panelwall/0.1 (github.com/ahmadazim/panelwall)", "Accept": "application/json"}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method="POST" if body is not None else "GET", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        ra = e.headers.get("Retry-After") if e.headers else None
        try:
            ra = float(ra) if ra else None
        except ValueError:
            ra = None
        raise ApiError(e.code, e.read().decode("utf-8", "replace"), ra) from None


def _get_json(url: str, timeout: float):
    _, text = _request(url, timeout)
    return json.loads(text)


def _post_json(url: str, body: dict, timeout: float):
    """POST and parse JSON. An empty 200 body is treated as an empty list."""
    _, text = _request(url, timeout, body)
    return json.loads(text) if text.strip() else []


def parse_aircraft(raw: dict, here_lat: float, here_lon: float) -> Aircraft:
    alt = raw.get("alt_baro")
    on_ground = alt == "ground"
    alt_i = 0 if on_ground else (int(alt) if isinstance(alt, (int, float)) else None)
    lat, lon = raw.get("lat"), raw.get("lon")
    dist = _haversine_nm(here_lat, here_lon, lat, lon) if lat is not None and lon is not None else None

    def _int(v):
        return int(round(v)) if isinstance(v, (int, float)) else None

    return Aircraft(
        hex=str(raw.get("hex", "")),
        callsign=(raw.get("flight") or "").strip(),
        registration=(raw.get("r") or "").strip(),
        type_code=(raw.get("t") or "").strip(),
        altitude=alt_i,
        on_ground=on_ground,
        speed=_int(raw.get("gs")),
        track=_int(raw.get("track")),
        vrate=_int(raw.get("baro_rate", raw.get("geom_rate"))),
        lat=lat, lon=lon,
        distance_nm=dist,
        extra={"desc": raw.get("desc", ""), "seen": raw.get("seen")},
    )


def parse_adsbdb_route(doc: dict) -> tuple[str, str, tuple | None, tuple | None]:
    """adsbdb /v0/callsign reply -> (origin_iata, dest_iata, (lat, lon) | None, (lat, lon) | None).
    Unknown callsign (their 404 body is {"response": "unknown callsign"}) -> ('', '', None, None)."""
    r = doc.get("response") if isinstance(doc, dict) else None
    fr = r.get("flightroute") if isinstance(r, dict) else None
    if not isinstance(fr, dict):
        return "", "", None, None
    o, d = fr.get("origin") or {}, fr.get("destination") or {}

    def _pos(a):
        lat, lon = a.get("latitude"), a.get("longitude")
        return (float(lat), float(lon)) if isinstance(lat, (int, float)) and isinstance(lon, (int, float)) else None

    oi, di = (o.get("iata_code") or "").upper(), (d.get("iata_code") or "").upper()
    if not oi or not di:
        return "", "", None, None
    return oi, di, _pos(o), _pos(d)


def parse_route(entry: dict) -> tuple[str, str]:
    """(legacy adsb.lol routeset shape, endpoint is dead) entry -> (origin_iata, dest_iata) or ('', '')."""
    if not entry or entry.get("plausible") is False:
        return "", ""
    codes = entry.get("_airport_codes_iata") or ""
    if not codes:
        # fall back to ICAO codes, crude US-style trim (KBOS -> BOS)
        icao = entry.get("airport_codes") or ""
        codes = "-".join(c[1:] if len(c) == 4 and c[0] == "K" else c for c in icao.split("-"))
    parts = [p for p in codes.split("-") if p and p != "unknown"]
    if len(parts) >= 2:
        return parts[0], parts[-1]
    return "", ""


BACKOFF_MIN, BACKOFF_MAX = 15.0, 300.0
NEGATIVE_ROUTE_TTL = 6 * 3600.0     # "unknown callsign" (private N-numbers): don't re-ask for hours


class AdsbClient:
    def __init__(self, base: str | None = None, timeout: float | None = None, routes_base: str | None = None):
        self.base = (base or CONFIG.data.adsb_base).rstrip("/")
        self.routes_base = (CONFIG.data.routes_base if routes_base is None else routes_base).rstrip("/")
        self.timeout = timeout or CONFIG.data.http_timeout
        # callsign -> (fetched_at, (origin, dest, origin_pos, dest_pos))
        self._routes: dict[str, tuple[float, tuple]] = {}
        self.last_error: str | None = None       # the aircraft fetch itself
        self.route_error: str | None = None      # adsbdb lookups: cosmetic (routes show '---'), never blocks the card
        self.backoff_until = 0.0           # epoch; the feed sleeps until then after a 429
        self._backoff = BACKOFF_MIN

    def fetch_raw(self, lat: float, lon: float, radius_nm: float) -> dict:
        return _get_json(f"{self.base}/v2/point/{lat:.4f}/{lon:.4f}/{int(radius_nm)}", self.timeout)

    def route_raw(self, callsign: str) -> tuple[int, str]:
        """Debug helper: raw (status, body) from the route lookup for one callsign."""
        return _request(f"{self.routes_base}/v0/callsign/{callsign.strip()}", self.timeout)

    def _note_rate_limit(self, e: ApiError) -> None:
        wait = e.retry_after if e.retry_after else self._backoff
        self._backoff = min(BACKOFF_MAX, self._backoff * 2)
        self.backoff_until = time.time() + wait
        self.last_error = f"HTTP 429 rate limited by {self.base}; retrying in {int(wait)} s"

    def nearby(self, lat: float, lon: float, radius_nm: float) -> list[Aircraft]:
        try:
            raw = self.fetch_raw(lat, lon, radius_nm)
            self.last_error = None
            self._backoff = BACKOFF_MIN
        except ApiError as e:
            if e.status == 429:
                self._note_rate_limit(e)
            else:
                self.last_error = f"{type(e).__name__}: {e}"
            return []
        except Exception as e:  # network down, API down, bad JSON - keep rendering
            self.last_error = f"{type(e).__name__}: {e}"
            return []
        acs = [parse_aircraft(a, lat, lon) for a in raw.get("ac", [])]
        # drop stale/positionless
        acs = [a for a in acs if a.lat is not None and (a.extra.get("seen") is None or a.extra["seen"] < 30)]
        acs.sort(key=lambda a: a.distance_nm if a.distance_nm is not None else 1e9)
        self._attach_routes(acs)
        return acs

    def _attach_routes(self, acs: list[Aircraft]) -> None:
        """Fill origin/destination from the cache; look up at most `route_lookups_per_poll`
        uncached airline callsigns per call (closest first) so a busy sky trickles in."""
        if not self.routes_base:
            return
        now = time.time()
        ttl = CONFIG.data.route_cache_seconds
        budget = CONFIG.data.route_lookups_per_poll
        for a in acs:
            cs = a.callsign
            if not cs or not cs[:3].isalpha() or not cs[3:4].isdigit():   # airline-style only; N-numbers have no route
                continue
            hit = self._routes.get(cs)
            if hit and now - hit[0] < ttl:
                self._apply_route(a, hit[1])
                continue
            if budget <= 0:
                continue
            budget -= 1
            try:
                _, text = self.route_raw(cs)
                route = parse_adsbdb_route(json.loads(text) if text.strip() else {})
                self._routes[cs] = (now, route)
                self.route_error = None
            except ApiError as e:
                if e.status == 404:                                   # unknown callsign: remember for hours
                    self._routes[cs] = (now - ttl + NEGATIVE_ROUTE_TTL, ("", "", None, None))
                else:
                    self.route_error = f"routes: {e}"
                    self._routes[cs] = (now - ttl + 120, ("", "", None, None))
                    budget = 0                                        # stop hammering a failing service
                route = self._routes[cs][1]
            except Exception as e:
                self.route_error = f"routes: {type(e).__name__}: {e}"
                self._routes[cs] = (now - ttl + 120, ("", "", None, None))
                budget = 0
                route = self._routes[cs][1]
            self._apply_route(a, route)

    @staticmethod
    def _apply_route(a: Aircraft, route: tuple) -> None:
        a.origin, a.destination = route[0], route[1]
        if len(route) >= 4 and route[2] and route[3]:
            a.extra["route_pos"] = (route[2], route[3])
