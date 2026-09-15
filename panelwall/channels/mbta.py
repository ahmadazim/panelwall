"""MbtaChannel: one MBTA line as a horizontal strip, with next trains at home.

Layout (256x64, SMALL text lights rows y+4..y+8):
  y 0-7    RED LINE (MEDIUM, line color)            ALEWIFE - BRAINTREE (SMALL grey, right)
  y 11-15  station labels, even stations
  y 17-19  northbound trains (arrow pointing left)
  y 21-24  the line (2 px) with a dot per station; home station amber
  y 26-28  southbound trains (arrow pointing right)
  y 30-34  station labels, odd stations
  y 44-48  HOME >DIR0                                       m  m  m MIN (amber)
  y 55-59  HOME >DIR1                                       m  m MIN

Stations are spaced evenly across x 6..250. Trains sit at their stop when
STOPPED_AT, otherwise part-way between the previous stop and the one they are
heading to. Data comes from data.mbta.MbtaFeed (background thread).
priority(): 5 - idle/background content.
"""

from __future__ import annotations

from .. import fonts
from ..config import CONFIG
from ..data.mbta import MbtaFeed, Stop, Vehicle, upcoming
from ..framebuffer import Frame, W, AMBER, WHITE, GREY, DIM, RED
from .base import Channel

X_LEFT, X_RIGHT = 6, W - 6
Y_LINE = 22
Y_LABEL_TOP, Y_LABEL_BOT = 7, 26
Y_TRAIN_N, Y_TRAIN_S = 17, 26
Y_ARR0, Y_ARR1 = 40, 51

LINE_COLORS = {"Red": RED, "Orange": (255, 140, 0), "Blue": (40, 110, 255), "Green": (40, 220, 90)}


def station_x(i: int, n: int) -> int:
    if n <= 1:
        return (X_LEFT + X_RIGHT) // 2
    return X_LEFT + round(i * (X_RIGHT - X_LEFT) / (n - 1))


def train_x(v: Vehicle, stops: list[Stop]) -> int | None:
    """Pixel x for a train, or None if its stop isn't on the drawn branch."""
    idx = {s.id: i for i, s in enumerate(stops)}
    i = idx.get(v.stop_id)
    if i is None:
        return None
    n = len(stops)
    x_here = station_x(i, n)
    if v.status == "STOPPED_AT":
        return x_here
    # heading to stop i: came from i-1 (southbound, dir 0) or i+1 (northbound, dir 1)
    prev = i - 1 if v.direction_id == 0 else i + 1
    if not 0 <= prev < n:
        return x_here
    frac = 0.85 if v.status == "INCOMING_AT" else 0.5
    return round(station_x(prev, n) + frac * (x_here - station_x(prev, n)))


class MbtaChannel(Channel):
    name = "mbta"

    def __init__(self, feed: MbtaFeed | None = None, static: dict | None = None):
        self.feed = feed or MbtaFeed(static=static)
        self._owns_feed = feed is None
        self.feed.register(self)
        self.t = 0.0

    def status(self) -> dict:
        return self.feed.status()

    def close(self):
        if self._owns_feed:
            self.feed.close()

    def tick(self, dt: float) -> None:
        self.t += dt

    def priority(self) -> int:
        return 5

    # ---- drawing -------------------------------------------------------------
    def render(self, frame: Frame) -> None:
        cfg = CONFIG.mbta
        color = LINE_COLORS.get(cfg.route, WHITE)
        frame.text(2, 0, f"{cfg.route.upper()} LINE", fonts.MEDIUM, color)
        stops = self.feed.stops
        if stops:
            frame.text_right(W - 2, 0, f"{stops[0].name.upper()} - {stops[-1].name.upper()}"[:22], fonts.SMALL, GREY)

        if not stops:
            err = self.feed.last_error
            msg = "NO DATA - CHECK NETWORK" if err else "LOADING..."
            frame.text_center(W // 2, 24, msg, fonts.MEDIUM, RED if err else GREY)
            return

        self._render_strip(frame, stops, color)
        self._render_arrivals(frame, stops)

    def _render_strip(self, frame: Frame, stops: list[Stop], color) -> None:
        d = frame.draw
        n = len(stops)
        d.rectangle([X_LEFT, Y_LINE, X_RIGHT, Y_LINE + 1], fill=color)
        home = CONFIG.mbta.home_stop
        for i, s in enumerate(stops):
            x = station_x(i, n)
            is_home = s.id == home
            d.rectangle([x - 1, Y_LINE - 1, x + 1, Y_LINE + 2], fill=AMBER if is_home else WHITE)
            y = Y_LABEL_TOP if i % 2 == 0 else Y_LABEL_BOT
            w = fonts.width(s.abbrev)
            frame.text(min(max(1, x - w // 2), W - 1 - w), y, s.abbrev, fonts.SMALL, AMBER if is_home else GREY)
        for v in self.feed.vehicles:
            x = train_x(v, stops)
            if x is None:
                continue
            if v.direction_id == 1:      # northbound: above the line, pointing left
                d.rectangle([x - 1, Y_TRAIN_N, x + 3, Y_TRAIN_N + 2], fill=WHITE)
                d.polygon([(x - 2, Y_TRAIN_N), (x - 4, Y_TRAIN_N + 1), (x - 2, Y_TRAIN_N + 2)], fill=WHITE)
            else:                        # southbound: below the line, pointing right
                d.rectangle([x - 3, Y_TRAIN_S, x + 1, Y_TRAIN_S + 2], fill=WHITE)
                d.polygon([(x + 2, Y_TRAIN_S), (x + 4, Y_TRAIN_S + 1), (x + 2, Y_TRAIN_S + 2)], fill=WHITE)

    def _render_arrivals(self, frame: Frame, stops: list[Stop]) -> None:
        cfg = CONFIG.mbta
        home = next((s for s in stops if s.id == cfg.home_stop), None)
        home_name = (home.name if home else cfg.home_stop).upper()[:12]
        now = self.feed.now()
        for direction, y in ((0, Y_ARR0), (1, Y_ARR1)):
            frame.text(2, y, f"{home_name} >{cfg.direction_names[direction]}", fonts.SMALL, WHITE)
            mins = upcoming(self.feed.predictions, direction, now)
            if mins:
                txt = "  ".join("NOW" if m == 0 else str(m) for m in mins) + " MIN"
                frame.text_right(W - 2, y, txt, fonts.SMALL, AMBER)
            else:
                frame.text_right(W - 2, y, "--", fonts.SMALL, DIM)
