"""RadarChannel: a 64x64 radar scope on the left, an overhead list on the right.

Layout (256x64):
  x 0-63   scope: range rings at 1/3, 2/3, full radius; N/S/E/W hairlines;
           a sweep that turns once per SWEEP_SECONDS with a fading wedge;
           aircraft as 3x3 blips + 4px heading tick, colored by altitude band.
  x 70-255 header (y 4-8): RADAR  <radius>NM                     HH:MM
           up to 4 rows, 12 px apart: swatch, flight, route, type, altitude.

Blip position: flat-earth projection around CONFIG.location (nm east/north),
scaled so `radius_nm` lands on the outer ring; anything further is clipped
to the ring so a far-away aircraft still shows its bearing.

Data comes from the shared AircraftFeed - this channel never polls itself.
"""

from __future__ import annotations

import math
from datetime import datetime

from .. import fonts
from ..config import CONFIG
from ..data.adsb import Aircraft
from ..data.feed import AircraftFeed
from ..framebuffer import Frame, W, AMBER, WHITE, GREY, DIM, GREEN, RED, CYAN
from .base import Channel

CX, CY, R = 32, 32, 30
SWEEP_SECONDS = 4.0
WEDGE_DEG = 60
WEDGE_STEPS = 30

RING = (0, 70, 34)
HAIR = (0, 48, 22)
SWEEP_MAX = 150

MAX_ROWS = 4
X0 = 70            # list left edge
X_FLIGHT = X0 + 6
X_ROUTE = 120
X_TYPE = 166
XR_ALT = W - 2
ROW_Y0 = 10
ROW_H = 12


def altitude_color(alt: int | None):
    """Altitude band -> blip color. Low = amber, mid = green, high = cyan."""
    if alt is None:
        return GREY
    if alt < 3000:
        return AMBER
    if alt < 10000:
        return GREEN
    return CYAN


def project(lat: float, lon: float, lat0: float, lon0: float, radius_nm: float,
            r_px: float = R) -> tuple[float, float]:
    """(lat, lon) -> (dx, dy) pixels from the scope center, +x east, +y south.

    Flat-earth: 1 degree latitude = 60 nm, 1 degree longitude = 60*cos(lat) nm.
    Fine within a few hundred nm. Points beyond radius_nm are pulled back onto
    the outer ring (bearing preserved).
    """
    dn = (lat - lat0) * 60.0
    de = (lon - lon0) * 60.0 * math.cos(math.radians(lat0))
    scale = r_px / max(radius_nm, 0.1)
    dx, dy = de * scale, -dn * scale
    d = math.hypot(dx, dy)
    if d > r_px - 1:
        f = (r_px - 1) / d
        dx, dy = dx * f, dy * f
    return dx, dy


class RadarChannel(Channel):
    name = "radar"

    def __init__(self, feed: AircraftFeed | None = None, static: list[Aircraft] | None = None):
        self.feed = feed or AircraftFeed(static=static)
        self._owns_feed = feed is None
        self.t = 0.0

    @property
    def aircraft(self) -> list[Aircraft]:
        return self.feed.aircraft

    def status(self) -> dict:
        return self.feed.status()

    def close(self):
        if self._owns_feed:
            self.feed.close()

    def tick(self, dt: float) -> None:
        self.t += dt

    def priority(self) -> int:
        return 10 if self.aircraft else 1

    # ---- drawing -------------------------------------------------------------
    def render(self, frame: Frame) -> None:
        self._render_scope(frame)
        self._render_list(frame)

    def _render_scope(self, frame: Frame) -> None:
        d = frame.draw
        for r in (R // 3, 2 * R // 3, R):
            d.ellipse([CX - r, CY - r, CX + r, CY + r], outline=RING)
        d.line([(CX - R, CY), (CX + R, CY)], fill=HAIR)
        d.line([(CX, CY - R), (CX, CY + R)], fill=HAIR)

        # sweep: a bright leading edge, then a fading wedge behind it (clockwise)
        head = (self.t / SWEEP_SECONDS * 360.0) % 360.0
        for i in range(WEDGE_STEPS, -1, -1):
            a = math.radians(90 - (head - i * WEDGE_DEG / WEDGE_STEPS))
            g = int(SWEEP_MAX * (1 - i / WEDGE_STEPS) ** 2)
            if g < 8:
                continue
            d.line([(CX, CY), (CX + R * math.cos(a), CY - R * math.sin(a))], fill=(0, g, g * 2 // 5))
        d.point((CX, CY), fill=WHITE)

        loc = CONFIG.location
        for a in self.aircraft:
            if a.lat is None or a.lon is None:
                continue
            dx, dy = project(a.lat, a.lon, loc.lat, loc.lon, loc.radius_nm)
            bx, by = int(round(CX + dx)), int(round(CY + dy))
            c = altitude_color(a.altitude)
            d.rectangle([bx - 1, by - 1, bx + 1, by + 1], fill=c)
            if a.track is not None:
                t = math.radians(a.track)
                d.line([(bx, by), (bx + 4 * math.sin(t), by - 4 * math.cos(t))], fill=c)

    def _render_list(self, frame: Frame) -> None:
        loc = CONFIG.location
        frame.text(X0, 0, "RADAR", fonts.SMALL, AMBER)
        frame.text(X0 + fonts.width("RADAR ") + 2, 0, f"{loc.radius_nm:g}NM", fonts.SMALL, GREY)
        now = datetime.now()
        clock = now.strftime("%H:%M") if int(self.t) % 2 == 0 else now.strftime("%H %M")
        frame.text_right(W - 2, 0, clock, fonts.SMALL, AMBER)

        acs = self.aircraft
        if not acs:
            err = self.feed.last_error
            msg = "NO AIRCRAFT" if err is None else "NO DATA"
            frame.text_center((X0 + W) // 2, 24, msg, fonts.MEDIUM, GREY if err is None else RED)
            sub = f"WITHIN {loc.radius_nm:g} NM" if err is None else "CHECK NETWORK"
            frame.text_center((X0 + W) // 2, 36, sub, fonts.SMALL, DIM if err is None else RED)
            return

        for i, a in enumerate(acs[:MAX_ROWS]):
            y = ROW_Y0 + i * ROW_H
            c = altitude_color(a.altitude)
            frame.rect([X0, y + 4, X0 + 2, y + 8], fill=c)
            frame.text(X_FLIGHT, y, a.flight[:8], fonts.SMALL, WHITE)
            frame.text(X_ROUTE, y, a.route or "---", fonts.SMALL, WHITE if a.route else GREY)
            frame.text(X_TYPE, y, a.type_name[:8], fonts.SMALL, GREY)
            if a.altitude is not None:
                frame.text_right(XR_ALT, y, str(a.altitude), fonts.SMALL, GREY)
