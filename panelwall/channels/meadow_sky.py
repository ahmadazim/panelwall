"""Sky, sun/moon, weather for the meadow: what the world above the hills looks like right now.

Inputs: the local time and, when the forecast feed has data, today's sunrise/sunset and the
current WMO weather code. Output: a SceneState the channel renders from.

Geometry: the wall is treated as facing south, so EAST IS ON THE LEFT. The sun rises at the
left edge, arcs over the top (highest at solar noon) and sets at the right edge; the moon does
the same at night. Sun elevation `e` runs -1 (deepest night) .. 0 (on the horizon) .. 1 (noon)
and drives the sky palette through night, dawn, day and dusk keyframes. The glow of a low sun
is concentrated on the sun's side of the sky, so sunrise is warm on the left, sunset on the
right.

Weather adds cloud cover (sky blended toward grey, more and darker clouds, sun hidden),
rain streaks, snow flakes, lightning flashes for storms and a fog wash. Everything is pure
functions of (time, state) so frames are deterministic.

The sky image is cached by a quantised key (elevation to 1/50, sun x to 8 px, cloud cover to
1/10) so it is rebuilt every minute or so, not every frame.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import datetime, time as dtime, timedelta
from functools import lru_cache

import numpy as np
from PIL import Image, ImageDraw

from ..framebuffer import W

HORIZON = 44
WEATHERS = ("sun", "partly", "cloud", "fog", "rain", "snow", "storm")
# cloud cover 0..1 and precipitation kind per glyph name (data/openmeteo.wmo)
_COVER = {"sun": 0.0, "partly": 0.35, "cloud": 0.8, "fog": 0.9, "rain": 0.85, "snow": 0.8, "storm": 0.95}

# sky keyframes on sun elevation e: (top colour, horizon colour)
_KEYS = [
    (-1.00, ((3, 4, 14), (8, 10, 28))),
    (-0.30, ((6, 8, 26), (14, 16, 44))),
    (-0.12, ((12, 14, 48), (60, 36, 70))),        # civil twilight: purple band
    (0.00, ((28, 32, 80), (190, 95, 50))),        # sun on the horizon: orange
    (0.12, ((36, 70, 130), (205, 140, 95))),      # golden hour
    (0.35, ((16, 40, 95), (70, 108, 140))),       # the muted day palette
    (1.00, ((16, 40, 95), (70, 108, 140))),
]
GREY_SKY_TOP, GREY_SKY_BOTTOM = (46, 50, 58), (82, 86, 94)
SUN, MOON = (205, 180, 95), (200, 200, 190)
DEFAULT_SUNRISE, DEFAULT_SUNSET = dtime(6, 30), dtime(18, 30)


@dataclass
class SceneState:
    e: float                 # sun elevation -1..1
    sun_x: float
    sun_y: float
    moon_x: float
    moon_y: float
    weather: str             # one of WEATHERS
    cover: float             # 0..1
    light: float             # ground tint 0.3..1
    night: bool


def _lerp(a, b, t):
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def sky_colors(e: float) -> tuple[tuple, tuple]:
    e = max(-1.0, min(1.0, e))
    for (e0, c0), (e1, c1) in zip(_KEYS, _KEYS[1:]):
        if e0 <= e <= e1:
            t = (e - e0) / (e1 - e0) if e1 > e0 else 0
            return _lerp(c0[0], c1[0], t), _lerp(c0[1], c1[1], t)
    return _KEYS[-1][1]


def scene_state(now: datetime, sunrise: datetime | None, sunset: datetime | None, weather: str) -> SceneState:
    """now, sunrise, sunset are naive local datetimes (Open-Meteo style). weather is a glyph name."""
    d = now.date()
    sr = sunrise or datetime.combine(d, DEFAULT_SUNRISE)
    ss = sunset or datetime.combine(d, DEFAULT_SUNSET)
    if ss <= sr:
        ss = sr + timedelta(hours=12)
    day_len = (ss - sr).total_seconds()
    if sr <= now <= ss:
        f = (now - sr).total_seconds() / day_len                 # 0 at sunrise .. 1 at sunset
        e = math.sin(math.pi * f)
        night = False
        sun_x, sun_y = 14 + f * (W - 28), HORIZON - 12 - 28 * e      # y 32 on the horizon (between the hill tops) .. 4 at noon
        g = 0.0
    else:
        # night: from this sunset to the next sunrise (or previous sunset to this sunrise, before dawn)
        if now > ss:
            n0, n1 = ss, sr + timedelta(days=1)
        else:
            n0, n1 = ss - timedelta(days=1), sr
        g = (now - n0).total_seconds() / max(1.0, (n1 - n0).total_seconds())   # 0 at sunset .. 1 at sunrise
        e = -math.sin(math.pi * g)
        night = True
        # keep the sun just below the horizon on the side it set / will rise, for the twilight glow
        sun_x = (W - 14) if g < 0.5 else 14
        sun_y = HORIZON + 6
    moon_g = g if night else 0.0
    moon_x, moon_y = 14 + moon_g * (W - 28), HORIZON - 12 - 26 * math.sin(math.pi * moon_g)
    weather = weather if weather in WEATHERS else "cloud"
    cover = _COVER[weather]
    light = 0.3 + 0.7 * max(0.0, min(1.0, (e + 0.12) / 0.45))
    light *= 1.0 - 0.35 * cover
    return SceneState(e=e, sun_x=sun_x, sun_y=sun_y, moon_x=moon_x, moon_y=moon_y,
                      weather=weather, cover=cover, light=round(light, 2), night=night)


# ---- sky image ----------------------------------------------------------------------------------
@lru_cache(maxsize=64)
def _sky_image(e_q: int, sun_x_q: int, cover_q: int) -> Image.Image:
    e, sun_x, cover = e_q / 50.0, sun_x_q * 8.0, cover_q / 10.0
    top, bottom = sky_colors(e)
    ys = np.linspace(0.0, 1.0, HORIZON, dtype=np.float32)[:, None, None]
    top_a, bot_a = np.array(top, np.float32), np.array(bottom, np.float32)
    sky = top_a * (1 - ys) + bot_a * ys                                   # (H, 1, 3)
    sky = np.repeat(sky, W, axis=1)
    # low sun: warm glow strongest near the sun's x and near the horizon
    if -0.3 < e < 0.35:
        strength = 1.0 - abs(e - 0.02) / 0.33
        xs = np.arange(W, dtype=np.float32)[None, :, None]
        glow = np.exp(-((xs - sun_x) / 90.0) ** 2) * ys ** 1.5 * strength
        sky = sky * (1 - 0.55 * glow) + np.array((225, 120, 60), np.float32) * 0.55 * glow
    if cover > 0:
        daylight = max(0.0, min(1.0, (e + 0.15) / 0.5))
        gt = np.array(GREY_SKY_TOP, np.float32) * (0.25 + 0.75 * daylight)
        gb = np.array(GREY_SKY_BOTTOM, np.float32) * (0.25 + 0.75 * daylight)
        grey = gt * (1 - ys) + gb * ys
        k = min(0.9, cover)
        sky = sky * (1 - k) + grey * k
    img = Image.fromarray(np.clip(sky, 0, 255).astype(np.uint8), "RGB")
    return img


def sky_image(st: SceneState) -> Image.Image:
    return _sky_image(int(round(st.e * 50)), int(round(st.sun_x / 8)), int(round(st.cover * 10)))


@lru_cache(maxsize=1)
def stars() -> list[tuple[int, int, float]]:
    rnd = random.Random(11)
    return [(rnd.randrange(W), rnd.randrange(2, HORIZON - 8), rnd.random() * math.tau) for _ in range(40)]


def draw_sky(img: Image.Image, d: ImageDraw.ImageDraw, st: SceneState, t: float) -> None:
    """Sky gradient, stars, sun or moon. Clouds and precipitation are drawn by the caller after the hills."""
    img.paste(sky_image(st), (0, 0))
    if st.e < -0.05 and st.cover < 0.7:
        vis = min(1.0, -st.e / 0.5) * (1 - st.cover)
        for sx, sy, ph in stars():
            tw = 0.6 + 0.4 * math.sin(t * 1.3 + ph)
            v = int(90 + 110 * vis * tw)
            d.point((sx, sy), fill=(v, v, v - 10))
    if not st.night and st.cover < 0.7:
        r = 8
        c = SUN if st.e > 0.15 else _lerp((225, 120, 60), SUN, max(0.0, st.e) / 0.15)
        if st.cover > 0.3:                                               # partly cloudy: dimmer disc
            c = _lerp(c, GREY_SKY_BOTTOM, 0.4)
        d.ellipse([st.sun_x - r, st.sun_y - r, st.sun_x + r, st.sun_y + r], fill=c)
    elif st.night and st.cover < 0.7:
        r = 6
        x, y = st.moon_x, st.moon_y
        d.ellipse([x - r, y - r, x + r, y + r], fill=MOON)
        bite = sky_image(st).getpixel((int(min(W - 1, max(0, x + 4))), int(min(HORIZON - 1, max(0, y - 2)))))
        d.ellipse([x - r + 4, y - r - 2, x + r + 4, y + r - 2], fill=bite)                  # crescent bite


@lru_cache(maxsize=8)
def cloud_sprites(shade_q: int) -> list[Image.Image]:
    """Six clouds, light to dark. shade 0 (white) .. 10 (storm grey)."""
    shade = shade_q / 10.0
    col = _lerp((165, 170, 178), (48, 50, 58), shade)
    out = []
    for w, h in ((34, 10), (26, 8), (42, 12), (52, 14), (38, 11), (60, 15)):
        im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        dd = ImageDraw.Draw(im)
        dd.ellipse([0, h // 2 - 1, w * 0.45, h - 1], fill=col)
        dd.ellipse([w * 0.25, 0, w * 0.75, h - 1], fill=col)
        dd.ellipse([w * 0.5, h // 3, w - 1, h - 1], fill=col)
        out.append(im)
    return out


def draw_clouds(img: Image.Image, st: SceneState, t: float, scroll: float) -> None:
    daylight = max(0.0, min(1.0, (st.e + 0.15) / 0.5))
    shade = st.cover * 0.8 + (1 - daylight) * 0.6
    sprites = cloud_sprites(int(round(min(1.0, shade) * 10)))
    n = 2 if st.cover < 0.2 else 3 if st.cover < 0.5 else 6
    for i, c in enumerate(sprites[:n]):
        x = int((i * 70 + 20 - t * (2.0 + i * 0.5) - scroll * 0.05) % (W + c.width)) - c.width
        y = 2 + (i * 5) % 14
        img.paste(c, (x, y), c)


def draw_precip(d: ImageDraw.ImageDraw, st: SceneState, t: float) -> None:
    if st.weather in ("rain", "storm"):
        n = 70 if st.weather == "storm" else 45
        rnd = random.Random(5)
        for i in range(n):
            x0, y0, sp = rnd.randrange(W), rnd.randrange(64), 60 + rnd.randrange(50)
            y = (y0 + t * sp) % 64
            x = (x0 - t * 12) % W
            d.line([(x, y), (x - 1, y + 3)], fill=(120, 140, 170))
    elif st.weather == "snow":
        rnd = random.Random(6)
        for i in range(40):
            x0, y0, sp, ph = rnd.randrange(W), rnd.randrange(64), 6 + rnd.randrange(8), rnd.random() * math.tau
            y = (y0 + t * sp) % 64
            x = (x0 + 4 * math.sin(t * 0.8 + ph)) % W
            d.point((x, y), fill=(210, 215, 225))
    elif st.weather == "fog":
        pass  # handled as an overlay in draw_fog


def lightning(t: float) -> float:
    """0 normally; brief brightness boost during a storm flash (deterministic in t)."""
    cell = int(t * 2)
    rnd = random.Random(cell * 7919)
    if rnd.random() < 0.08:
        phase = (t * 2) % 1.0
        if phase < 0.12:
            return 1.0 - phase / 0.12
    return 0.0


@lru_cache(maxsize=1)
def fog_overlay() -> Image.Image:
    im = Image.new("RGBA", (W, 64), (0, 0, 0, 0))
    px = im.load()
    for y in range(64):
        a = int(150 * max(0.0, min(1.0, (y - 14) / 30.0)))     # thickest low over the meadow
        for x in range(W):
            px[x, y] = (150, 152, 160, a)
    return im


def draw_fog(img: Image.Image) -> None:
    f = fog_overlay()
    img.paste(f, (0, 0), f)
