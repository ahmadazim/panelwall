"""AircraftFeed: ONE background poller shared by every aircraft channel.

Flights, Radar and Silhouette all want the same list of aircraft around
CONFIG.location. Polling adsb.lol three times would triple the load on a free
API for no benefit, so they share one feed:

    feed = AircraftFeed()              # starts a daemon thread
    FlightsChannel(feed=feed); RadarChannel(feed=feed); ...

`feed.aircraft` is a fresh list object on every successful poll (never mutated
in place), so render() can read it without a lock. A dead API leaves the last
good list in place and records `last_error`; nothing here ever raises into the
frame loop.

`AircraftFeed(static=[...])` never starts a thread: that's what the fixture
demos use.
"""

from __future__ import annotations

import threading
import time

from ..config import CONFIG
from .adsb import AdsbClient, Aircraft
from .polling import DemandPoller


class AircraftFeed(DemandPoller):
    def __init__(self, client: AdsbClient | None = None, poll_seconds: float | None = None,
                 static: list[Aircraft] | None = None):
        self.client = client or AdsbClient()
        self.poll = poll_seconds or CONFIG.data.poll_seconds
        self.static = static is not None
        self.aircraft: list[Aircraft] = [a for a in (static or []) if not a.on_ground]
        self.updated_at = time.time() if self.static else 0.0
        self._init_demand()
        self._thread = None
        if not self.static:
            self._thread = threading.Thread(target=self._poll_loop, daemon=True, name="adsb-poll")
            self._thread.start()

    @property
    def last_error(self) -> str | None:
        return self.client.last_error

    @property
    def radius_nm(self) -> float:
        return CONFIG.location.radius_nm

    def _poll_loop(self):
        self._startup_grace()
        self._wait_wanted()                          # don't spend a request on a panel nobody is looking at
        while not self._stop.is_set():
            loc = CONFIG.location  # re-read each time: the control server may move it
            acs = self.client.nearby(loc.lat, loc.lon, loc.radius_nm)
            if acs or self.client.last_error is None:
                self.aircraft = [a for a in acs if not a.on_ground]
                self.updated_at = time.time()
            # after a 429 the client asks us to wait longer than the normal poll
            self._sleep_or_pause(max(self.poll, self.client.backoff_until - time.time()))

    def status(self) -> dict:
        return {"updated_at": self.updated_at or None, "last_error": self.last_error, "count": len(self.aircraft),
                "paused": self.paused, "route_error": self.client.route_error}

    def close(self):
        self._stop.set()
