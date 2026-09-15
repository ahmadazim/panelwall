"""Live aircraft near a point, from adsb.lol (free, no key) or any readsb-style API.

Endpoints (adsb.lol; airplanes.live has the same /v2/point shape):
  GET  {base}/v2/point/{lat}/{lon}/{radius_nm}      -> {"ac": [...], "now": ..., ...}
  POST {base}/api/0/routeset  {"planes":[{"callsign","lat","lng"}]} -> [{callsign, airport_codes, _airport_codes_iata, plausible, ...}]

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

    def __init__(self, status: int, body: str):
        super().__init__(f"HTTP {status}: {body[:200]!r}")
        self.status, self.body = status, body


def _request(url: str, timeout: float, body: dict | None = None) -> tuple[int, str]:
    headers = {"User-Agent": "panelwall/0.1", "Accept": "application/json"}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method="POST" if body is not None else "GET", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        raise ApiError(e.code, e.read().decode("utf-8", "replace")) from None


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


def parse_route(entry: dict) -> tuple[str, str]:
    """routeset entry -> (origin_iata, dest_iata) or ('', '')."""
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


class AdsbClient:
    def __init__(self, base: str | None = None, timeout: float | None = None):
        self.base = (base or CONFIG.data.adsb_base).rstrip("/")
        self.timeout = timeout or CONFIG.data.http_timeout
        self._routes: dict[str, tuple[float, tuple[str, str]]] = {}
        self.last_error: str | None = None

    def fetch_raw(self, lat: float, lon: float, radius_nm: float) -> dict:
        return _get_json(f"{self.base}/v2/point/{lat:.4f}/{lon:.4f}/{int(radius_nm)}", self.timeout)

    def routeset_raw(self, planes: list[dict]) -> tuple[int, str]:
        """Debug helper: raw (status, body) from routeset. planes = [{callsign, lat, lng}, ...]"""
        return _request(f"{self.base}/api/0/routeset", self.timeout, {"planes": planes})

    def nearby(self, lat: float, lon: float, radius_nm: float) -> list[Aircraft]:
        try:
            raw = self.fetch_raw(lat, lon, radius_nm)
            self.last_error = None
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
        now = time.time()
        ttl = CONFIG.data.route_cache_seconds
        need = []
        for a in acs:
            if not a.callsign:
                continue
            hit = self._routes.get(a.callsign)
            if hit and now - hit[0] < ttl:
                a.origin, a.destination = hit[1]
            else:
                need.append(a)
        if not need:
            return
        body = {"planes": [{"callsign": a.callsign, "lat": a.lat, "lng": a.lon} for a in need]}
        try:
            resp = _post_json(f"{self.base}/api/0/routeset", body, self.timeout)
        except Exception as e:
            self.last_error = f"routeset {type(e).__name__}: {e}"
            for a in need:  # negative-cache briefly so we don't hammer the API
                self._routes[a.callsign] = (now - ttl + 60, ("", ""))
            return
        by_cs = {e.get("callsign", "").strip(): e for e in (resp or []) if isinstance(e, dict)}
        for a in need:
            route = parse_route(by_cs.get(a.callsign, {}))
            self._routes[a.callsign] = (now, route)
            a.origin, a.destination = route
