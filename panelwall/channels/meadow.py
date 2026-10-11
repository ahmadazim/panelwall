"""MeadowChannel: a looping, API-free screensaver - an orange tabby and Kuromi in a meadow.

Scene (256x64), back to front:
  sky (meadow_sky.py: sun/moon on an east-left to west-right arc from the forecast's
  sunrise/sunset, palette by sun elevation, weather cover/rain/snow/storm/fog), clouds,
  two layers of rolling hills
  (pre-rendered 512 px wide, scrolled with wrap), a flowered grass strip (y 44-63) with
  ~90 swaying blades, two butterflies on sine paths, the cat (60x36) and Kuromi (32x34).
  The palette is muted on purpose: the LEDs are bright, and the characters should pop.

The world scrolls while the cat walks (the cat stays near x=96); the layers wrap, so it
loops forever. A small state machine gives the cat a life: walk, stop and sit, tail
flick, look back at Kuromi, walk on. Kuromi hops along a few steps behind, bobbing, and
stops when the cat does. Everything is seeded, so frame N is always the same picture
(tests) and nothing is fetched from anywhere.

Weather and daylight come from the SHARED ForecastFeed (the same one the forecast panel
uses, so no extra requests); without it the sky falls back to clear with sunrise 06:30 /
sunset 18:30. Hills, ground and sprites are tinted for the light level via a small cache.

Cost: ~0.3 ms per frame on the Mac. priority(): 2 - idle content.
"""

from __future__ import annotations

import math
import random
from functools import lru_cache

from PIL import Image, ImageDraw

from datetime import datetime
from zoneinfo import ZoneInfo

from PIL import ImageEnhance

from ..config import CONFIG
from ..data.openmeteo import ForecastFeed, wmo
from ..framebuffer import Frame, W, H
from .base import Channel
from .meadow_sky import SceneState, scene_state, draw_sky, draw_clouds, draw_precip, draw_fog, lightning, WEATHERS

# ---- palette (deliberately muted: the wall is bright, and the characters should carry the scene) ----
SKY_TOP, SKY_BOTTOM = (16, 40, 95), (70, 108, 140)
SUN = (205, 180, 95)
CLOUD = (165, 170, 178)
HILL_FAR, HILL_NEAR = (38, 82, 44), (28, 68, 32)
GRASS, GRASS_DARK, GRASS_LIGHT = (32, 88, 30), (22, 62, 22), (58, 118, 44)
FLOWERS = ((190, 70, 95), (195, 165, 45), (175, 175, 190), (145, 90, 190))
ORANGE, ORANGE_DARK, CREAM = (225, 130, 35), (175, 85, 18), (225, 210, 180)
BLACK, WHITE, PINK, GREEN_EYE = (14, 14, 18), (215, 215, 222), (220, 95, 155), (80, 180, 80)

WORLD_W = 512                     # hills/ground tile width; scroll wraps here
HORIZON = 44
CAT_X = 110
WALK_SPEED = 14.0                 # px/s world scroll while walking


# ---- pre-rendered layers --------------------------------------------------------------------------
@lru_cache(maxsize=48)
def tinted(layer_name: str, light_q: int) -> Image.Image:
    """A pre-rendered layer darkened for the light level (quantised to 1/20)."""
    layer = {"far": hills_far, "near": hills_near, "ground": ground}[layer_name]()
    f = light_q / 20.0
    if f >= 0.99:
        return layer
    rgb = ImageEnhance.Brightness(layer.convert("RGB")).enhance(f)
    out = rgb.convert("RGBA")
    out.putalpha(layer.getchannel("A"))
    return out


@lru_cache(maxsize=64)
def tinted_sprite(key: tuple, light_q: int) -> Image.Image:
    spr = cat_sprite(*key[1:]) if key[0] == "cat" else kuromi_sprite(key[1])
    f = light_q / 20.0
    if f >= 0.99:
        return spr
    rgb = ImageEnhance.Brightness(spr.convert("RGB")).enhance(f)
    out = rgb.convert("RGBA")
    out.putalpha(spr.getchannel("A"))
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


