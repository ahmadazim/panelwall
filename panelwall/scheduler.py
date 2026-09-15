"""Picks a channel each frame and drives the sink at a fixed FPS.

Two policies, chosen by Settings.mode:

  manual (default)  Settings.channel is pinned. Nothing else is shown, whatever the
                    channels' priorities say. A temporary forced channel (/api/show)
                    still wins while it lasts.
  auto              Round-robin over Settings.cycle (None = all), `dwell_seconds` on
                    each, skipping channels whose priority() <= 0 (nothing to show).
                    If Settings.alerts is on, a channel at priority >= ALERT_PRIORITY
                    (a score, a new closest aircraft) interrupts the cycle for as long
                    as it stays that high - but never more often than every `min_hold`
                    seconds (anti-flap), and the interrupted channel's dwell resumes.

Without a Settings object (demos, tests) the scheduler runs the auto policy over
all its channels with the constructor's rotate_seconds and alerts on.

Transitions are a `wipe_seconds` vertical wipe: the new frame slides up from
the bottom over the old one. Done here by compositing two numpy arrays, so
channels never know about it.

Brightness: once a minute (and whenever settings change) the sink is given
Settings.effective_brightness(), which applies the quiet-hours level.
"""

from __future__ import annotations

import time
from datetime import datetime

import numpy as np

from .channels.base import Channel
from .framebuffer import Frame
from .settings import Settings
from .sinks.base import Sink

ALERT_PRIORITY = 20


class Scheduler:
    def __init__(self, channels: list[Channel], sink: Sink, fps: float, settings: Settings | None = None,
                 min_hold: float = 8.0, rotate_seconds: float = 20.0, wipe_seconds: float = 0.3):
        self.channels = channels
        self.by_name = {c.name: c for c in channels}
        self.sink = sink
        self.period = 1.0 / fps
        self.settings = settings
        self.min_hold = min_hold
        self.rotate_seconds = rotate_seconds
        self.wipe_seconds = wipe_seconds
        self.frames = 0
        self.started_at = time.time()
        self.current: Channel | None = None
        self.current_since = 0.0
        self.last_shown: dict[str, float] = {}      # channel name -> monotonic time it left the screen
        self.latest: np.ndarray | None = None        # what the sink last showed (for /preview.png)
        self._old: np.ndarray | None = None          # frame being wiped away
        self._wipe_start = -1.0
        self._bright_rev = -1
        self._bright_minute = -1

    # ---- selection -----------------------------------------------------------
    def _cycle(self) -> list[Channel]:
        s = self.settings
        return [c for c in self.channels if s is None or s.in_cycle(c.name)]

    def pick(self, now: float) -> Channel | None:
        s = self.settings
        if s is not None:
            forced = s.forced()
            if forced in self.by_name:
                return self.by_name[forced]
            if s.mode == "manual":
                return self.by_name.get(s.channel) or (self.channels[0] if self.channels else None)
        return self._pick_auto(now)

    def _pick_auto(self, now: float) -> Channel | None:
        s = self.settings
        cycle = self._cycle()
        dwell = s.dwell_seconds if s is not None else self.rotate_seconds
        alerts = s.alerts if s is not None else True
        cur = self.current

        if alerts:
            hot = [c for c in cycle if c.priority() >= ALERT_PRIORITY]
            if cur in hot:
                return cur
            for c in hot:
                left = self.last_shown.get(c.name)
                if left is None or now - left >= self.min_hold:
                    return c

        showable = [c for c in cycle if c.priority() > 0]
        if not showable:
            return cycle[0] if cycle else None
        if cur in showable and now - self.current_since < dwell:
            return cur
        if cur in cycle:                       # next showable channel after the current one, in list order
            i = cycle.index(cur)
            for k in range(1, len(cycle) + 1):
                c = cycle[(i + k) % len(cycle)]
                if c in showable:
                    return c
        return showable[0]

    # ---- one frame -------------------------------------------------------------
    def step(self, frame: Frame, now: float, dt: float) -> np.ndarray:
        for ch in self.channels:
            ch.tick(dt)
        ch = self.pick(now)
        if ch is not self.current:
            if self.current is not None:
                self.last_shown[self.current.name] = now
            if self.latest is not None and self.wipe_seconds > 0:
                self._old, self._wipe_start = self.latest, now
            self.current, self.current_since = ch, now
        frame.clear()
        if ch is not None:
            ch.render(frame)
        out = frame.to_array()
        if self._old is not None:
            p = (now - self._wipe_start) / self.wipe_seconds
            if p >= 1.0:
                self._old = None
            else:
                out = wipe_up(self._old, out, p)
        self._apply_brightness()
        self.latest = out
        return out

    def _apply_brightness(self) -> None:
        s = self.settings
        if s is None:
            return
        minute = datetime.now().minute
        if s.revision != self._bright_rev or minute != self._bright_minute:
            self._bright_rev, self._bright_minute = s.revision, minute
            self.sink.set_brightness(s.effective_brightness())

    @property
    def current_name(self) -> str | None:
        return self.current.name if self.current else None

    # ---- loop --------------------------------------------------------------------
    def run(self, duration: float | None = None) -> None:
        frame = Frame()
        t_prev = time.perf_counter()
        t_end = None if duration is None else t_prev + duration
        try:
            while t_end is None or time.perf_counter() < t_end:
                t0 = time.perf_counter()
                dt, t_prev = t0 - t_prev, t0
                self.sink.show(self.step(frame, t0, dt))
                self.frames += 1
                sleep = self.period - (time.perf_counter() - t0)
                if sleep > 0:
                    time.sleep(sleep)
        except KeyboardInterrupt:
            pass
        finally:
            for ch in self.channels:
                ch.close()
            self.sink.close()


def wipe_up(old: np.ndarray, new: np.ndarray, progress: float) -> np.ndarray:
    """New frame slides in from the bottom over the old one. progress 0..1."""
    h = old.shape[0]
    offset = int(round(h * (1.0 - max(0.0, min(1.0, progress)))))
    if offset <= 0:
        return new
    if offset >= h:
        return old
    out = old.copy()
    out[offset:] = new[: h - offset]
    return out
