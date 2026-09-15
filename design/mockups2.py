"""Round-2 layout mockups, pixel-accurate at 256x64, rendered LED-style.

    python design/mockups2.py        -> design/round2/round2_sheet.png

  1. Boston tonight (sports)           -> built: panelwall/channels/sports.py
  2. Ticker band                        -> DEFERRED (not built)
  3. Spotify now playing                -> DEFERRED (not built)
  4. Spotify queue                      -> DEFERRED (not built)
  5. Forecast - week view               -> built: panelwall/channels/forecast.py
  6. Forecast - hourly view             -> built: panelwall/channels/forecast.py

The weather glyphs and the team badge live in panelwall/glyphs.py so this
script and the channels draw the exact same pixels. The built screens are
rendered here through the real channels with fixture data (so the mockup can
never drift from the implementation); the deferred ones are static sketches.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from panelwall import fonts  # noqa: E402
from panelwall.framebuffer import Frame, W, H, AMBER, WHITE, GREY, DIM, GREEN, MAGENTA  # noqa: E402
from panelwall.glyphs import draw_glyph, team_mark, hex_color, GLYPHS  # noqa: E402
from panelwall.sinks.simulator import led_image  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..")
OUT = os.path.join(os.path.dirname(__file__), "round2")


def sports():
    from panelwall.data.espn import SportsFeed
    from panelwall.channels.sports import SportsChannel
    fx = json.load(open(os.path.join(ROOT, "fixtures", "espn_scoreboards.json")))
    ch = SportsChannel(feed=SportsFeed(static=fx))
    f = Frame(); ch.tick(0.05); ch.render(f)
    return f.img


def forecast(view):
    from panelwall.data.openmeteo import ForecastFeed
    from panelwall.channels.forecast import ForecastChannel
    fx = json.load(open(os.path.join(ROOT, "fixtures", "openmeteo.json")))
    ch = ForecastChannel(feed=ForecastFeed(static=fx), view=view)
    f = Frame(); ch.render(f)
    return f.img


def ticker():
    """DEFERRED sketch: a one-line news/ADS-B ticker band under a compact status row."""
    f = Frame()
    f.text(2, 0, "BOSTON", fonts.SMALL, AMBER)
    f.text(46, 0, "57F", fonts.SMALL, WHITE)
    draw_glyph(f.draw, "partly", 66, -1)
    f.text_right(W - 2, 0, "23:48", fonts.SMALL, AMBER)
    f.text(2, 16, "RED SOX 7 - 6 ARI  TOP 9TH", fonts.MEDIUM, WHITE)
    f.text(2, 30, "B6 1287 BOS>LAX A321NEO 4250FT   DL 2314 BOS>ATL 737-900 6100FT   N741CG PC-12 2800FT", fonts.SMALL, GREY)
    f.text(2, 46, "RED LINE  HARVARD >ALEWIFE 4 11 MIN", fonts.SMALL, GREY)
    f.text_center(W // 2, 56, "(DEFERRED)", fonts.SMALL, DIM)
    return f.img


def spotify(queue=False):
    """DEFERRED sketch (see design/led_mockups.py D for the earlier version)."""
    f = Frame()
    f.rect([4, 4, 59, 59], fill=(70, 30, 90))
    f.draw.ellipse([18, 18, 46, 46], fill=(20, 20, 40))
    f.text(68, 4, "UP NEXT" if queue else "NOW PLAYING", fonts.SMALL, GREEN)
    f.text(68, 14, "Midnight City", fonts.MEDIUM, WHITE)
    f.text(68, 26, "M83", fonts.SMALL, GREY)
    if queue:
        for i, s in enumerate(("Intro - The xx", "Genesis - Grimes")):
            f.text(68, 34 + i * 9, f"{i + 1}. {s}", fonts.SMALL, GREY)
    else:
        f.rect([68, 40, W - 6, 42], fill=DIM); f.rect([68, 40, 160, 42], fill=WHITE)
        for i, h in enumerate((4, 9, 6, 12, 8, 5, 11, 7)):
            f.rect([150 + i * 4, 60 - h, 152 + i * 4, 60], fill=MAGENTA)
    f.text_right(W - 2, 55, "(DEFERRED)", fonts.SMALL, DIM)
    return f.img


def glyph_row():
    f = Frame()
    for i, g in enumerate(GLYPHS):
        draw_glyph(f.draw, g, 4 + i * 16, 2)
        draw_glyph(f.draw, g, 4 + i * 34, 16, scale=2)
    for i, (c, a) in enumerate((("bd3039", "0c2340"), ("002a5c", "c60c30"), ("007a33", "ba9653"), ("ffb81c", "000000"), ("000000", "c4ced4"))):
        team_mark(f.draw, 4 + i * 12, 50, hex_color(c), hex_color(a))
    f.text(70, 50, "GLYPHS.PY + TEAM_MARK", fonts.SMALL, GREY)
    return f.img


MOCKS = [
    ("1", "Boston tonight (sports)  - BUILT, rendered from the channel", sports),
    ("2", "Ticker band  - DEFERRED", ticker),
    ("3", "Spotify now playing  - DEFERRED", lambda: spotify(False)),
    ("4", "Spotify queue  - DEFERRED", lambda: spotify(True)),
    ("5", "Forecast, week view  - BUILT, rendered from the channel", lambda: forecast("week")),
    ("6", "Forecast, hourly view  - BUILT, rendered from the channel", lambda: forecast("hourly")),
    ("G", "Shared glyphs (panelwall/glyphs.py)", glyph_row),
]

if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    scale, pad, label_h = 4, 16, 26
    font = ImageFont.truetype(fonts.SMALL.path, 16)
    tiles = []
    for key, name, fn in MOCKS:
        im = fn()
        im.save(os.path.join(OUT, f"{key}_native.png"))
        tiles.append((key, name, led_image(np.asarray(im), scale)))
    tw, th = tiles[0][2].size
    sheet = Image.new("RGB", (tw + 2 * pad, len(tiles) * (th + label_h + pad) + pad), (20, 20, 22))
    d = ImageDraw.Draw(sheet)
    y = pad
    for key, name, tile in tiles:
        d.text((pad, y), f"{key}.  {name}", font=font, fill=(220, 220, 220))
        y += label_h
        sheet.paste(tile, (pad, y))
        y += th + pad
    out = os.path.join(OUT, "round2_sheet.png")
    sheet.save(out)
    print("wrote", out, sheet.size)
