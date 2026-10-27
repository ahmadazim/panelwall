"""MBTA V3 API client + parsers (https://api-v3.mbta.com, JSON:API shape).

Verified live on 2026-09-14 (fixtures/mbta_red.json is a trimmed capture):
  GET /stops?filter[route]=Red
      -> data[]: {id: "place-harsq", attributes: {name: "Harvard", location_type: 1}}
         parent stations, in route order, BOTH branches after JFK/UMass.
  GET /vehicles?filter[route]=Red&include=stop
      -> data[]: {attributes: {current_status: STOPPED_AT|INCOMING_AT|IN_TRANSIT_TO,
                               direction_id: 0|1}, relationships.stop.data.id: "70063"}
         included[]: child platform stops with relationships.parent_station.data.id
  GET /predictions?filter[stop]=place-harsq&filter[route]=Red&sort=arrival_time
      -> data[]: {attributes: {arrival_time, departure_time (ISO 8601 or null), direction_id}}
  GET /routes/Red -> direction_names ["South","North"], direction_destinations
      ["Ashmont/Braintree","Alewife"]

An API key (env MBTA_API_KEY) is optional: without one the rate limit is 20
requests/minute, and we make 2 every 15 s. With one it is 1000/minute.

Everything network-facing is wrapped; a dead API yields None and sets
`last_error`, never an exception in the frame loop.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone

from ..config import CONFIG, LineSpec, MBTA_LINES
from .polling import Backoff, DemandPoller, retry_after_seconds

# Red Line branches south of JFK/UMass. Drawing both on one horizontal strip is
# impossible, so the channel picks one (CONFIG.mbta.branch).
BRANCHES: dict[str, set[str]] = {
    "Ashmont": {"place-shmnl", "place-fldcr", "place-smmnl", "place-asmnl"},
    "Braintree": {"place-nqncy", "place-wlsta", "place-qnctr", "place-qamnl", "place-brntn"},
}

# 3-letter labels for the strip. Anything missing falls back to the first 3 letters of the name.
ABBREV: dict[str, str] = {
    # Red
    "place-alfcl": "ALW", "place-davis": "DAV", "place-portr": "PTR", "place-harsq": "HVD",
    "place-cntsq": "CEN", "place-knncl": "KEN", "place-chmnl": "CHS", "place-pktrm": "PRK",
    "place-dwnxg": "DTX", "place-sstat": "SST", "place-brdwy": "BRD", "place-andrw": "AND",
    "place-jfk": "JFK", "place-shmnl": "SAV", "place-fldcr": "FLD", "place-smmnl": "SHW",
    "place-asmnl": "ASH", "place-nqncy": "NQU", "place-wlsta": "WOL", "place-qnctr": "QCT",
    "place-qamnl": "QAD", "place-brntn": "BRN",
    # Green trunk
    "place-unsqu": "USQ", "place-lech": "LEC", "place-spmnl": "SCP", "place-north": "NST", "place-haecl": "HAY",
    "place-gover": "GOV", "place-boyls": "BOY", "place-armnl": "ARL", "place-coecl": "COP", "place-hymnl": "HYN",
    "place-kencl": "KEN",
    # Green B
    "place-bland": "BLA", "place-buest": "BUE", "place-bucen": "BUC", "place-amory": "AMO", "place-babck": "BAB",
    "place-brico": "PAC", "place-harvd": "HAR", "place-grigg": "GRI", "place-alsgr": "ALL", "place-wrnst": "WAR",
    "place-wascm": "WAS", "place-sthld": "SUT", "place-chswk": "CHW", "place-chill": "CHA", "place-sougr": "SOU",
    "place-lake": "BC",
    # Green C
    "place-smary": "STM", "place-hwsst": "HAW", "place-kntst": "KNT", "place-stpul": "STP", "place-cool": "COO",
    "place-sumav": "SUM", "place-bndhl": "BRA", "place-fbkst": "FAI", "place-bcnwa": "WSQ", "place-tapst": "TAP",
    "place-denrd": "DEA", "place-engav": "ENG", "place-clmnl": "CLE",
    # Green D
    "place-fenwy": "FEN", "place-longw": "LNG", "place-bvmnl": "BVL", "place-brkhl": "BHL", "place-bcnfd": "BCF",
    "place-rsmnl": "RES", "place-chhil": "CHH", "place-newto": "NCT", "place-newtn": "NHL", "place-eliot": "ELI",
    "place-waban": "WAB", "place-woodl": "WOO", "place-river": "RIV",
}

# Long station / destination names -> what fits on the arrival rows
_SHORT = (("Government Center", "GOV CTR"), ("Boston University", "BU"), ("Convention Center", "CONV CTR"),
          ("Cleveland Circle", "CLEVELAND CIR"), ("Brighton Center", "BRIGHTON CTR"),
          ("Street", "ST"), ("Square", "SQ"), ("Avenue", "AVE"), ("Center", "CTR"), ("Centre", "CTR"),
          ("Station", ""), ("Saint", "ST"), ("Road", "RD"), ("Highlands", "HLDS"))
# tightest forms, for rows that hold two destinations
_TINY = {"Boston College": "BC", "Government Center": "GOV CTR", "Cleveland Circle": "CLEV CIR", "Union Square": "UNION SQ",
         "Riverside": "RIVERSIDE", "Ruggles Station": "RUGGLES", "Brighton Center": "BRIGHTON", "Alewife": "ALEWIFE",
         "Ashmont/Braintree": "ASH/BRAIN", "Washington Street": "WASH ST"}


def short_name(name: str, limit: int = 15) -> str:
    n = name
    for a, b in _SHORT:
        n = n.replace(a, b)
    return " ".join(n.upper().split())[:limit]


def tiny_name(name: str, limit: int = 9) -> str:
    """Shortest readable form of a terminus / station, for rows that list two of them."""
    return _TINY.get(name.strip(), short_name(name, limit))[:limit]


def orient(stops: list[Stop], dest0: str | None) -> list[Stop]:
    """The API's stop order is arbitrary per route. Flip the list so that direction_id 0's
    destination is the LAST stop (right end of the strip); train_x relies on that."""
    if stops and dest0 and stops[0].name.strip().lower() == dest0.strip().lower():
        return list(reversed(stops))
    return list(stops)


@dataclass
class Stop:
    id: str
    name: str

    @property
    def abbrev(self) -> str:
        return ABBREV.get(self.id) or self.name[:3].upper()


@dataclass
class Vehicle:
    id: str
    stop_id: str            # parent station id if resolvable, else the raw stop id
    direction_id: int       # 0 = southbound (Ashmont/Braintree), 1 = northbound (Alewife) on the Red Line
    status: str             # STOPPED_AT | INCOMING_AT | IN_TRANSIT_TO


@dataclass
class Prediction:
    direction_id: int
    when: datetime          # arrival if present else departure, tz-aware

    def minutes(self, now: datetime) -> int:
        return int((self.when - now).total_seconds() // 60)


# ---- pure parsers ------------------------------------------------------------------
def parse_stops(doc: dict) -> list[Stop]:
    out = []
    for e in doc.get("data", []):
        attrs = e.get("attributes", {})
        out.append(Stop(id=e.get("id", ""), name=attrs.get("name") or e.get("id", "")))
    return out


def select_branch(stops: list[Stop], branch: str) -> list[Stop]:
    """Drop the stops that belong to the OTHER branch(es). Unknown branch -> unchanged."""
    if branch not in BRANCHES:
        return list(stops)
    others = set().union(*(ids for name, ids in BRANCHES.items() if name != branch))
    return [s for s in stops if s.id not in others]


def parse_vehicles(doc: dict) -> list[Vehicle]:
    parent = {}
    for inc in doc.get("included", []):
        if inc.get("type") == "stop":
            ps = (inc.get("relationships", {}).get("parent_station", {}) or {}).get("data") or {}
            parent[inc.get("id")] = ps.get("id") or inc.get("id")
    out = []
    for e in doc.get("data", []):
        attrs = e.get("attributes", {})
        stop = ((e.get("relationships", {}).get("stop", {}) or {}).get("data") or {}).get("id")
        if stop is None or attrs.get("direction_id") is None:
            continue
        out.append(Vehicle(id=e.get("id", ""), stop_id=parent.get(stop, stop),
                           direction_id=int(attrs["direction_id"]),
                           status=attrs.get("current_status") or "IN_TRANSIT_TO"))
    return out


def _parse_time(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def parse_predictions(doc: dict) -> list[Prediction]:
    out = []
    for e in doc.get("data", []):
        attrs = e.get("attributes", {})
        when = _parse_time(attrs.get("arrival_time")) or _parse_time(attrs.get("departure_time"))
        if when is None or attrs.get("direction_id") is None:
            continue
        out.append(Prediction(direction_id=int(attrs["direction_id"]), when=when))
    out.sort(key=lambda p: p.when)
    return out


def upcoming(preds: list[Prediction], direction_id: int, now: datetime, n: int = 3) -> list[int]:
    """Minutes until the next n trains in one direction (>= 0 only)."""
    mins = [p.minutes(now) for p in preds if p.direction_id == direction_id]
    return [m for m in mins if m >= 0][:n]


# ---- client ------------------------------------------------------------------------
class MbtaClient:
    def __init__(self, base: str | None = None, api_key: str | None = None, timeout: float | None = None):
        self.base = (base or CONFIG.mbta.base).rstrip("/")
        self.api_key = api_key if api_key is not None else CONFIG.mbta.api_key
        self.timeout = timeout or CONFIG.data.http_timeout
        self.last_error: str | None = None
        self.backoff = Backoff()

    def _get(self, path: str, params: dict) -> dict | None:
        url = f"{self.base}{path}?{urllib.parse.urlencode(params)}"
        headers = {"User-Agent": "panelwall/0.1", "Accept": "application/vnd.api+json"}
        if self.api_key:
            headers["x-api-key"] = self.api_key
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=self.timeout) as r:
                doc = json.loads(r.read().decode("utf-8", "replace"))
            self.last_error = None
            self.backoff.reset()
            return doc
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = self.backoff.note(retry_after_seconds(e.headers))
                self.last_error = f"HTTP 429 rate limited by MBTA; retrying in {int(wait)} s"
            else:
                self.last_error = f"HTTP {e.code} {path}"
        except Exception as e:  # DNS, timeout, bad JSON
            self.last_error = f"{type(e).__name__}: {e}"
        return None

    def stops(self, route: str) -> dict | None:
        return self._get("/stops", {"filter[route]": route})

    def vehicles(self, route: str) -> dict | None:
        return self._get("/vehicles", {"filter[route]": route, "include": "stop"})

    def predictions(self, stop: str, route: str) -> dict | None:
        """`stop` may be a comma-separated list (the API accepts it) - used for the two bus stops."""
        return self._get("/predictions", {"filter[stop]": stop, "filter[route]": route, "sort": "arrival_time"})

    def route(self, route: str) -> dict | None:
        return self._get(f"/routes/{route}", {})


class MbtaFeed(DemandPoller):
    """Background poller for one LineSpec. Stops + route info are fetched once an hour; vehicles,
    home predictions and (if configured) bus predictions every CONFIG.mbta.poll_seconds -
    2 or 3 requests per poll.

    MbtaFeed(static=fixture_dict) never starts a thread and freezes 'now' at the fixture's
    _now so the demo shows stable minutes.
    """

    def __init__(self, client: MbtaClient | None = None, static: dict | None = None, spec: LineSpec | None = None):
        self.spec = spec or MBTA_LINES["mbta"]
        self.client = client or MbtaClient()
        self.route, self.home, self.branch = self.spec.route, self.spec.home_stop, self.spec.branch
        self.stops: list[Stop] = []
        self.vehicles: list[Vehicle] = []
        self.predictions: list[Prediction] = []
        self.bus_predictions: list[Prediction] = []
        self.directions: tuple[str, str] = ("", "")        # direction_destinations from /routes/{id}
        self.bus_directions: tuple[str, str] = ("", "")
        self.updated_at = 0.0
        self._stops_at = 0.0
        self._fixed_now: datetime | None = None
        self._init_demand()
        self._thread = None
        if static is not None:
            self._ingest(static.get("stops"), static.get("vehicles"), static.get("predictions"),
                         static.get("route"), static.get("bus_predictions"), static.get("bus_route"))
            self._fixed_now = _parse_time(static.get("_now"))
            self.updated_at = time.time()
        else:
            self._thread = threading.Thread(target=self._poll_loop, daemon=True, name=f"mbta-{self.spec.name}")
            self._thread.start()

    @property
    def last_error(self) -> str | None:
        return self.client.last_error

    def now(self) -> datetime:
        return self._fixed_now or datetime.now(timezone.utc)

    def home_stop(self) -> Stop | None:
        return next((s for s in self.stops if s.id == self.home), None)

    @staticmethod
    def _dests(route_doc) -> tuple[str, str]:
        try:
            d = route_doc["data"]["attributes"]["direction_destinations"]
            return str(d[0]), str(d[1])
        except (KeyError, IndexError, TypeError):
            return "", ""

    def _ingest(self, stops_doc, vehicles_doc, preds_doc, route_doc=None, bus_doc=None, bus_route_doc=None) -> None:
        if route_doc is not None:
            self.directions = self._dests(route_doc)
        if bus_route_doc is not None:
            self.bus_directions = self._dests(bus_route_doc)
        if stops_doc is not None:
            self.stops = orient(select_branch(parse_stops(stops_doc), self.branch), self.directions[0])
        if vehicles_doc is not None:
            self.vehicles = parse_vehicles(vehicles_doc)
        if preds_doc is not None:
            self.predictions = parse_predictions(preds_doc)
        if bus_doc is not None:
            self.bus_predictions = parse_predictions(bus_doc)

    def _poll_loop(self):
        self._startup_grace()
        self._wait_wanted()
        while not self._stop.is_set():
            t = time.time()
            stops_doc = route_doc = bus_route_doc = None
            if not self.stops or t - self._stops_at > 3600:
                route_doc = self.client.route(self.route)
                stops_doc = self.client.stops(self.route)
                if self.spec.bus_route and not self.bus_directions[0]:
                    bus_route_doc = self.client.route(self.spec.bus_route)
                if stops_doc is not None:
                    self._stops_at = t
            ok = self.client.backoff.remaining() == 0
            veh = self.client.vehicles(self.route) if ok else None
            preds = self.client.predictions(self.home, self.route) if ok else None
            bus = None
            if ok and self.spec.bus_route and self.spec.bus_stops:
                bus = self.client.predictions(",".join(self.spec.bus_stops), self.spec.bus_route)
            self._ingest(stops_doc, veh, preds, route_doc, bus, bus_route_doc)
            if veh is not None or preds is not None:
                self.updated_at = time.time()
            self._sleep_or_pause(max(CONFIG.mbta.poll_seconds, self.client.backoff.remaining()))

    def status(self) -> dict:
        s = {"updated_at": self.updated_at or None, "last_error": self.last_error, "paused": self.paused,
             "stops": len(self.stops), "vehicles": len(self.vehicles), "predictions": len(self.predictions)}
        if self.spec.bus_route:
            s["bus"] = len(self.bus_predictions)
        return s

    def close(self):
        self._stop.set()
