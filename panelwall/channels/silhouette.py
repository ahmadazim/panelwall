"""SilhouetteChannel: one aircraft (the closest) as a hero card.

Layout (256x64):
  x 2-101   y 4-8   aircraft description (SMALL, cyan), e.g. AIRBUS A-321NEO
            y 12-43 side-profile sprite (sprites.py), tail/stripe in airline colors
            y 49    dashed motion line;  y 58-62  distance + bearing from home
  x 108-255 y 1-8   airline + flight number (MEDIUM)
            y 13-28 ORIGIN ---o--->  DEST (LARGE, amber); the dot is how far along
                    the great-circle route the aircraft is (centered if unknown)
            y 37-59 three SMALL rows: ALT / SPD / phase   |   HDG / REG / type

priority(): 20 when exactly one aircraft is in range (the list views are
pointless for a single aircraft), 25 for DETAIL_SECONDS whenever a DIFFERENT
aircraft becomes the closest ("detail mode"), at most once per DETAIL_COOLDOWN
and never twice for the same aircraft, else 0. With a 50 nm radius and 20
aircraft the solo case never happens - detail mode is how this card gets seen.
"""

from __future__ import annotations

import math

from .. import fonts
from ..config import CONFIG
from ..data.adsb import Aircraft
from ..data.airlines import parse_callsign
from ..data.airports import route_progress
from ..data.feed import AircraftFeed
from ..framebuffer import Frame, W, AMBER, WHITE, GREY, DIM, GREEN, RED, CYAN
from ..sprites import sprite_for
from .base import Channel

X0 = 108           # right column
XR = W - 4
SPRITE_X, SPRITE_Y = 2, 12
DETAIL_SECONDS = 8.0
DETAIL_COOLDOWN = 45.0        # min gap between two detail cards
DETAIL_PRIORITY = 25
SOLO_PRIORITY = 20

_COMPASS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]


def bearing_text(lat0: float, lon0: float, lat: float, lon: float) -> str:
    dn = (lat - lat0)
    de = (lon - lon0) * math.cos(math.radians(lat0))
    ang = (math.degrees(math.atan2(de, dn)) + 360) % 360
    return _COMPASS[int((ang + 22.5) // 45) % 8]


class SilhouetteChannel(Channel):
    name = "silhouette"

    def __init__(self, feed: AircraftFeed | None = None, static: list[Aircraft] | None = None):
        self.feed = feed or AircraftFeed(static=static)
        self._owns_feed = feed is None
        self.t = 0.0
        self._detailed: dict[str, float] = {}       # hex -> t when its card was shown
        self._closest_hex: str | None = None
        self._detail_until = -DETAIL_COOLDOWN       # so the first card is not blocked by the cooldown

    @property
    def aircraft(self) -> list[Aircraft]:
        return self.feed.aircraft

    def status(self) -> dict:
        s = self.feed.status()
        s["detail"] = self.detail_active()
        return s

    def close(self):
        if self._owns_feed:
            self.feed.close()

    # ---- scheduling ----------------------------------------------------------
    def tick(self, dt: float) -> None:
        self.t += dt
        acs = self.aircraft
        closest = acs[0].hex if acs else None
        if closest is not None and closest not in self._detailed and self.t - self._detail_until >= DETAIL_COOLDOWN:
            # an aircraft we haven't featured yet is the closest -> show its card for a while
            self._detail_until = self.t + DETAIL_SECONDS
            self._detailed[closest] = self.t
        self._closest_hex = closest
        if len(self._detailed) > 200:   # forget aircraft that left long ago
            cutoff = self.t - 3600
            self._detailed = {h: t for h, t in self._detailed.items() if t > cutoff}

    def detail_active(self) -> bool:
        return bool(self.aircraft) and self.t < self._detail_until

    def priority(self) -> int:
        if self.detail_active():
            return DETAIL_PRIORITY
        return SOLO_PRIORITY if len(self.aircraft) == 1 else 0

    # ---- drawing -------------------------------------------------------------
    def render(self, frame: Frame) -> None:
        acs = self.aircraft
        if not acs:
            frame.text_center(W // 2, 28, "NO AIRCRAFT", fonts.MEDIUM, GREY)
            return
        a = acs[0]
        self._render_left(frame, a)
        self._render_right(frame, a)

    def _render_left(self, frame: Frame, a: Aircraft) -> None:
        desc = (a.extra.get("desc") or "").upper().strip()
        label = desc if desc and fonts.width(desc) <= 100 else a.type_name
        frame.text(2, 0, label, fonts.SMALL, CYAN)

        icao = a.callsign[:3] if a.callsign[:3].isalpha() else ""
        spr = sprite_for(a.type_code, icao)
        frame.img.paste(spr, (SPRITE_X, SPRITE_Y), spr)

        # motion dashes, scrolling backwards (the plane flies left -> right... it faces left, so dashes drift right)
        off = int(self.t * 12) % 6
        for x in range(2 + off, 102, 6):
            frame.draw.line([(x, 49), (x + 2, 49)], fill=DIM)

        loc = CONFIG.location
        if a.distance_nm is not None and a.lat is not None:
            brg = bearing_text(loc.lat, loc.lon, a.lat, a.lon)
            frame.text(2, 54, f"{a.distance_nm:.1f}NM {brg}", fonts.SMALL, GREY)

    def _render_right(self, frame: Frame, a: Aircraft) -> None:
        _, airline, num = parse_callsign(a.callsign)
        title = f"{airline} {num}" if airline else (a.callsign or a.registration or a.hex.upper())
        frame.text(X0, 1, title[:18], fonts.MEDIUM, WHITE)

        o, d = a.origin or "---", a.destination or "---"
        frame.text(X0, 13, o, fonts.LARGE, AMBER if a.origin else DIM)
        frame.text_right(XR, 13, d, fonts.LARGE, AMBER if a.destination else DIM)
        # route line with arrow, between the two codes
        lx0, lx1, ly = X0 + 52, XR - 52, 21
        frame.draw.line([(lx0, ly), (lx1, ly)], fill=GREY)
        frame.draw.polygon([(lx1, ly), (lx1 - 3, ly - 3), (lx1 - 3, ly + 3)], fill=GREY)
        frac = None
        if a.origin and a.destination:
            pos = a.extra.get("route_pos")           # airport coordinates from adsbdb, when it gave them
            frac = route_progress(a.origin, a.destination, a.lat, a.lon, pos)
        if frac is None:
            frac = 0.5
        dx = int(round(lx0 + 2 + frac * (lx1 - 6 - lx0 - 2)))
        frame.draw.ellipse([dx - 2, ly - 2, dx + 2, ly + 2], fill=WHITE)

        ys = (33, 42, 51)
        alt = "ALT  ---" if a.altitude is None else f"ALT  {a.altitude:,} FT"
        spd = "SPD  ---" if a.speed is None else f"SPD  {a.speed} KTS"
        phase = a.phase
        pc = GREEN if phase == "CLIMBING" else RED if phase == "DESCENDING" else GREY
        frame.text(X0, ys[0], alt, fonts.SMALL, WHITE)
        frame.text(X0, ys[1], spd, fonts.SMALL, WHITE)
        frame.text(X0, ys[2], phase, fonts.SMALL, pc)

        xr = X0 + 84
        if a.track is not None:
            frame.text(xr, ys[0], f"HDG {a.track:03d}", fonts.SMALL, GREY)
        if a.registration:
            frame.text(xr, ys[1], f"REG {a.registration}"[:10], fonts.SMALL, GREY)
        frame.text(xr, ys[2], (a.type_code or a.type_name)[:10], fonts.SMALL, GREY)
