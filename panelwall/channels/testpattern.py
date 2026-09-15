"""Test pattern for bring-up: proves panel order, orientation, and color mapping.

Each 64x32 panel gets a colored border and a big number, so when the wall
first lights up you can see instantly whether LEDVision's layout matches
the physical one (a mirrored or swapped panel is obvious). A white pixel
marks the display's (0,0) corner and a moving dot proves frames are updating.
"""

from __future__ import annotations

from .. import fonts
from ..framebuffer import Frame, W, H, WHITE, RED, GREEN, BLUE, AMBER, CYAN, MAGENTA, GREY
from .base import Channel

PANEL_W, PANEL_H = 64, 32
COLORS = [RED, GREEN, BLUE, AMBER, CYAN, MAGENTA, WHITE, GREY]


class TestPatternChannel(Channel):
    name = "testpattern"

    def __init__(self):
        self.t = 0.0

    def tick(self, dt: float) -> None:
        self.t += dt

    def render(self, frame: Frame) -> None:
        n = 0
        for py in range(H // PANEL_H):
            for px in range(W // PANEL_W):
                x0, y0 = px * PANEL_W, py * PANEL_H
                c = COLORS[n % len(COLORS)]
                frame.rect([x0, y0, x0 + PANEL_W - 1, y0 + PANEL_H - 1], outline=c)
                frame.text_center(x0 + PANEL_W // 2, y0 + 8, str(n + 1), fonts.LARGE, c)
                frame.text(x0 + 3, y0 + 3, f"R{py}C{px}", fonts.SMALL, GREY)
                n += 1
        # origin marker + heartbeat
        frame.draw.point((0, 0), fill=WHITE)
        frame.draw.point((1, 0), fill=WHITE)
        frame.draw.point((0, 1), fill=WHITE)
        x = int(self.t * 40) % W
        frame.draw.point((x, H - 1), fill=WHITE)
        # RGB bars along the bottom row of each panel to verify color order
        for px in range(W // PANEL_W):
            x0 = px * PANEL_W
            frame.rect([x0 + 8, H - 4, x0 + 23, H - 3], fill=RED)
            frame.rect([x0 + 24, H - 4, x0 + 39, H - 3], fill=GREEN)
            frame.rect([x0 + 40, H - 4, x0 + 55, H - 3], fill=BLUE)
