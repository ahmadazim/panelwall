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
from ..config import CONFIG, LineSpec, MBTA_LINES
from ..data.mbta import MbtaFeed, Stop, Vehicle, upcoming, short_name, tiny_name
from ..framebuffer import Frame, W, AMBER, WHITE, GREY, DIM, RED, GREEN
from .base import Channel

X_LEFT, X_RIGHT = 6, W - 6
Y_LINE = 22
Y_LABEL_TOP, Y_LABEL_BOT = 7, 26
Y_TRAIN_N, Y_TRAIN_S = 17, 26
Y_ARR0, Y_ARR1 = 40, 51                 # two arrival rows (no bus)
Y_ARR_BUS = (37, 46, 55)                # three rows when a bus row is configured (text rows 41-45, 50-54, 59-63)

LINE_COLORS = {"Red": RED, "Orange": (255, 140, 0), "Blue": (40, 110, 255), "Green": GREEN}


def line_color(route: str):
    return LINE_COLORS.get(route.split("-")[0], WHITE)


def label_rows(stops: list[Stop], home: str, x_left: int = X_LEFT, x_right: int = X_RIGHT) -> dict[int, str]:
    """Which stations get a label and on which row ('top' | 'bottom').

    Two alternating rows need ~25 px between same-row labels (3-letter labels are ~19 px wide).
    When a line is denser than that (Green B: 23 stops, D: 25) only every 4th stop is labelled
    per row; Red (18) and Green C (20) still label every stop. The home station is
    always labelled, and any label on its row within 20 px of it is dropped."""
    n = len(stops)
    spacing = (x_right - x_left) / max(1, n - 1)
    step = 2 if 2 * spacing >= 25 else 4
    rows = {}
    for i in range(n):
        if i % step == 0:
            rows[i] = "top"
        elif i % step == step // 2:
            rows[i] = "bottom"
    hi = next((i for i, s in enumerate(stops) if s.id == home), None)
    if hi is not None:
        rows[hi] = "top" if hi % 2 == 0 else "bottom"
        hx = station_x(hi, n, x_left, x_right)
        for i in list(rows):
            if i != hi and rows[i] == rows[hi] and abs(station_x(i, n, x_left, x_right) - hx) < 20:
                del rows[i]
    return rows


def station_x(i: int, n: int, x_left: int = X_LEFT, x_right: int = X_RIGHT) -> int:
    if n <= 1:
        return (x_left + x_right) // 2
    return x_left + round(i * (x_right - x_left) / (n - 1))


def train_x_in(v: Vehicle, stops: list[Stop], x_left: int, x_right: int) -> int | None:
    """Pixel x for a train on a strip spanning x_left..x_right, or None if its stop isn't drawn."""
    idx = {s.id: i for i, s in enumerate(stops)}
    i = idx.get(v.stop_id)
    if i is None:
        return None
    n = len(stops)
    x_here = station_x(i, n, x_left, x_right)
    if v.status == "STOPPED_AT":
        return x_here
    # heading to stop i: came from i-1 (direction 0 runs left->right) or i+1 (direction 1)
    prev = i - 1 if v.direction_id == 0 else i + 1
    if not 0 <= prev < n:
        return x_here
    frac = 0.85 if v.status == "INCOMING_AT" else 0.5
    return round(station_x(prev, n, x_left, x_right) + frac * (x_here - station_x(prev, n, x_left, x_right)))


def train_x(v: Vehicle, stops: list[Stop]) -> int | None:
    return train_x_in(v, stops, X_LEFT, X_RIGHT)


class MbtaChannel(Channel):
    """One LineSpec (Red / Green-B / Green-C / Green-D ...). `name` is the spec's name."""

    name = "mbta"

    def __init__(self, feed: MbtaFeed | None = None, static: dict | None = None, spec: LineSpec | None = None):
        self.spec = spec or (feed.spec if feed is not None else MBTA_LINES["mbta"])
        self.name = self.spec.name
        self.feed = feed or MbtaFeed(static=static, spec=self.spec)
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
        color = line_color(self.spec.route)
        frame.text(2, 0, self.spec.title, fonts.MEDIUM, color)
        stops = self.feed.stops
        if stops:
            ends = f"{short_name(stops[0].name, 14)} - {short_name(stops[-1].name, 14)}"
            frame.text_right(W - 2, 0, ends, fonts.SMALL, GREY, max_w=W - 2 - fonts.width(self.spec.title, fonts.MEDIUM) - 6)

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
        home = self.spec.home_stop
        rows = label_rows(stops, home)
        for i, s in enumerate(stops):
            x = station_x(i, n)
            is_home = s.id == home
            d.rectangle([x - 1, Y_LINE - 1, x + 1, Y_LINE + 2], fill=AMBER if is_home else WHITE)
            if i not in rows:
                continue
            y = Y_LABEL_TOP if rows[i] == "top" else Y_LABEL_BOT
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

    def _direction_names(self) -> tuple[str, str]:
        d0, d1 = self.feed.directions
        if self.spec.name == "mbta" and not d0:
            return CONFIG.mbta.direction_names
        return short_name(d0 or "OUTBOUND"), short_name(d1 or "INBOUND")

    def _render_arrivals(self, frame: Frame, stops: list[Stop]) -> None:
        home = self.feed.home_stop()
        home_name = short_name(home.name if home else self.spec.home_stop, 13)
        now = self.feed.now()
        names = self._direction_names()
        has_bus = bool(self.spec.bus_route)
        ys = Y_ARR_BUS if has_bus else (Y_ARR0, Y_ARR1)
        for direction, y in ((0, ys[0]), (1, ys[1])):
            frame.text(2, y, f"{home_name} >{names[direction]}", fonts.SMALL, WHITE, max_w=W - 2 - 66 - 4)
            mins = upcoming(self.feed.predictions, direction, now)
            if mins:
                txt = "  ".join("NOW" if m == 0 else str(m) for m in mins) + " MIN"
                frame.text_right(W - 2, y, txt, fonts.SMALL, AMBER)
            else:
                frame.text_right(W - 2, y, "--", fonts.SMALL, DIM)
        if has_bus:
            self._render_bus_row(frame, ys[2], now)

    def _render_bus_row(self, frame: Frame, y: int, now) -> None:
        """'BUS 65 >BRIGHTON CTR 4 12  >RUGGLES 7 15' - both directions on one row."""
        bd = self.feed.bus_directions
        x = 2
        frame.text(x, y, self.spec.bus_label, fonts.SMALL, AMBER)
        x += fonts.width(self.spec.bus_label) + 6
        for direction in (0, 1):
            label = ">" + tiny_name(bd[direction] or ("OUT", "IN")[direction])
            mins = upcoming(self.feed.bus_predictions, direction, now, n=2)
            txt = " ".join("NOW" if m == 0 else str(m) for m in mins) if mins else "--"
            frame.text(x, y, label, fonts.SMALL, WHITE)
            x += fonts.width(label) + 4
            frame.text(x, y, txt, fonts.SMALL, AMBER if mins else DIM)
            x += fonts.width(txt) + 8
