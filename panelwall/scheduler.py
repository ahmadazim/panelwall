"""Picks a channel each frame and drives the sink at a fixed FPS.

Rotation policy (in order):
  1. A forced channel (Settings.force_channel, from the phone UI) always wins.
  2. Disabled channels and channels with priority() <= 0 are never shown; if
     the current one drops out, switch immediately.
  3. A channel with STRICTLY higher priority than the current one preempts it
     right away - unless it was itself on screen within the last `min_hold`
     seconds. That cooldown is the anti-flap rule: a channel whose priority
     blinks on/off can't bounce the display more often than every 8 s.
  4. Among channels tied at the top priority, rotate every `rotate_seconds`.
  5. Otherwise stay put.

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
    def _enabled(self) -> list[Channel]:
        s = self.settings
        return [c for c in self.channels if s is None or s.is_enabled(c.name)]

    def pick(self, now: float) -> Channel | None:
        cands = self._enabled()
        if self.settings is not None:
            forced = self.settings.forced()
            if forced in self.by_name and self.by_name[forced] in cands:
                return self.by_name[forced]

        scored = [(c.priority(), c) for c in cands]
        positive = [(p, c) for p, c in scored if p > 0]
        if not positive:
            return None
        top = max(p for p, _ in positive)
        group = [c for p, c in positive if p == top]

        cur = self.current
        cur_p = next((p for p, c in scored if c is cur), 0) if cur is not None else 0
        if cur is None or cur_p <= 0 or cur not in cands:
            return self._first_available(group, now) or group[0]

        if cur in group:
            if len(group) > 1 and now - self.current_since >= self.rotate_seconds:
                return group[(group.index(cur) + 1) % len(group)]
            return cur

        if top > cur_p:  # preempt, subject to the anti-flap cooldown
            cand = self._first_available(group, now)
            return cand if cand is not None else cur
        return cur

    def _first_available(self, group: list[Channel], now: float) -> Channel | None:
        for c in group:
            left = self.last_shown.get(c.name)
            if left is None or now - left >= self.min_hold:
                return c
        return None

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
