"""MeadowChannel: a looping, API-free screensaver - an orange tabby and Kuromi in a meadow.

Scene (256x64), back to front:
  sky gradient + sun, three drifting clouds (slow parallax), two layers of rolling hills
  (pre-rendered 512 px wide, scrolled with wrap), a flowered grass strip (y 44-63) with
  ~60 swaying blades, two butterflies on sine paths, the cat, and Kuromi.

The world scrolls while the cat walks (the cat stays near x=96); the layers wrap, so it
loops forever. A small state machine gives the cat a life: walk, stop and sit, tail
flick, look back at Kuromi, walk on. Kuromi hops along a few steps behind, bobbing, and
stops when the cat does. Everything is seeded, so frame N is always the same picture
(tests) and nothing is fetched from anywhere.

Cost: the hills, ground and sprites are rendered once; per frame it is four pastes,
~60 short lines for the grass and a handful of pixels. ~1 ms on the Mac.
priority(): 2 - idle content. Pick it from the phone UI or add it to the auto cycle.
"""

from __future__ import annotations

import math
import random
from functools import lru_cache

from PIL import Image, ImageDraw

from ..framebuffer import Frame, W, H
from .base import Channel

# ---- palette -------------------------------------------------------------------------------------
SKY_TOP, SKY_BOTTOM = (28, 70, 160), (120, 185, 235)
SUN = (255, 225, 120)
CLOUD = (240, 244, 250)
HILL_FAR, HILL_NEAR = (62, 130, 70), (46, 110, 52)
GRASS, GRASS_DARK, GRASS_LIGHT = (52, 140, 48), (36, 105, 36), (96, 190, 70)
FLOWERS = ((255, 90, 120), (255, 220, 60), (240, 240, 255), (200, 120, 255))
ORANGE, ORANGE_DARK, CREAM = (235, 140, 40), (190, 95, 20), (250, 235, 205)
BLACK, WHITE, PINK, GREEN_EYE = (18, 18, 22), (245, 245, 250), (240, 110, 170), (90, 200, 90)

WORLD_W = 512                     # hills/ground tile width; scroll wraps here
HORIZON = 44
CAT_X = 96
WALK_SPEED = 14.0                 # px/s world scroll while walking


# ---- pre-rendered layers --------------------------------------------------------------------------
@lru_cache(maxsize=1)
def sky() -> Image.Image:
    im = Image.new("RGB", (W, H), SKY_BOTTOM)
    d = ImageDraw.Draw(im)
    for y in range(HORIZON):
        t = y / HORIZON
        c = tuple(int(SKY_TOP[i] + (SKY_BOTTOM[i] - SKY_TOP[i]) * t) for i in range(3))
        d.line([(0, y), (W, y)], fill=c)
    d.ellipse([214, 6, 230, 22], fill=SUN)
    return im


