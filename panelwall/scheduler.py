"""Picks a channel each frame and drives the sink at a fixed FPS."""

from __future__ import annotations

import time

from .channels.base import Channel
from .framebuffer import Frame
from .sinks.base import Sink


class Scheduler:
    def __init__(self, channels: list[Channel], sink: Sink, fps: float):
        self.channels = channels
        self.sink = sink
        self.period = 1.0 / fps
        self.frames = 0

    def pick(self) -> Channel | None:
        best, best_p = None, 0
        for ch in self.channels:
            p = ch.priority()
            if p > best_p:
                best, best_p = ch, p
        return best

    def run(self, duration: float | None = None) -> None:
        frame = Frame()
        t_prev = time.perf_counter()
        t_end = None if duration is None else t_prev + duration
        try:
            while t_end is None or time.perf_counter() < t_end:
                t0 = time.perf_counter()
                dt, t_prev = t0 - t_prev, t0
                for ch in self.channels:
                    ch.tick(dt)
                ch = self.pick()
                frame.clear()
                if ch is not None:
                    ch.render(frame)
                self.sink.show(frame.to_array())
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
