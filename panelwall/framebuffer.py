"""The Frame: a 256x64 RGB canvas.

Channels draw onto a Frame with Pillow (text, lines, sprites), and sinks read
its numpy array (H, W, 3) uint8. This is the one data structure the whole
system agrees on.
"""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw

from .config import CONFIG
from . import fonts

W = CONFIG.display.width
H = CONFIG.display.height

# Palette tuned for LEDs: pure saturated colors read best; greys look muddy
# below ~40, so DIM/GREY are kept above that.
AMBER = (255, 176, 0)
WHITE = (235, 235, 235)
GREY = (110, 110, 110)
DIM = (48, 48, 48)
GREEN = (40, 220, 90)
RED = (240, 60, 60)
CYAN = (60, 200, 255)
BLUE = (40, 110, 255)
MAGENTA = (255, 70, 200)
BLACK = (0, 0, 0)


class _TextCache:
    """FreeType rasterization costs ~1.5 ms per string; a frame has dozens.
    Cache the rendered (string, font, color) as a small RGBA tile and paste it.
    Bounded so a scrolling ticker can't grow it without limit."""

    def __init__(self, max_entries: int = 2048):
        self.max = max_entries
        self._d: dict[tuple, Image.Image] = {}

    def get(self, s: str, font, fill) -> Image.Image:
        key = (s, id(font), fill)
        tile = self._d.get(key)
        if tile is None:
            x0, y0, x1, y1 = font.getbbox(s)
            w, h = max(1, x1), max(1, y1)  # bbox is relative to the anchor at (0,0)
            tile = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            ImageDraw.Draw(tile).text((0, 0), s, font=font, fill=fill)
            if len(self._d) >= self.max:
                self._d.pop(next(iter(self._d)))
            self._d[key] = tile
        return tile


_TEXT_CACHE = _TextCache()


class Frame:
    """Thin wrapper over a PIL image sized to the display."""

    def __init__(self):
        self.img = Image.new("RGB", (W, H), BLACK)
        self.draw = ImageDraw.Draw(self.img)

    # ---- drawing helpers -------------------------------------------------
    def text(self, x: int, y: int, s: str, font=None, fill=WHITE, max_w: int | None = None):
        """Draw cached text. `max_w` clips the string to that many pixels (hard clip, no ellipsis)."""
        if not s:
            return
        tile = _TEXT_CACHE.get(s, font or fonts.SMALL, fill)
        if max_w is not None and tile.width > max_w:
            if max_w <= 0:
                return
            tile = tile.crop((0, 0, max_w, tile.height))
        self.img.paste(tile, (int(x), int(y)), tile)

    def text_right(self, x_right: int, y: int, s: str, font=None, fill=WHITE):
        f = font or fonts.SMALL
        self.text(x_right - fonts.width(s, f), y, s, f, fill)

    def text_center(self, cx: int, y: int, s: str, font=None, fill=WHITE):
        f = font or fonts.SMALL
        self.text(cx - fonts.width(s, f) // 2, y, s, f, fill)

    def hline(self, y: int, x0: int = 0, x1: int = W - 1, fill=DIM):
        self.draw.line([(x0, y), (x1, y)], fill=fill)

    def rect(self, box, fill=None, outline=None):
        self.draw.rectangle(box, fill=fill, outline=outline)

    def clear(self):
        self.draw.rectangle([0, 0, W, H], fill=BLACK)

    # ---- output ----------------------------------------------------------
    def to_array(self) -> np.ndarray:
        """(H, W, 3) uint8, RGB."""
        return np.asarray(self.img, dtype=np.uint8)