@lru_cache(maxsize=1)
def clouds() -> list[Image.Image]:
    out = []
    for w, h in ((34, 10), (26, 8), (42, 12)):
        im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        d.ellipse([0, h // 2 - 1, w * 0.45, h - 1], fill=CLOUD)
        d.ellipse([w * 0.25, 0, w * 0.75, h - 1], fill=CLOUD)
        d.ellipse([w * 0.5, h // 3, w - 1, h - 1], fill=CLOUD)
        out.append(im)
    return out


def _hills(color, base_y: int, amp: int, period: float, seed: int) -> Image.Image:
    im = Image.new("RGBA", (WORLD_W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    rnd = random.Random(seed)
    phase = rnd.random() * math.tau
    pts = [(x, base_y - amp * (0.6 * math.sin(math.tau * x / period + phase) + 0.4 * math.sin(math.tau * x / (period * 0.37) + 1.3)))
           for x in range(WORLD_W + 1)]
    # make the tile seamless: blend the last column into the first
    d.polygon(pts + [(WORLD_W, H), (0, H)], fill=color)
    return im


@lru_cache(maxsize=1)
def hills_far() -> Image.Image:
    return _hills(HILL_FAR, HORIZON - 4, 9, 170.67, 1)      # period divides 512 -> seamless


@lru_cache(maxsize=1)
def hills_near() -> Image.Image:
    return _hills(HILL_NEAR, HORIZON + 2, 6, 128.0, 2)


@lru_cache(maxsize=1)
def ground() -> Image.Image:
    im = Image.new("RGBA", (WORLD_W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rectangle([0, HORIZON, WORLD_W, H], fill=GRASS)
    rnd = random.Random(3)
    for _ in range(140):                                   # texture
        x, y = rnd.randrange(WORLD_W), rnd.randrange(HORIZON + 1, H)
        d.point((x, y), fill=GRASS_DARK if rnd.random() < 0.6 else GRASS_LIGHT)
    for _ in range(26):                                    # flowers: stem + 3-px head
        x, y = rnd.randrange(WORLD_W), rnd.randrange(HORIZON + 6, H - 2)
        c = rnd.choice(FLOWERS)
        d.line([(x, y), (x, y + 3)], fill=GRASS_DARK)
        d.point([(x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)], fill=c)
        d.point((x, y), fill=(255, 240, 160))
    return im


@lru_cache(maxsize=1)
def blades() -> list[tuple[int, int, int, float]]:
    """(world x, base y, height, phase) for the swaying grass blades."""
    rnd = random.Random(4)
    return [(rnd.randrange(WORLD_W), rnd.randrange(HORIZON + 2, H), rnd.randrange(3, 7), rnd.random() * math.tau) for _ in range(90)]


# ---- sprites -------------------------------------------------------------------------------------
@lru_cache(maxsize=16)
def cat_sprite(pose: str, step: int = 0, look_back: bool = False) -> Image.Image:
    """Orange tabby, side view facing right, in a 44x26 box. pose: walk | sit. step 0-3 for the walk cycle."""
    im = Image.new("RGBA", (44, 26), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    gy = 25                                                 # ground line (bottom row)
    if pose == "walk":
        # legs: two pairs alternating; step 0..3 -> phase
        ph = (0, 1, 0, -1)[step % 4]
        for lx, back in ((11, True), (15, True), (26, False), (30, False)):
            dx = ph * (2 if back else -2) * (1 if lx in (11, 26) else -1)
            d.rectangle([lx + dx, 17, lx + dx + 2, gy], fill=ORANGE)
            d.rectangle([lx + dx, gy - 1, lx + dx + 2, gy], fill=CREAM)      # paws
        d.rounded_rectangle([8, 9, 34, 19], radius=5, fill=ORANGE)            # body
        d.rectangle([14, 16, 30, 19], fill=CREAM)                             # belly
        for sx in (14, 19, 24):                                               # tabby stripes
            d.line([(sx, 9), (sx + 1, 13)], fill=ORANGE_DARK)
        # tail: up and curled, with a little sway per step
        tail = [(8, 12), (4, 8), (3, 4 + (step % 2)), (6, 2)]
        d.line(tail, fill=ORANGE, width=2)
        d.point((6, 2), fill=ORANGE_DARK)
        hx = 30                                                               # head at the front
        hy = 5
    else:                                                                     # sit
        d.polygon([(10, 25), (12, 10), (30, 10), (34, 25)], fill=ORANGE)       # haunches/back
        d.rounded_rectangle([12, 8, 32, 20], radius=5, fill=ORANGE)
        d.rectangle([18, 15, 30, 24], fill=CREAM)                             # chest
        d.rectangle([21, 19, 23, gy], fill=ORANGE)                            # front legs
        d.rectangle([27, 19, 29, gy], fill=ORANGE)
        d.rectangle([21, gy - 1, 23, gy], fill=CREAM)
        d.rectangle([27, gy - 1, 29, gy], fill=CREAM)
        for sx in (16, 21, 26):
            d.line([(sx, 8), (sx + 1, 12)], fill=ORANGE_DARK)
        d.line([(12, 22), (6, 24), (3, 20 - 2 * (step % 2))], fill=ORANGE, width=2)   # tail along the ground, flicking
        hx, hy = 30, 2
    # head (shared): 12x11 with ears, facing right (or back-left when looking back)
    flip = -1 if look_back else 1
    cx = hx + (0 if not look_back else -8)
    d.ellipse([cx - 1, hy, cx + 11, hy + 10], fill=ORANGE)
    d.polygon([(cx, hy + 2), (cx + 1, hy - 3), (cx + 4, hy + 1)], fill=ORANGE)         # ears
    d.polygon([(cx + 7, hy + 1), (cx + 10, hy - 3), (cx + 11, hy + 2)], fill=ORANGE)
    d.point([(cx + 1, hy - 1), (cx + 9, hy - 1)], fill=PINK)
    d.line([(cx + 3, hy + 1), (cx + 3, hy + 3)], fill=ORANGE_DARK)                     # forehead 'M'
    d.line([(cx + 7, hy + 1), (cx + 7, hy + 3)], fill=ORANGE_DARK)
    ex = cx + (7 if flip > 0 else 3)
    d.rectangle([ex - 1, hy + 4, ex, hy + 5], fill=GREEN_EYE)                          # eye
    d.point((ex, hy + 4), fill=BLACK)
    nx = cx + (11 if flip > 0 else -1)
    d.point((nx, hy + 7), fill=PINK)                                                   # nose
    d.line([(nx, hy + 8), (nx - 2 * flip, hy + 9)], fill=ORANGE_DARK)                  # mouth
    for wy in (hy + 6, hy + 8):                                                        # whiskers
        d.line([(nx + 1 * flip, wy), (nx + 5 * flip, wy - (1 if wy == hy + 6 else -1))], fill=CREAM)
    return im


@lru_cache(maxsize=4)
def kuromi_sprite(step: int = 0) -> Image.Image:
    """Kuromi: black jester hood with long ears, pink skull on the front, white face, devil tail. 22x24."""
    im = Image.new("RGBA", (22, 24), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    # ears: long, hanging either side of the hood, tips swing with the hop
    sw = (0, 1, 0, -1)[step % 4]
    d.polygon([(7, 2), (0, 9 + sw), (0, 13 + sw), (3, 13 + sw), (9, 5)], fill=BLACK)      # left ear, out and down
    d.polygon([(14, 2), (21, 9 - sw), (21, 13 - sw), (18, 13 - sw), (12, 5)], fill=BLACK)  # right ear
    d.point([(1, 12 + sw), (20, 12 - sw)], fill=PINK)                                       # ear tips
    # hood
    d.ellipse([4, 0, 17, 13], fill=BLACK)
    d.rectangle([4, 7, 17, 11], fill=BLACK)
    # pink skull on the hood
    d.ellipse([8, 2, 13, 6], fill=PINK)
    d.rectangle([9, 6, 12, 7], fill=PINK)
    d.point([(9, 4), (12, 4)], fill=BLACK)
    # face
    d.ellipse([5, 8, 16, 17], fill=WHITE)
    d.ellipse([7, 11, 9, 14], fill=BLACK)                                 # eyes
    d.ellipse([12, 11, 14, 14], fill=BLACK)
    d.point([(8, 12), (13, 12)], fill=WHITE)
    d.line([(9, 16), (12, 16)], fill=BLACK)                               # mischievous grin
    d.point((9, 16), fill=PINK)
    # body + feet
    d.rounded_rectangle([7, 17, 14, 21], radius=2, fill=WHITE)
    d.rectangle([7, 22, 9, 23], fill=BLACK)
    d.rectangle([12, 22, 14, 23], fill=BLACK)
    # devil tail
    d.line([(14, 20), (18, 19), (20, 21)], fill=BLACK)
    d.polygon([(19, 20), (21, 19), (21, 22)], fill=PINK)
    return im


@lru_cache(maxsize=2)
def butterfly_sprite(open_wings: bool) -> Image.Image:
    im = Image.new("RGBA", (7, 5), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    c = (255, 200, 60)
    if open_wings:
        d.rectangle([0, 1, 2, 3], fill=c)
        d.rectangle([4, 1, 6, 3], fill=c)
    else:
        d.rectangle([2, 0, 2, 4], fill=c)
        d.rectangle([4, 0, 4, 4], fill=c)
    d.line([(3, 0), (3, 4)], fill=BLACK)
    return im


# ---- the channel ----------------------------------------------------------------------------------
class MeadowChannel(Channel):
    name = "meadow"

    def __init__(self, seed: int = 7):
        self.t = 0.0
        self.scroll = 0.0               # world offset in px
        self.rnd = random.Random(seed)
        self.state = "walk"
        self.state_until = 6.0
        self.look_back = False
        self.kuromi_gap = 34.0          # how far behind the cat Kuromi is
        self._frames = 0

    def priority(self) -> int:
        return 2

    def status(self) -> dict:
        return {"updated_at": None, "last_error": None, "state": self.state, "scroll": round(self.scroll, 1)}

    # ---- behaviour -------------------------------------------------------------
    def tick(self, dt: float) -> None:
        dt = min(dt, 0.1)
        self.t += dt
        if self.t >= self.state_until:
            self._next_state()
        if self.state == "walk":
            self.scroll = (self.scroll + WALK_SPEED * dt) % WORLD_W
            # Kuromi lags, then catches up a little while the cat walks
            self.kuromi_gap = min(40.0, self.kuromi_gap + 1.5 * dt)
        else:
            self.kuromi_gap = max(26.0, self.kuromi_gap - 4.0 * dt)   # she catches up when the cat sits

    def _next_state(self) -> None:
        r = self.rnd
        if self.state == "walk":
            self.state, self.look_back = "sit", False
            self.state_until = self.t + r.uniform(3.0, 6.0)
        elif self.state == "sit":
            if r.random() < 0.5 and not self.look_back:
                self.look_back = True                                   # glance back at Kuromi
                self.state_until = self.t + r.uniform(1.5, 3.0)
            else:
                self.state, self.look_back = "walk", False
                self.state_until = self.t + r.uniform(8.0, 16.0)

    # ---- drawing --------------------------------------------------------------
    def render(self, frame: Frame) -> None:
        img = frame.img
        img.paste(sky(), (0, 0))
        for i, c in enumerate(clouds()):                                 # clouds drift on their own, very slowly
            x = int((i * 90 + 20 - self.t * (2.0 + i * 0.6) - self.scroll * 0.05) % (W + c.width)) - c.width
            img.paste(c, (x, 4 + i * 7), c)
        self._paste_wrapped(img, hills_far(), self.scroll * 0.25)
        self._paste_wrapped(img, hills_near(), self.scroll * 0.5)
        self._paste_wrapped(img, ground(), self.scroll)
        d = frame.draw
        off = int(self.scroll)
        for bx, by, h, ph in blades():
            x = (bx - off) % WORLD_W
            if x >= W:
                continue
            sway = round(1.2 * math.sin(self.t * 1.8 + ph))
            d.line([(x, by), (x + sway, by - h)], fill=GRASS_LIGHT if h > 4 else GRASS_DARK)
        for i in range(2):                                               # butterflies
            bxf = (40 + i * 150 + 18 * math.sin(self.t * 0.7 + i) - self.scroll * 0.3) % (W + 20) - 10
            byf = 24 + i * 8 + 5 * math.sin(self.t * 2.3 + i * 2)
            spr = butterfly_sprite(int(self.t * 10 + i) % 2 == 0)
            img.paste(spr, (int(bxf), int(byf)), spr)
        # Kuromi hops behind the cat
        hop = abs(math.sin(self.t * 5.0)) * 3 if self.state == "walk" else 0
        ks = kuromi_sprite(int(self.t * 6) % 4 if self.state == "walk" else 0)
        img.paste(ks, (int(CAT_X - self.kuromi_gap), H - 24 - int(hop)), ks)
        # the cat
        if self.state == "walk":
            cs = cat_sprite("walk", int(self.t * 6) % 4)
        else:
            cs = cat_sprite("sit", int(self.t * 2) % 2, self.look_back)
        img.paste(cs, (CAT_X, H - 26), cs)
        self._frames += 1

    @staticmethod
    def _paste_wrapped(img: Image.Image, layer: Image.Image, offset: float) -> None:
        x0 = int(offset) % WORLD_W
        img.paste(layer, (-x0, 0), layer)
        if x0 + W > WORLD_W:
            img.paste(layer, (WORLD_W - x0, 0), layer)
