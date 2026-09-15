"""ForecastChannel: Open-Meteo weather in two views that alternate every 20 s.

WEEK view (SMALL text at y lights rows y+4..y+8):
  y 4-8    57F CLEAR                                             H72 L52
  7 columns, 36 px each from x=2, faint dividers between them (rows 12-54):
  y 13-17  TODAY / TUE / WED ...       y 19-28 glyph       y 33-37 high (white)
  y 41-45  low (grey)                  y 49-53 precip % in cyan when >= 20
  y 59-63  UPDATED HH:MM (dim, right)

HOURLY view:
  x 0-65   LARGE current temp (rows 2-17) + glyph; FEELS / UV / HUM lines; SET / RISE (24 h)
  x 70-255 12 columns of 15 px starting at the current hour: 2-digit 24 h label (rows 4-8),
           temperature polyline rows 14-46 (dim line, amber points), cyan tick rows 50-51
           where precipitation_probability >= 40, temperature under each column (rows 56-60;
           every other column when any temp has 3 digits).

priority(): 3, or 8 for 60 s after the current weather_code changes into precipitation.
"""

from __future__ import annotations

import time
from datetime import datetime

from .. import fonts
from ..config import CONFIG
from ..data.openmeteo import Forecast, ForecastFeed, wmo, compass
from ..framebuffer import Frame, W, AMBER, WHITE, GREY, DIM, CYAN, RED
from ..glyphs import draw_glyph, GLYPH_W
from .base import Channel

VIEWS = ("week", "hourly")
COL_W, COL_X0, N_DAYS = 36, 2, 7
H_X0, H_COL, N_HOURS = 70, 15, 12
DIVIDER = (28, 28, 30)
LINE = (70, 70, 80)


def _t(v: float | None) -> str:
    return "--" if v is None else str(int(round(v)))