# ---- sprites (hand-placed at 60x36 / 32x34 so edges stay crisp) ------------------------------------
CAT_W, CAT_H = 60, 36
KUROMI_W, KUROMI_H = 32, 34


def _cat_head(d: ImageDraw.ImageDraw, cx: int, hy: int, look_back: bool) -> None:
    """17x16 head with ears, facing right; mirrored features when looking back over the shoulder."""
    flip = -1 if look_back else 1
    d.ellipse([cx, hy + 2, cx + 16, hy + 16], fill=ORANGE)
    d.polygon([(cx + 1, hy + 5), (cx + 2, hy - 2), (cx + 7, hy + 3)], fill=ORANGE)          # ears
    d.polygon([(cx + 9, hy + 3), (cx + 14, hy - 2), (cx + 15, hy + 5)], fill=ORANGE)
    d.polygon([(cx + 2, hy + 4), (cx + 3, hy), (cx + 5, hy + 3)], fill=PINK)                 # inner ears
    d.polygon([(cx + 11, hy + 3), (cx + 13, hy), (cx + 14, hy + 4)], fill=PINK)
    for sx in (cx + 5, cx + 8, cx + 11):                                                     # forehead 'M'
        d.line([(sx, hy + 3), (sx, hy + 6)], fill=ORANGE_DARK)
    ex = cx + (11 if flip > 0 else 3)
    d.rectangle([ex - 1, hy + 7, ex + 1, hy + 9], fill=GREEN_EYE)                            # eye
    d.rectangle([ex, hy + 7, ex, hy + 9], fill=BLACK)
    nx = cx + (16 if flip > 0 else 0)
    d.rectangle([nx - 1, hy + 11, nx, hy + 11], fill=PINK)                                   # nose
    d.line([(nx, hy + 12), (nx - 2 * flip, hy + 13)], fill=ORANGE_DARK)                      # mouth
    for i, wy in enumerate((hy + 10, hy + 12, hy + 14)):                                      # whiskers
        d.line([(nx + 1 * flip, wy), (nx + 7 * flip, wy + (i - 1) * 2)], fill=CREAM)


