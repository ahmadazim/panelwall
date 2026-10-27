"""GreenOverviewChannel: the B, C and D branches on one screen, plus home arrivals and the 65 bus.

Layout (256x64):
  y 0-7    GREEN LINE (MEDIUM)                              B C D OVERVIEW (SMALL grey)
  strips at y = 14, 26, 38 (line 2 px, dots per station, home amber, trains as arrows above
           (eastbound, pointing left) / below (westbound, pointing right)):
           x 2    branch letter    x 10-30 east terminus    x 34-222 line    x 226-254 west terminus
  y 50-54  WASHINGTON ST >BOSTON COLLEGE 3 8 >GOVT CENTER 6 12      (SMALL; B's home)
  y 59-63  BUS 65 >BRIGHTON CTR 4 12  >RUGGLES 7 15

Station labels don't fit on three strips, so only the termini are named; the per-branch
panels (greenb / greenc / greend) have the full labelled strip. Uses the same three
MbtaFeeds as those panels (shared in build_channels), so no extra requests.
priority(): 5.
"""

from __future__ import annotations

from .. import fonts
from ..data.mbta import MbtaFeed, upcoming, short_name, tiny_name
from ..framebuffer import Frame, W, AMBER, WHITE, GREY, DIM, GREEN
from .base import Channel
from .mbta import train_x_in, line_color

STRIP_Y = (14, 26, 38)
X_L, X_R = 34, 222
Y_HOME, Y_BUS = 46, 55


class GreenOverviewChannel(Channel):
    name = "green"

    def __init__(self, feeds: dict[str, MbtaFeed]):
        """feeds: {'greenb': feed, 'greenc': feed, 'greend': feed}"""
        self.feeds = feeds
        for f in feeds.values():
            f.register(self)
        self.t = 0.0

    def status(self) -> dict:
        b = self.feeds.get("greenb")
        s = b.status() if b else {"updated_at": None, "last_error": None}
        s["branches"] = {k: len(f.stops) for k, f in self.feeds.items()}
        return s

    def tick(self, dt: float) -> None:
        self.t += dt

    def priority(self) -> int:
        return 5

    def render(self, frame: Frame) -> None:
        d = frame.draw
        frame.text(2, 0, "GREEN LINE", fonts.MEDIUM, GREEN)
        frame.text_right(W - 2, 0, "B C D", fonts.SMALL, GREY)
        for (key, y) in zip(("greenb", "greenc", "greend"), STRIP_Y):
            feed = self.feeds.get(key)
            letter = key[-1].upper()
            frame.text(2, y - 4, letter, fonts.SMALL, GREEN)
            if feed is None or not feed.stops:
                frame.text(X_L, y - 4, "LOADING..." if not (feed and feed.last_error) else "NO DATA", fonts.SMALL, DIM)
                continue
            stops = feed.stops
            n = len(stops)
            frame.text_right(X_L - 4, y - 4, short_name(stops[0].name, 4)[:3], fonts.SMALL, GREY)
            frame.text(X_R + 4, y - 4, short_name(stops[-1].name, 4)[:3], fonts.SMALL, GREY)
            d.rectangle([X_L, y, X_R, y + 1], fill=line_color(feed.route))
            for i, s in enumerate(stops):
                x = X_L + round(i * (X_R - X_L) / (n - 1)) if n > 1 else X_L
                is_home = s.id == feed.home
                d.rectangle([x - 1, y - 1, x + 1, y + 2], fill=AMBER if is_home else WHITE)
            for v in feed.vehicles:
                x = train_x_in(v, stops, X_L, X_R)
                if x is None:
                    continue
                if v.direction_id == 1:      # eastbound: above, pointing left
                    d.rectangle([x - 1, y - 5, x + 3, y - 3], fill=WHITE)
                    d.polygon([(x - 2, y - 5), (x - 4, y - 4), (x - 2, y - 3)], fill=WHITE)
                else:                        # westbound: below, pointing right
                    d.rectangle([x - 3, y + 4, x + 1, y + 6], fill=WHITE)
                    d.polygon([(x + 2, y + 4), (x + 4, y + 5), (x + 2, y + 6)], fill=WHITE)
        b = self.feeds.get("greenb")
        if b and b.stops:
            now = b.now()
            home = b.home_stop()
            x = 2
            hn = tiny_name(home.name if home else b.home)
            frame.text(x, Y_HOME, hn, fonts.SMALL, AMBER)
            x += fonts.width(hn) + 6
            for direction in (0, 1):
                label = ">" + tiny_name(b.directions[direction] or ("W", "E")[direction])
                mins = upcoming(b.predictions, direction, now, n=2)
                txt = " ".join("NOW" if m == 0 else str(m) for m in mins) if mins else "--"
                frame.text(x, Y_HOME, label, fonts.SMALL, WHITE)
                x += fonts.width(label) + 4
                frame.text(x, Y_HOME, txt, fonts.SMALL, AMBER if mins else DIM)
                x += fonts.width(txt) + 8
            if b.spec.bus_route:
                x = 2
                frame.text(x, Y_BUS, b.spec.bus_label, fonts.SMALL, AMBER)
                x += fonts.width(b.spec.bus_label) + 6
                for direction in (0, 1):
                    label = ">" + tiny_name(b.bus_directions[direction] or ("OUT", "IN")[direction])
                    mins = upcoming(b.bus_predictions, direction, now, n=2)
                    txt = " ".join("NOW" if m == 0 else str(m) for m in mins) if mins else "--"
                    frame.text(x, Y_BUS, label, fonts.SMALL, WHITE)
                    x += fonts.width(label) + 4
                    frame.text(x, Y_BUS, txt, fonts.SMALL, AMBER if mins else DIM)
                    x += fonts.width(txt) + 8
