"""FlightsChannel: a FlightWall-style list of aircraft overhead.

Layout (256x64):
  y 1-7   header: OVERHEAD · n aircraft            HH:MM
  y 10-63 up to 5 rows, 11 px each (2 px gap under the header):
          FLIGHT   ROUTE    TYPE       ALT    SPD  ^hdg
  The row for the closest aircraft is highlighted.

Data arrives from a background thread; render() only reads the latest
snapshot, so a slow or dead API can never stall the frame loop.
"""

from __future__ import annotations

import math
from datetime import datetime

from .. import fonts
from ..config import CONFIG
from ..data.adsb import AdsbClient, Aircraft
from ..data.feed import AircraftFeed
from ..framebuffer import Frame, W, AMBER, WHITE, GREY, DIM, GREEN, RED, CYAN
from .base import Channel

MAX_ROWS = 5
ROW_Y0 = 10
ROW_H = 11

# column x positions (left edges, or right edges for right-aligned numbers)
X_FLIGHT = 2
X_ROUTE = 50
X_TYPE = 96
XR_ALT = 200
XR_SPD = 234
X_HDG = 240
X_VR = 250


class FlightsChannel(Channel):
    name = "flights"

    def __init__(self, client: AdsbClient | None = None, poll_seconds: float | None = None,
                 static: list[Aircraft] | None = None, feed: AircraftFeed | None = None):
        # Data comes from a shared AircraftFeed (one poller for all aircraft channels).
        # Passing client/static builds a private feed - kept for the old call sites.
        self.feed = feed or AircraftFeed(client=client, poll_seconds=poll_seconds, static=static)
        self._owns_feed = feed is None
        self.t = 0.0

    # ---- data --------------------------------------------------------------
    @property
    def client(self) -> AdsbClient:
        return self.feed.client

    @property
    def aircraft(self) -> list[Aircraft]:
        return self.feed.aircraft

    def status(self) -> dict:
        return self.feed.status()

    def close(self):
        if self._owns_feed:
            self.feed.close()

    # ---- scheduling ----------------------------------------------------------
    def tick(self, dt: float) -> None:
        self.t += dt

    def priority(self) -> int:
        return 10 if self.aircraft else 1   # still shows an "empty sky" screen at low priority

    # ---- drawing -------------------------------------------------------------
    def render(self, frame: Frame) -> None:
        now = datetime.now()
        n = len(self.aircraft)
        frame.text(X_FLIGHT, 1, "OVERHEAD", fonts.SMALL, AMBER)
        sub = f"{n} AIRCRAFT" if n != 1 else "1 AIRCRAFT"
        frame.text(X_FLIGHT + fonts.width("OVERHEAD ") + 2, 1, sub, fonts.SMALL, GREY)
        clock = now.strftime("%H:%M") if int(self.t) % 2 == 0 else now.strftime("%H %M")
        frame.text_right(W - 2, 1, clock, fonts.SMALL, AMBER)

        if not self.aircraft:
            self._render_empty(frame)
            return

        for i, a in enumerate(self.aircraft[:MAX_ROWS]):
            y = ROW_Y0 + i * ROW_H
            hot = i == 0
            col = WHITE if hot else GREY
            frame.text(X_FLIGHT, y, a.flight[:8], fonts.SMALL, AMBER if hot else WHITE)
            frame.text(X_ROUTE, y, a.route or "---", fonts.SMALL, col)
            frame.text(X_TYPE, y, a.type_name[:10], fonts.SMALL, col)
            if a.altitude is not None:
                frame.text_right(XR_ALT, y, f"{a.altitude}FT" if a.altitude else "GND", fonts.SMALL, col)
            if a.speed is not None:
                frame.text_right(XR_SPD, y, f"{a.speed}KT", fonts.SMALL, col)
            if a.track is not None:
                _heading_arrow(frame, X_HDG, y + 3, a.track, col)
            _vrate_marker(frame, X_VR, y, a.vrate)

    def _render_empty(self, frame: Frame) -> None:
        msg = "NO AIRCRAFT OVERHEAD" if self.client.last_error is None else "NO DATA - CHECK NETWORK"
        frame.text_center(W // 2, 26, msg, fonts.MEDIUM, GREY if self.client.last_error is None else RED)
        loc = CONFIG.location
        frame.text_center(W // 2, 42, f"WITHIN {loc.radius_nm:g} NM", fonts.SMALL, DIM)
        # slow "radar sweep" dot along the bottom so the screen is visibly alive
        x = int((self.t * 30) % W)
        frame.draw.point((x, 62), fill=DIM)


def _heading_arrow(frame: Frame, cx: int, cy: int, track_deg: float, color) -> None:
    """A 7px arrow pointing along the aircraft's track (0 = up/north)."""
    a = math.radians(track_deg)
    dx, dy = math.sin(a), -math.cos(a)
    tip = (cx + dx * 3.2, cy + dy * 3.2)
    tail = (cx - dx * 3.2, cy - dy * 3.2)
    frame.draw.line([tail, tip], fill=color)
    # arrowhead: two short strokes back from the tip
    for s in (+1, -1):
        b = a + s * math.radians(150)
        frame.draw.line([tip, (tip[0] + math.sin(b) * 2.2, tip[1] - math.cos(b) * 2.2)], fill=color)


def _vrate_marker(frame: Frame, x: int, y: int, vrate: int | None) -> None:
    if vrate is None or abs(vrate) < 300:
        frame.draw.line([(x, y + 3), (x + 4, y + 3)], fill=DIM)
        return
    up = vrate > 0
    c = GREEN if up else RED
    if up:
        pts = [(x + 2, y + 1), (x, y + 3), (x + 4, y + 3)]
        frame.draw.line([(x + 2, y + 1), (x + 2, y + 6)], fill=c)
    else:
        pts = [(x + 2, y + 6), (x, y + 4), (x + 4, y + 4)]
        frame.draw.line([(x + 2, y + 1), (x + 2, y + 6)], fill=c)
    frame.draw.polygon(pts, fill=c)
