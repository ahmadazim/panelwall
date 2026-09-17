"""PrayersChannel: today's athan and iqama times, with a countdown to the next one.

Layout (256x64; SMALL text at y lights rows y+4..y+8, MEDIUM rows y..y+7):
  y 4-8    TITLE (page's display name)      ATHAN     IQAMA                 HH:MM
  rows y = 9, 18, 27, 36, 45 (9 px pitch), one per prayer:
           FAJR                 5:27 AM   5:45 AM        right block x >= 172:
           DHUHR               12:55 PM   1:15 PM          y 13-17  NEXT ATHAN IN   (dim)
           ASR                  4:25 PM   4:45 PM          y 17-24  ASR             (MEDIUM, amber)
           MAGHRIB              7:11 PM   7:16 PM          y 27-34  0:45:12         (MEDIUM)
           ISHA                 8:22 PM   8:27 PM          y 42-46  SUNRISE 6:39A   y 50-54  JUMUAH 12:30P
  y 59-63  fiveprayers.org                                              THU SEP 17
  Athan / iqama columns are right-aligned at x=104 / x=160. The next prayer's row is amber,
  prayers already past are grey.

Data: data/prayers.PrayersFeed (page scraped every 6 h, times computed locally per day).
priority(): 20 (alert) from `alert_before_min` before each athan / iqama / Jumu'ah until
`alert_after_min` after it, else 4.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from .. import fonts
from ..config import CONFIG
from ..data.prayers import PrayersFeed, IQAMA_NAMES
from ..framebuffer import Frame, W, AMBER, WHITE, GREY, DIM, RED
from .base import Channel

XR_ATHAN, XR_IQAMA = 104, 160
X_RIGHT = 172
ROW_Y0, ROW_H = 9, 9
ALERT_PRIORITY, IDLE_PRIORITY = 20, 4


def clock12(t: datetime) -> str:
    return t.strftime("%I:%M %p").lstrip("0")


def clock12_short(t: datetime) -> str:
    return t.strftime("%I:%M%p").lstrip("0")[:-1]      # '6:39A'


def hms(delta: timedelta) -> str:
    s = max(0, int(delta.total_seconds()))
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"


class PrayersChannel(Channel):
    name = "prayers"

    def __init__(self, feed: PrayersFeed | None = None, static_html: str | None = None, now: datetime | None = None):
        self.feed = feed or PrayersFeed(static_html=static_html, now=now)
        self._owns_feed = feed is None
        self.feed.register(self)
        self.t = 0.0

    def status(self) -> dict:
        s = self.feed.status()
        nxt = self.feed.upcoming()
        s["next"] = f"{nxt[0]} {nxt[1]} {nxt[2]:%H:%M}" if nxt else None
        return s

    def close(self):
        if self._owns_feed:
            self.feed.close()

    def tick(self, dt: float) -> None:
        self.t += dt

    def priority(self) -> int:
        if self.feed.config is None:
            return 0
        cfg = CONFIG.prayers
        now = self.feed.now()
        today = self.feed.today()
        if today:
            events = [t for n, t in today.athan.items() if n != "Sunrise"] + list(today.iqama.values())
            if today.jumuah and today.day.weekday() == 4:
                events.append(today.jumuah)
            for t in events:
                if t - timedelta(minutes=cfg.alert_before_min) <= now <= t + timedelta(minutes=cfg.alert_after_min):
                    return ALERT_PRIORITY
        return IDLE_PRIORITY

    # ---- drawing -------------------------------------------------------------
    def render(self, frame: Frame) -> None:
        now = self.feed.now()
        cfg = self.feed.config
        title = (cfg.title.upper() if cfg and cfg.title else "PRAYER TIMES")[:14]
        frame.text(2, 0, title, fonts.SMALL, AMBER)
        clock = now.strftime("%H:%M") if int(self.t) % 2 == 0 else now.strftime("%H %M")
        frame.text_right(W - 2, 0, clock, fonts.SMALL, AMBER)
        day = self.feed.today()
        if cfg is None or day is None:
            err = self.feed.last_error
            frame.text_center(W // 2, 24, "NO DATA" if err else "LOADING...", fonts.MEDIUM, RED if err else GREY)
            if err:
                frame.text_center(W // 2, 38, "CHECK NETWORK", fonts.SMALL, RED)
            return

        frame.text_right(XR_ATHAN, 0, "ATHAN", fonts.SMALL, GREY)
        frame.text_right(XR_IQAMA, 0, "IQAMA", fonts.SMALL, GREY)
        nxt = self.feed.upcoming()
        next_name = nxt[0] if nxt and nxt[2].date() == now.date() else None
        for i, name in enumerate(IQAMA_NAMES):
            y = ROW_Y0 + i * ROW_H
            ath = day.athan.get(name)
            iq = day.iqama.get(name)
            passed = iq is not None and iq < now and (ath is None or ath < now)
            col = AMBER if name == next_name else (GREY if passed else WHITE)
            frame.text(2, y, name.upper(), fonts.SMALL, col)
            if ath:
                frame.text_right(XR_ATHAN, y, clock12(ath), fonts.SMALL, col)
            if iq:
                frame.text_right(XR_IQAMA, y, clock12(iq), fonts.SMALL, col)

        if nxt:
            name, kind, when = nxt
            label = "JUMUAH IN" if kind == "JUMUAH" else f"NEXT {kind} IN"
            frame.text(X_RIGHT, 9, label, fonts.SMALL, DIM)
            frame.text(X_RIGHT, 17, name.upper().replace("'", "")[:9], fonts.MEDIUM, AMBER)
            frame.text(X_RIGHT, 27, hms(when - now), fonts.MEDIUM, WHITE)
        sun = day.athan.get("Sunrise")
        if sun:
            frame.text(X_RIGHT, 38, f"SUNRISE {clock12_short(sun)}", fonts.SMALL, GREY)
        if day.jumuah:
            frame.text(X_RIGHT, 46, f"JUMUAH {clock12_short(day.jumuah)}", fonts.SMALL, GREY)
        frame.text(2, 55, "FIVEPRAYERS.ORG", fonts.SMALL, DIM)
        frame.text_right(W - 2, 55, now.strftime("%a %b %d").upper(), fonts.SMALL, DIM)
