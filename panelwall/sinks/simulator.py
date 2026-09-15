"""SimulatorSink: shows frames without hardware.

Two modes, chosen automatically:
  * If pygame is importable and a display is available -> a live window that
    draws each pixel as a round LED dot (looks like the real thing).
  * Otherwise -> writes a PNG to disk every `png_every` frames. Open it in
    any image viewer / VS Code and it refreshes as the file changes.

Install pygame on your Mac for the live window:  pip install pygame
"""

from __future__ import annotations

import os
import time

import numpy as np
from PIL import Image, ImageDraw

from .base import Sink


def led_image(frame: np.ndarray, scale: int = 5, gap: int = 1) -> Image.Image:
    """Upscale a frame into an LED-dot rendering (PIL)."""
    h, w, _ = frame.shape
    out = Image.new("RGB", (w * scale, h * scale), (10, 10, 10))
    d = ImageDraw.Draw(out)
    r = (scale - gap) / 2
    dark = (22, 22, 22)
    for y in range(h):
        row = frame[y]
        for x in range(w):
            c = tuple(int(v) for v in row[x])
            if c == (0, 0, 0):
                c = dark
            cx, cy = x * scale + scale / 2, y * scale + scale / 2
            d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=c)
    return out


class SimulatorSink(Sink):
    def __init__(self, scale: int = 5, png_path: str = "sim.png", png_every: int = 10, window: bool | None = None):
        self.scale = scale
        self.png_path = png_path
        self.png_every = png_every
        self._n = 0
        self._brightness = 1.0
        self._pg = None
        if window is None:
            window = bool(os.environ.get("DISPLAY")) or os.uname().sysname == "Darwin"
        if window:
            try:
                import pygame  # noqa

                self._pg = pygame
            except ImportError:
                self._pg = None
        if self._pg:
            self._init_window()
            print(f"[sim] pygame window, {scale}x scale. Close the window or Ctrl-C to stop.", flush=True)
        else:
            why = "pygame not installed" if window else "window disabled"
            print(f"[sim] {why} -> writing {os.path.abspath(png_path)} every {png_every} frames. "
                  f"Open it in Preview/VS Code; it refreshes as the file changes. Ctrl-C to stop.", flush=True)
            print("[sim] for a live window: pip install pygame", flush=True)

    def _init_window(self):
        pg = self._pg
        pg.init()
        self._screen = None  # created lazily on first frame (we need w/h)
        self._clock = pg.time.Clock()

    def set_brightness(self, level: int) -> None:
        self._brightness = max(0, min(255, level)) / 255.0

    def show(self, frame: np.ndarray) -> None:
        self._n += 1
        if self._brightness < 1.0:
            frame = (frame.astype(np.float32) * self._brightness).astype(np.uint8)
        if self._pg:
            self._show_window(frame)
        elif self._n % self.png_every == 1:
            led_image(frame, self.scale).save(self.png_path)
            if self._n % (self.png_every * 20) == 1:  # a heartbeat every ~10 s at 20 fps
                print(f"[sim] frame {self._n}, wrote {self.png_path}", flush=True)

    def _show_window(self, frame: np.ndarray):
        pg = self._pg
        h, w, _ = frame.shape
        s = self.scale
        if self._screen is None:
            self._screen = pg.display.set_mode((w * s, h * s))
            pg.display.set_caption("panelwall simulator")
            # pre-render the dot mask once: a white disc per LED, alpha elsewhere
            self._dot = pg.Surface((s, s), pg.SRCALPHA)
            pg.draw.circle(self._dot, (255, 255, 255, 255), (s / 2, s / 2), (s - 1) / 2)
        for ev in pg.event.get():
            if ev.type == pg.QUIT:
                raise KeyboardInterrupt
        # fast path: blit a scaled surface, then punch the LED grid over it
        surf = pg.surfarray.make_surface(np.transpose(frame, (1, 0, 2)))
        surf = pg.transform.scale(surf, (w * s, h * s))
        self._screen.fill((10, 10, 10))
        self._screen.blit(surf, (0, 0))
        # grid lines to suggest individual LEDs (cheap approximation of dots)
        grid = (10, 10, 10)
        for x in range(0, w * s, s):
            pg.draw.line(self._screen, grid, (x, 0), (x, h * s))
        for y in range(0, h * s, s):
            pg.draw.line(self._screen, grid, (0, y), (w * s, y))
        pg.display.flip()

    def close(self) -> None:
        if self._pg:
            self._pg.quit()