@lru_cache(maxsize=16)
def cat_sprite(pose: str, step: int = 0, look_back: bool = False) -> Image.Image:
    """Orange tabby, side view facing right, in a 60x36 box. pose: walk | sit. step 0-3 for the walk cycle."""
    im = Image.new("RGBA", (CAT_W, CAT_H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    gy = CAT_H - 1
    if pose == "walk":
        ph = (0, 1, 0, -1)[step % 4]
        for lx, back, sign in ((13, True, 1), (20, True, -1), (34, False, -1), (41, False, 1)):
            dx = ph * 3 * sign
            d.rectangle([lx + dx, 24, lx + dx + 3, gy], fill=ORANGE)
            d.rectangle([lx + dx, gy - 2, lx + dx + 3, gy], fill=CREAM)                     # paws
        d.rounded_rectangle([10, 12, 48, 27], radius=7, fill=ORANGE)                        # body
        d.rectangle([18, 22, 42, 27], fill=CREAM)                                           # belly
        for sx in (18, 24, 30, 36):                                                         # tabby stripes
            d.line([(sx, 12), (sx + 2, 18)], fill=ORANGE_DARK, width=2)
        tail = [(11, 18), (5, 12), (3, 6 + (step % 2)), (8, 1)]                              # tail up, swaying
        d.line(tail, fill=ORANGE, width=3)
        d.rectangle([7, 1, 9, 3], fill=ORANGE_DARK)
        _cat_head(d, 41, 3, False)
    else:
        d.polygon([(12, gy), (15, 16), (42, 16), (48, gy)], fill=ORANGE)                     # haunches / back
        d.rounded_rectangle([15, 12, 46, 30], radius=7, fill=ORANGE)
        d.rectangle([31, 21, 41, 29], fill=CREAM)                                           # chest bib
        for lx in (29, 40):                                                                 # front legs, orange, paws cream
            d.rectangle([lx, 26, lx + 3, gy], fill=ORANGE)
            d.rectangle([lx, gy - 2, lx + 3, gy], fill=CREAM)
        d.rectangle([33, 30, 39, gy], fill=ORANGE_DARK)                                     # shadow between the legs
        for sx in (20, 26, 32):
            d.line([(sx, 12), (sx + 2, 18)], fill=ORANGE_DARK, width=2)
        d.line([(14, 32), (7, 34), (3, 28 - 3 * (step % 2))], fill=ORANGE, width=3)         # tail along the ground
        _cat_head(d, 41 - (11 if look_back else 0), 0, look_back)
    return im


@lru_cache(maxsize=4)
def kuromi_sprite(step: int = 0) -> Image.Image:
    """Kuromi: black jester hood with long ears, pink skull, white face, devil tail. 32x34, feet on the bottom row."""
    im = Image.new("RGBA", (KUROMI_W, KUROMI_H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    sw = (0, 1, 0, -1)[step % 4]
    # ears: out and down from the hood, tips swinging with the hop
    # ears rise from the hood, flare out, then droop; tips swing with the hop
    d.polygon([(11, 6), (6, 0), (1, 3), (0, 12 + sw), (4, 17 + sw), (7, 12 + sw), (13, 9)], fill=BLACK)
    d.polygon([(20, 6), (25, 0), (30, 3), (31, 12 - sw), (27, 17 - sw), (24, 12 - sw), (18, 9)], fill=BLACK)
    d.rectangle([2, 14 + sw, 3, 15 + sw], fill=PINK)                                        # ear tips
    d.rectangle([28, 14 - sw, 29, 15 - sw], fill=PINK)
    # hood
    d.ellipse([6, 0, 25, 19], fill=BLACK)
    d.rectangle([6, 10, 25, 16], fill=BLACK)
    # pink skull on the hood
    d.ellipse([11, 2, 20, 9], fill=PINK)
    d.rectangle([13, 9, 18, 10], fill=PINK)
    d.rectangle([13, 5, 14, 6], fill=BLACK)
    d.rectangle([17, 5, 18, 6], fill=BLACK)
    # face
    d.ellipse([8, 11, 23, 25], fill=WHITE)
    d.ellipse([10, 15, 13, 19], fill=BLACK)                                                 # eyes
    d.ellipse([18, 15, 21, 19], fill=BLACK)
    d.point([(11, 16), (19, 16)], fill=WHITE)
    d.line([(13, 22), (18, 22)], fill=BLACK)                                                # mischievous grin
    d.point((13, 22), fill=PINK)
    d.point((18, 22), fill=PINK)
    # body + feet
    d.rounded_rectangle([10, 24, 21, 30], radius=3, fill=WHITE)
    d.rectangle([10, 31, 13, 33], fill=BLACK)
    d.rectangle([18, 31, 21, 33], fill=BLACK)
    # devil tail
    d.line([(21, 28), (26, 26), (29, 29)], fill=BLACK, width=2)
    d.polygon([(27, 28), (31, 26), (31, 31)], fill=PINK)
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

    def __init__(self, seed: int = 7, forecast: ForecastFeed | None = None,
                 weather: str | None = None, now: datetime | None = None):
        self.t = 0.0
        self.scroll = 0.0               # world offset in px
        self.rnd = random.Random(seed)
        self.state = "walk"
        self.state_until = 6.0
        self.look_back = False
        self.kuromi_gap = 48.0          # how far behind the cat Kuromi is
        self._frames = 0
        self.forecast = forecast
        if forecast is not None:
            forecast.register(self)     # keep the forecast polling while the meadow is on screen
        self.weather_override = weather # demos / tests: force a sky
        self.now_override = now
        self.tz = ZoneInfo(CONFIG.forecast.timezone)

    def priority(self) -> int:
        return 2

    def status(self) -> dict:
        st = self.scene()
        return {"updated_at": None, "last_error": None, "state": self.state, "scroll": round(self.scroll, 1),
                "sky": st.weather, "sun_elevation": round(st.e, 2), "light": st.light}

    # ---- sky -----------------------------------------------------------------------
    def now_local(self) -> datetime:
        return self.now_override or datetime.now(self.tz).replace(tzinfo=None)

    def scene(self) -> SceneState:
        now = self.now_local()
        sunrise = sunset = None
        weather = self.weather_override or "sun"
        fc = self.forecast.forecast if self.forecast is not None else None
        if fc is not None:
            day = next((d for d in fc.daily if d.date.date() == now.date()), fc.today())
            if day is not None:
                sunrise, sunset = day.sunrise, day.sunset
            if self.weather_override is None:
                weather = wmo(fc.code)[0]
        return scene_state(now, sunrise, sunset, weather)

    # ---- behaviour -------------------------------------------------------------
    def tick(self, dt: float) -> None:
        dt = min(dt, 0.1)
        self.t += dt
        if self.t >= self.state_until:
            self._next_state()
        if self.state == "walk":
            self.scroll = (self.scroll + WALK_SPEED * dt) % WORLD_W
            # Kuromi lags, then catches up a little while the cat walks
            self.kuromi_gap = min(56.0, self.kuromi_gap + 1.5 * dt)
        else:
            self.kuromi_gap = max(38.0, self.kuromi_gap - 5.0 * dt)   # she catches up when the cat sits

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
        img, d = frame.img, frame.draw
        st = self.scene()
        lq = int(round(st.light * 20))
        draw_sky(img, d, st, self.t)
        self._paste_wrapped(img, tinted("far", lq), self.scroll * 0.25)
        self._paste_wrapped(img, tinted("near", lq), self.scroll * 0.5)
        draw_clouds(img, st, self.t, self.scroll)                        # clouds sit in front of the far hills
        self._paste_wrapped(img, tinted("ground", lq), self.scroll)
        off = int(self.scroll)
        gl = tuple(int(c * st.light) for c in GRASS_LIGHT)
        gd = tuple(int(c * st.light) for c in GRASS_DARK)
        for bx, by, h, ph in blades():
            x = (bx - off) % WORLD_W
            if x >= W:
                continue
            sway = round(1.2 * math.sin(self.t * 1.8 + ph))
            d.line([(x, by), (x + sway, by - h)], fill=gl if h > 4 else gd)
        if not st.night and st.weather in ("sun", "partly"):             # butterflies only in fair daylight
            for i in range(2):
                bxf = (40 + i * 150 + 18 * math.sin(self.t * 0.7 + i) - self.scroll * 0.3) % (W + 20) - 10
                byf = 24 + i * 8 + 5 * math.sin(self.t * 2.3 + i * 2)
                spr = butterfly_sprite(int(self.t * 10 + i) % 2 == 0)
                img.paste(spr, (int(bxf), int(byf)), spr)
        # characters: a little dimmer at night, never below 60% so they stay readable
        cq = int(round(max(0.6, 0.4 + 0.6 * st.light) * 20))
        hop = abs(math.sin(self.t * 5.0)) * 4 if self.state == "walk" else 0
        ks = tinted_sprite(("kuromi", int(self.t * 6) % 4 if self.state == "walk" else 0), cq)
        img.paste(ks, (int(CAT_X - self.kuromi_gap), H - KUROMI_H - int(hop)), ks)
        if self.state == "walk":
            cs = tinted_sprite(("cat", "walk", int(self.t * 6) % 4, False), cq)
        else:
            cs = tinted_sprite(("cat", "sit", int(self.t * 2) % 2, self.look_back), cq)
        img.paste(cs, (CAT_X, H - CAT_H), cs)
        draw_precip(d, st, self.t)
        if st.weather == "fog":
            draw_fog(img)
        if st.weather == "storm":
            flash = lightning(self.t)
            if flash > 0:
                bolt_x = 60 + int((self.t * 2) % 7) * 25
                d.line([(bolt_x, 0), (bolt_x - 4, 14), (bolt_x + 3, 16), (bolt_x - 2, 34)], fill=(235, 235, 255), width=1)
                frame.img.paste(Image.blend(frame.img, Image.new("RGB", (W, H), (200, 205, 230)), 0.35 * flash), (0, 0))
        self._frames += 1

    @staticmethod
    def _paste_wrapped(img: Image.Image, layer: Image.Image, offset: float) -> None:
        x0 = int(offset) % WORLD_W
        img.paste(layer, (-x0, 0), layer)
        if x0 + W > WORLD_W:
            img.paste(layer, (WORLD_W - x0, 0), layer)
