"""FlightWallChannel: a faithful replica of TheFlightWall "Widescreen" card.

One aircraft at a time, cycling through the nearest MAX_FLIGHTS every
`cycle_seconds` (5 s default, like the app's "Flight Display Speed"). Layout,
tuned against the product photos (256x64, fonts.FW = X11 6x10: 7 px caps in rows
1-7 of the cell, 6 px advance; 11 px row pitch leaves a dark margin under row 5):

    x 2-29   rows 0-27   airline logo (assets/logos/<ICAO>.png), 'private' for N-numbers
    x 34     row 1 (y 2)  airline full name        -- or the flight number (title="flight")
    x 34     row 2 (y 13) route  "OAK-SEA"
    x 34     row 3 (y 24) aircraft long name       "Boeing 737-700"
    x 0      row 4 (y 35) origin airport name      "Oakland Intl"            (full width)
    x 0      row 5 (y 46) destination name         "Seattle-Tacoma Intl"
    right column, rows 1-4, VALUES right-aligned at x=254, label 6 px left of the value:
             "Alt: 2,700ft"  "Spd: 413kts"  "Trk: 300deg"  "Vr: +640ft/m"
    All white. Long left-hand text is hard-clipped where the right column starts (no ellipsis),
    like the real thing.

Only one airport known: row 4 "Arriving from X" / "Departing to X", row 5 blank.
None known: row 4 shows the registration, row 5 blank.
> MAX_FLIGHTS in range: the nearest five cycle; nothing extra is drawn (the real one shows a
message we have never seen photographed, so the corner stays dark).
No aircraft: "..." centred, or stacked clocks (CONFIG.flightwall.no_flights = "clock").

Data: the shared AircraftFeed (nearest first). The cycle order is kept stable while the
set of nearby aircraft is unchanged; when it changes the current aircraft keeps its slot
if it is still there. Swaps are instant with one black frame between cards.

priority(): 10 with aircraft, 2 otherwise (stays up in dots/clock mode unless something
better is on).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image

from .. import fonts
from ..config import CONFIG
from ..data.adsb import Aircraft
from ..data.aircraft_types import type_long_name
from ..data.airlines import airline_full_name, short_flight
from ..data.airports import display_name
from ..data.feed import AircraftFeed
from ..framebuffer import Frame, W, H, WHITE
from .base import Channel

LOGO_DIR = Path(__file__).resolve().parent.parent.parent / "assets" / "logos"
ROWS = (2, 13, 24, 35, 46)          # 11 px pitch
LOGO_X, LOGO_Y = 2, 0
X_TEXT = 34
X_RIGHT = 254
LABEL_GAP = 6
COL_GAP = 4                      # clearance between left text and the right column
RIGHT_LABELS = ("Alt:", "Spd:", "Trk:", "Vr:")
MAX_FLIGHTS_DEFAULT = 5
_logo_cache: dict[str, Image.Image | None] = {}


# ---- formatters ------------------------------------------------------------------------
def fmt_alt(ft: int | None, units: str = "imperial") -> str:
    if ft is None:
        return "N/A"
    if units == "metric":
        m = ft * 0.3048
        return f"{m / 1000:.1f}km" if m >= 1000 else f"{int(round(m))}m"
    return f"{ft / 1000:.1f}kft" if ft >= 10000 else f"{ft:,}ft"


def fmt_spd(kts: int | None, units: str = "imperial") -> str:
    if kts is None:
        return "N/A"
    return f"{int(round(kts * 1.852))}kph" if units == "metric" else f"{kts}kts"


def fmt_trk(deg: int | None) -> str:
    return "N/A" if deg is None else f"{deg}deg"


def fmt_vr(fpm: int | None, units: str = "imperial") -> str:
    if fpm is None:
        return "N/A"
    if units == "metric":
        v = int(round(fpm * 0.018288))          # ft/min -> km/h, the way the product photo shows it
        return f"{v:+d}kph"
    return f"{fpm:+d}ft/m"


def logo_for(a: Aircraft) -> Image.Image | None:
    cs = a.callsign.upper()
    key = cs[:3] if len(cs) >= 4 and cs[:3].isalpha() and cs[3:4].isdigit() else "private"
    if key != "private" and not (LOGO_DIR / f"{key}.png").exists():
        key = "generic"
    if key not in _logo_cache:
        p = LOGO_DIR / f"{key}.png"
        _logo_cache[key] = Image.open(p).convert("RGBA") if p.exists() else None
    return _logo_cache[key]


def card_rows(a: Aircraft, title: str = "airline") -> tuple[str, str, str, str, str]:
    """The five text rows for one aircraft."""
    airline = airline_full_name(a.callsign)
    flight = short_flight(a.callsign) or a.registration or a.hex.upper()
    if title == "flight":
        row1 = flight
    else:
        row1 = airline or a.registration or flight
    o, d = a.origin, a.destination
    if o and d:
        row2 = f"{o}-{d}"
    elif title == "flight":
        row2 = ""
    else:
        row2 = flight
    row3 = type_long_name(a.type_code) or (a.extra.get("desc") or "").title()
    if o and d:
        row4, row5 = display_name(o), display_name(d)
    elif o:
        row4, row5 = f"Arriving from {display_name(o)}", ""
    elif d:
        row4, row5 = f"Departing to {display_name(d)}", ""
    else:
        row4, row5 = a.registration or a.hex.upper(), ""
    return row1, row2, row3, row4, row5


def right_column(a: Aircraft, units: str) -> list[tuple[str, str]]:
    return [("Alt:", fmt_alt(a.altitude, units)), ("Spd:", fmt_spd(a.speed, units)),
            ("Trk:", fmt_trk(a.track)), ("Vr:", fmt_vr(a.vrate, units))]


# ---- the channel -------------------------------------------------------------------------
class FlightWallChannel(Channel):
    name = "flightwall"

    def __init__(self, feed: AircraftFeed | None = None, static: list[Aircraft] | None = None):
        self.feed = feed or AircraftFeed(static=static)
        self._owns_feed = feed is None
        self.feed.register(self)
        self.cfg = CONFIG.flightwall
        self.t = 0.0
        self.order: list[str] = []          # hex codes, nearest first, stable while the set is unchanged
        self.index = 0
        self._since = 0.0                   # t when the current card appeared
        self._gap = 0                       # black frames to insert before the next card
        self._shown_hex: str | None = None

    @property
    def aircraft(self) -> list[Aircraft]:
        return self.feed.aircraft

    def status(self) -> dict:
        s = self.feed.status()
        s["showing"] = self._shown_hex
        s["cycle"] = f"{self.index + 1}/{len(self.order)}" if self.order else None
        return s

    def close(self):
        if self._owns_feed:
            self.feed.close()

    # ---- cycling -----------------------------------------------------------------
    def _sync_order(self) -> None:
        nearest = [a.hex for a in self.aircraft[: self.cfg.max_flights]]
        if set(nearest) == set(self.order):
            return                           # same aircraft: keep the order and the index
        current = self.order[self.index] if self.order and self.index < len(self.order) else None
        self.order = nearest
        self.index = self.order.index(current) if current in self.order else min(self.index, max(0, len(self.order) - 1))

    def tick(self, dt: float) -> None:
        self.t += dt
        self._sync_order()
        if self.order and self.t - self._since >= self.cfg.cycle_seconds and len(self.order) > 1:
            self.index = (self.index + 1) % len(self.order)
            self._since = self.t
            self._gap = 1

    def current(self) -> Aircraft | None:
        if not self.order:
            return None
        by_hex = {a.hex: a for a in self.aircraft}
        return by_hex.get(self.order[self.index % len(self.order)])

    def priority(self) -> int:
        return 10 if self.aircraft else 2

    # ---- drawing -------------------------------------------------------------------
    def render(self, frame: Frame) -> None:
        a = self.current()
        if a is None:
            self._render_idle(frame)
            self._shown_hex = None
            return
        if self._gap > 0:                    # one black frame so the eye registers the swap
            self._gap -= 1
            return
        if a.hex != self._shown_hex:
            self._since = self.t if self._shown_hex is None else self._since
            self._shown_hex = a.hex
        self._render_card(frame, a)

    def _render_card(self, frame: Frame, a: Aircraft) -> None:
        f = fonts.FW
        logo = logo_for(a)
        if logo is not None:
            frame.img.paste(logo, (LOGO_X, LOGO_Y), logo)
        rows = card_rows(a, self.cfg.title)
        right = right_column(a, self.cfg.units)
        # right column first so the left text knows where to clip
        col_left = W
        for i, (label, value) in enumerate(right):
            vw = fonts.width(value, f)
            frame.text_right(X_RIGHT, ROWS[i], value, f, WHITE)
            lx = X_RIGHT - vw - LABEL_GAP - fonts.width(label, f)
            frame.text(lx, ROWS[i], label, f, WHITE)
            col_left = min(col_left, lx)
        for i, s in enumerate(rows):
            x = X_TEXT if i < 3 else 0
            max_w = (col_left - COL_GAP - x) if i < 4 else (W - x)
            frame.text(x, ROWS[i], s, f, WHITE, max_w=max_w)

    def _render_idle(self, frame: Frame) -> None:
        cfg = self.cfg
        if cfg.no_flights == "clock" and cfg.clocks:
            clocks = list(cfg.clocks)[:3]
            pitch = 11
            y0 = (H - pitch * len(clocks)) // 2
            for i, (label, tz) in enumerate(clocks):
                try:
                    now = datetime.now(ZoneInfo(tz))
                except Exception:      # bad tz name in config: show it rather than crash
                    frame.text_center(W // 2, y0 + i * pitch, f"{label} ??:??", fonts.FW, WHITE)
                    continue
                fmt = "%H:%M" if cfg.hour24 else "%I:%M"
                if cfg.show_seconds:
                    fmt += ":%S"
                s = now.strftime(fmt)
                if not cfg.hour24:
                    s = s.lstrip("0") + now.strftime(" %p")
                frame.text_center(W // 2, y0 + i * pitch, f"{label} {s}", fonts.FW, WHITE)
        else:
            frame.text_center(W // 2, 27, "...", fonts.FW, WHITE)
