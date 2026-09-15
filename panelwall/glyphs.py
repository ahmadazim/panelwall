"""Small pixel glyphs shared by channels and design/mockups2.py.

Weather glyphs are drawn procedurally into a 12x10 box (scale 1) or 24x20
(scale 2) with the top-left at (x, y):

    draw_glyph(draw, "rain", x, y)            # PIL ImageDraw
    draw_glyph(draw, "sun", x, y, scale=2)

Names: sun, cloud, partly, rain, snow, storm, fog.

team_mark(draw, x, y, color, alt) is the 8x8 two-tone team badge: a filled
tile in the primary color with a diagonal corner in the alternate color.
Colors are (r, g, b); hex_color() converts ESPN's "c60c30" strings.
"""

from __future__ import annotations

from PIL import ImageDraw

GLYPH_W, GLYPH_H = 12, 10

SUN = (255, 200, 40)
CLOUD = (190, 190, 200)
CLOUD_DARK = (120, 120, 135)
RAIN = (60, 160, 255)
SNOW = (230, 240, 255)
BOLT = (255, 220, 60)
FOG = (150, 150, 160)

GLYPHS = ("sun", "cloud", "partly", "rain", "snow", "storm", "fog")


def hex_color(s: str | None, default=(120, 120, 120)) -> tuple[int, int, int]:
    s = (s or "").strip().lstrip("#")
    if len(s) != 6:
        return default
    try:
        return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
    except ValueError:
        return default


def _px(d: ImageDraw.ImageDraw, x, y, color, s):
    d.rectangle([x * s, y * s, x * s + s - 1, y * s + s - 1], fill=color)


class _Pen:
    """Draw in glyph-local integer coordinates, scaled by s and offset by (ox, oy)."""

    def __init__(self, d: ImageDraw.ImageDraw, ox: int, oy: int, s: int):
        self.d, self.ox, self.oy, self.s = d, ox, oy, s

    def px(self, x, y, c):
        s = self.s
        self.d.rectangle([self.ox + x * s, self.oy + y * s, self.ox + x * s + s - 1, self.oy + y * s + s - 1], fill=c)

    def rect(self, x0, y0, x1, y1, c):
        s = self.s
        self.d.rectangle([self.ox + x0 * s, self.oy + y0 * s, self.ox + x1 * s + s - 1, self.oy + y1 * s + s - 1], fill=c)

    def hline(self, x0, x1, y, c):
        self.rect(x0, y, x1, y, c)


def _cloud(p: _Pen, x0: int, y0: int, c=CLOUD, w: int = 9):
    """A cloud w px wide, 4 px tall, with its bottom-left at (x0, y0+3)."""
    p.hline(x0 + 1, x0 + w - 2, y0 + 3, c)
    p.hline(x0, x0 + w - 1, y0 + 2, c)
    p.hline(x0 + 1, x0 + w - 3, y0 + 1, c)
    p.hline(x0 + 3, x0 + w - 4, y0, c)


def _sun(p: _Pen, cx: int, cy: int, r: int = 2, c=SUN):
    p.rect(cx - r + 1, cy - r, cx + r - 1, cy + r, c)
    p.rect(cx - r, cy - r + 1, cx + r, cy + r - 1, c)
    for dx, dy in ((0, -r - 2), (0, r + 2), (-r - 2, 0), (r + 2, 0), (-r - 1, -r - 1), (r + 1, -r - 1), (-r - 1, r + 1), (r + 1, r + 1)):
        p.px(cx + dx, cy + dy, c)


def draw_glyph(d: ImageDraw.ImageDraw, name: str, x: int, y: int, scale: int = 1) -> None:
    p = _Pen(d, x, y, scale)
    if name == "sun":
        _sun(p, 6, 5, 2)
    elif name == "cloud":
        _cloud(p, 1, 3, CLOUD, 10)
    elif name == "partly":
        _sun(p, 4, 3, 2)
        _cloud(p, 3, 5, CLOUD, 9)
    elif name == "rain":
        _cloud(p, 1, 0, CLOUD_DARK, 10)
        for i, xx in enumerate((2, 5, 8)):
            p.px(xx, 5 + (i % 2), RAIN)
            p.px(xx - (1 if i % 2 else 0), 7 + (i % 2), RAIN)
        p.px(4, 9, RAIN)
        p.px(7, 8, RAIN)
    elif name == "snow":
        _cloud(p, 1, 0, CLOUD_DARK, 10)
        for xx, yy in ((2, 5), (6, 5), (9, 6), (4, 7), (8, 8), (2, 9), (6, 9)):
            p.px(xx, yy, SNOW)
    elif name == "storm":
        _cloud(p, 1, 0, CLOUD_DARK, 10)
        for xx, yy in ((5, 4), (4, 5), (3, 6), (5, 6), (6, 6), (5, 7), (4, 8), (3, 9)):
            p.px(xx, yy, BOLT)
        p.px(9, 6, RAIN)
        p.px(8, 8, RAIN)
    elif name == "fog":
        for i, yy in enumerate((2, 4, 6, 8)):
            x0 = 1 + (i % 2)
            p.hline(x0, x0 + 9, yy, FOG if i % 2 == 0 else CLOUD_DARK)
    else:
        raise ValueError(f"unknown glyph {name!r}")


def team_mark(d: ImageDraw.ImageDraw, x: int, y: int, color, alt=None, size: int = 8) -> None:
    """8x8 two-tone badge: primary color tile, alternate color in the lower-right triangle.
    A near-black primary gets a grey outline so it doesn't vanish on the LED background."""
    alt = alt or tuple(min(255, c + 90) for c in color)
    d.rectangle([x, y, x + size - 1, y + size - 1], fill=color)
    d.polygon([(x + size - 1, y + 2), (x + size - 1, y + size - 1), (x + 2, y + size - 1)], fill=alt)
    if max(color) < 40:
        d.rectangle([x, y, x + size - 1, y + size - 1], outline=(90, 90, 90))