class ForecastChannel(Channel):
    name = "forecast"

    def __init__(self, feed: ForecastFeed | None = None, static: dict | None = None, view: str | None = None):
        self.feed = feed or ForecastFeed(static=static)
        self._owns_feed = feed is None
        self.feed.register(self)
        self.t = 0.0
        self.fixed_view = view          # demo --view; None = alternate
        self.view_seconds = CONFIG.forecast.view_seconds

    @property
    def view(self) -> str:
        if self.fixed_view in VIEWS:
            return self.fixed_view
        return VIEWS[int(self.t // self.view_seconds) % len(VIEWS)]

    def status(self) -> dict:
        s = self.feed.status()
        s["view"] = self.view
        return s

    def close(self):
        if self._owns_feed:
            self.feed.close()

    def tick(self, dt: float) -> None:
        self.t += dt

    def priority(self) -> int:
        if self.feed.forecast is None:
            return 0
        return 8 if time.time() < self.feed.alert_until else 3

    # ---- drawing -------------------------------------------------------------
    def render(self, frame: Frame) -> None:
        fc = self.feed.forecast
        if fc is None:
            err = self.feed.last_error
            frame.text_center(W // 2, 24, "NO FORECAST" if err is None else "NO DATA", fonts.MEDIUM, GREY if err is None else RED)
            frame.text_center(W // 2, 38, "LOADING..." if err is None else "CHECK NETWORK", fonts.SMALL, GREY if err is None else RED)
            return
        if self.view == "week":
            self._render_week(frame, fc)
        else:
            self._render_hourly(frame, fc)

    def _render_week(self, frame: Frame, fc: Forecast) -> None:
        now = self.feed.now()
        glyph, word = wmo(fc.code)
        x = 2
        frame.text(x, 0, f"{_t(fc.temp)}F", fonts.SMALL, AMBER)
        x += fonts.width(f"{_t(fc.temp)}F ") + 2
        frame.text(x, 0, word, fonts.SMALL, WHITE)
        today = fc.today()
        if today:
            frame.text_right(W - 2, 0, f"H{_t(today.hi)} L{_t(today.lo)}", fonts.SMALL, GREY)

        for i, day in enumerate(fc.daily[:N_DAYS]):
            x0 = COL_X0 + i * COL_W
            cx = x0 + COL_W // 2
            if i > 0:
                frame.draw.line([(x0 - 1, 12), (x0 - 1, 54)], fill=DIVIDER)
            label = "TODAY" if day.date.date() == now.date() else day.date.strftime("%a").upper()
            frame.text_center(cx, 9, label, fonts.SMALL, AMBER if label == "TODAY" else GREY)
            draw_glyph(frame.draw, wmo(day.code)[0], cx - GLYPH_W // 2, 19)
            frame.text_center(cx, 29, _t(day.hi), fonts.SMALL, WHITE)
            frame.text_center(cx, 37, _t(day.lo), fonts.SMALL, GREY)
            if day.precip is not None and day.precip >= 20:
                frame.text_center(cx, 45, f"{day.precip}%", fonts.SMALL, CYAN)
        if fc.time:
            frame.text_right(W - 2, 55, f"UPDATED {fc.time:%H:%M}", fonts.SMALL, DIM)

    def _render_hourly(self, frame: Frame, fc: Forecast) -> None:
        now = self.feed.now()
        glyph, _ = wmo(fc.code)
        temp = f"{_t(fc.temp)}"
        frame.text(2, 2, temp, fonts.LARGE, WHITE)
        tw = fonts.width(temp, fonts.LARGE)
        if tw + 4 + 24 <= 66:
            draw_glyph(frame.draw, glyph, 2 + tw + 4, 0, scale=2)
        else:
            draw_glyph(frame.draw, glyph, 66 - GLYPH_W - 1, 4)
        rows = (("FEELS", f"{_t(fc.feels)}F"), ("UV", f"{_t(fc.uv)}"), ("HUM", f"{fc.humidity if fc.humidity is not None else '--'}%"))
        for i, (label, val) in enumerate(rows):
            y = 20 + i * 8
            frame.text(2, y, label, fonts.SMALL, GREY)
            frame.text_right(64, y, val, fonts.SMALL, WHITE)
        today = fc.today()
        if today and today.sunset and today.sunrise:
            first, second = (("SET", today.sunset), ("RISE", today.sunrise)) if now < today.sunset else (("RISE", today.sunrise), ("SET", today.sunset))
            for i, (label, t) in enumerate((first, second)):
                y = 46 + i * 8
                frame.text(2, y, label, fonts.SMALL, GREY)
                frame.text_right(64, y, f"{t:%H:%M}", fonts.SMALL, AMBER if label == "SET" else WHITE)

        hours = fc.hours_from(now, N_HOURS)
        if not hours:
            frame.text(H_X0, 26, "NO HOURLY DATA", fonts.SMALL, GREY)
            return
        temps = [h.temp for h in hours if h.temp is not None]
        lo, hi = (min(temps), max(temps)) if temps else (0, 1)
        span = max(hi - lo, 4.0)
        y_top, y_bot = 14, 46
        pts = []
        three_digit = any(t >= 100 or t <= -10 for t in temps)
        for i, h in enumerate(hours):
            x0 = H_X0 + i * H_COL
            cx = x0 + H_COL // 2
            frame.text_center(cx, 0, f"{h.time.hour:02d}", fonts.SMALL, GREY)
            if h.temp is not None:
                y = int(round(y_bot - (h.temp - lo) / span * (y_bot - y_top)))
                pts.append((cx, y))
            if h.precip is not None and h.precip >= 40:
                frame.draw.rectangle([x0 + 3, 50, x0 + H_COL - 4, 51], fill=CYAN)
            if h.temp is not None and (not three_digit or i % 2 == 0):
                frame.text_center(cx, 52, _t(h.temp), fonts.SMALL, WHITE if i == 0 else GREY)
        if len(pts) > 1:
            frame.draw.line(pts, fill=LINE)
        for (x, y) in pts:
            frame.draw.rectangle([x - 1, y - 1, x, y], fill=AMBER)
