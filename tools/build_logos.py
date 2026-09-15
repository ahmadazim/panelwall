"""Generate assets/logos/<ICAO>.png - 28x28 RGBA pixel-art airline marks for the FlightWall card.

    python tools/build_logos.py            # writes the PNGs and design/logos_sheet.png

These are hand-drawn, personal-use APPROXIMATIONS of trademarked marks (2-3 colour
shapes meant to be recognisable at arm's length), not the real logos. Nothing is
downloaded. 'private' is used for N-number aircraft, 'generic' for unknown carriers.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "logos"
N = 28


def canvas():
    im = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    return im, ImageDraw.Draw(im)


def heart_mask():
    """Filled heart, 26 px wide, as a mask image."""
    m = Image.new("L", (N, N), 0)
    d = ImageDraw.Draw(m)
    d.ellipse([1, 2, 14, 15], fill=255)
    d.ellipse([13, 2, 26, 15], fill=255)
    d.polygon([(1, 10), (26, 10), (14, 26)], fill=255)
    return m


def swa():
    # Southwest heart: blue body, red/orange/yellow diagonal bands through the middle
    im, _ = canvas()
    body = Image.new("RGBA", (N, N), (48, 74, 171, 255))
    d = ImageDraw.Draw(body)
    # bands fall from upper-left to lower-right; yellow/orange above red, blue below (as on the photo)
    for i, c in enumerate(((255, 191, 39, 255), (247, 111, 33, 255), (228, 30, 46, 255))):
        y = -2 + i * 5
        d.polygon([(0, y), (N, y + 14), (N, y + 19), (0, y + 5)], fill=c)
    im.paste(body, (0, 0), heart_mask())
    return im


def dal():
    im, d = canvas()
    d.polygon([(14, 1), (26, 26), (14, 26)], fill=(200, 16, 46, 255))      # right half, red
    d.polygon([(14, 1), (2, 26), (14, 26)], fill=(150, 12, 36, 255))       # left half, darker red
    return im


def aal():
    im, d = canvas()
    # slanted flag: blue top, white sliver, red bottom (the eagle mark simplified)
    d.polygon([(9, 1), (27, 1), (19, 14), (1, 14)], fill=(0, 120, 210, 255))
    d.polygon([(1, 14), (19, 14), (17, 17), (0, 17)], fill=(235, 235, 235, 255))
    d.polygon([(0, 17), (17, 17), (9, 27), (0, 27)], fill=(200, 30, 40, 255))
    return im


def ual():
    im, d = canvas()
    d.rectangle([0, 0, 27, 27], fill=(0, 51, 160, 255))
    # globe: white circle with meridians/parallels in blue
    d.ellipse([4, 4, 23, 23], fill=(235, 235, 235, 255))
    d.ellipse([9, 4, 18, 23], outline=(0, 51, 160, 255))
    d.line([(4, 13), (23, 13)], fill=(0, 51, 160, 255))
    d.line([(6, 8), (21, 8)], fill=(0, 51, 160, 255))
    d.line([(6, 18), (21, 18)], fill=(0, 51, 160, 255))
    d.line([(13, 4), (13, 23)], fill=(0, 51, 160, 255))
    return im


def jbu():
    im, d = canvas()
    d.rounded_rectangle([0, 0, 27, 27], radius=6, fill=(0, 51, 141, 255))
    # tail-fin swoosh in JetBlue's lighter blue + white
    d.polygon([(5, 22), (13, 4), (17, 4), (11, 22)], fill=(235, 235, 235, 255))
    d.polygon([(11, 22), (17, 4), (23, 4), (17, 22)], fill=(40, 150, 220, 255))
    return im


def nks():
    im, d = canvas()
    d.rectangle([0, 0, 27, 27], fill=(255, 220, 0, 255))
    # a bold black "S"
    k = (20, 20, 20, 255)
    d.rectangle([7, 5, 20, 8], fill=k)
    d.rectangle([7, 5, 10, 13], fill=k)
    d.rectangle([7, 12, 20, 15], fill=k)
    d.rectangle([17, 12, 20, 22], fill=k)
    d.rectangle([7, 19, 20, 22], fill=k)
    return im


def fft():
    im, d = canvas()
    d.rounded_rectangle([0, 0, 27, 27], radius=4, fill=(0, 106, 68, 255))
    w = (235, 235, 235, 255)
    d.rectangle([7, 5, 10, 22], fill=w)        # F stem
    d.rectangle([7, 5, 21, 8], fill=w)
    d.rectangle([7, 12, 18, 15], fill=w)
    return im


def asa():
    im, d = canvas()
    d.ellipse([0, 0, 27, 27], fill=(1, 66, 106, 255))
    # smiling face
    d.ellipse([7, 6, 20, 21], fill=(235, 235, 235, 255))
    d.point([(11, 12), (16, 12)], fill=(1, 66, 106, 255))
    d.arc([10, 12, 17, 18], 20, 160, fill=(1, 66, 106, 255))
    d.rectangle([7, 4, 20, 7], fill=(60, 180, 190, 255))      # hood
    return im


def ein():
    im, d = canvas()
    g = (0, 128, 96, 255)
    d.ellipse([9, 1, 18, 10], fill=g)
    d.ellipse([2, 8, 11, 17], fill=g)
    d.ellipse([16, 8, 25, 17], fill=g)
    d.ellipse([9, 9, 18, 18], fill=g)
    d.line([(13, 16), (13, 25), (16, 27)], fill=g, width=2)
    return im


def baw():
    im, d = canvas()
    # speedmarque: a red ribbon over a blue one, both swooping
    d.polygon([(1, 16), (27, 8), (27, 13), (1, 21)], fill=(200, 16, 46, 255))
    d.polygon([(1, 21), (27, 13), (27, 17), (1, 25)], fill=(235, 235, 235, 255))
    d.polygon([(1, 25), (27, 17), (27, 21), (1, 27)], fill=(7, 82, 156, 255))
    return im


def aca():
    im, d = canvas()
    r = (240, 30, 40, 255)
    d.ellipse([0, 0, 27, 27], outline=r, width=2)
    # maple leaf (simplified)
    leaf = [(14, 4), (16, 9), (20, 7), (19, 12), (23, 13), (18, 17), (20, 21), (15, 19), (14, 25),
            (13, 19), (8, 21), (10, 17), (5, 13), (9, 12), (8, 7), (12, 9)]
    d.polygon(leaf, fill=r)
    return im


def kap():
    im, d = canvas()
    d.rounded_rectangle([0, 0, 27, 27], radius=4, fill=(0, 70, 140, 255))
    d.ellipse([15, 3, 25, 13], fill=(255, 200, 40, 255))                 # sun
    _plane(d, 2, 4, 20, (235, 235, 235, 255))                             # small white plane
    return im


def _plane(d, x, y, w, c):
    """Top-view airliner silhouette, nose right, ~w wide and 22 tall, top-left at (x, y)."""
    sx = w / 24.0
    cy = y + 11
    top = [(24, 0), (21, -2), (13, -2), (8, -11), (5, -11), (7, -2), (3, -2), (0, -6), (-1, -6), (0, -1)]
    pts = [(x + px * sx, cy + py) for px, py in top]
    pts += [(x + px * sx, cy - py) for px, py in reversed(top)]
    d.polygon(pts, fill=c)


def private():
    # small GA plane (straight wings, single engine), grey, top view, nose right
    im, d = canvas()
    c = (170, 170, 170, 255)
    d.rectangle([3, 12, 25, 15], fill=c)                    # fuselage
    d.rectangle([11, 2, 15, 25], fill=c)                    # straight wing
    d.rectangle([2, 8, 6, 19], fill=c)                      # tail
    d.rectangle([25, 13, 26, 14], fill=c)                   # prop hub
    d.line([(26, 9), (26, 18)], fill=c)                     # prop disc
    return im


def generic():
    im, d = canvas()
    _plane(d, 2, 3, 24, (235, 235, 235, 255))
    return im


LOGOS = {"SWA": swa, "DAL": dal, "AAL": aal, "UAL": ual, "JBU": jbu, "NKS": nks, "FFT": fft, "ASA": asa,
         "EIN": ein, "BAW": baw, "ACA": aca, "KAP": kap, "private": private, "generic": generic}


def build() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, fn in LOGOS.items():
        fn().save(OUT / f"{name}.png")


def sheet(scale: int = 6) -> Image.Image:
    sys.path.insert(0, str(ROOT))
    import numpy as np
    from panelwall.sinks.simulator import led_image
    cols = 7
    rows = math.ceil(len(LOGOS) / cols)
    tile = N * scale
    im = Image.new("RGB", (cols * (tile + 12) + 12, rows * (tile + 30) + 12), (20, 20, 22))
    d = ImageDraw.Draw(im)
    for i, (name, fn) in enumerate(LOGOS.items()):
        x, y = 12 + (i % cols) * (tile + 12), 12 + (i // cols) * (tile + 30)
        rgb = Image.new("RGB", (N, N), (0, 0, 0))
        logo = fn()
        rgb.paste(logo, (0, 0), logo)
        im.paste(led_image(np.asarray(rgb), scale), (x, y))
        d.text((x, y + tile + 6), name, fill=(220, 220, 220))
    return im


if __name__ == "__main__":
    build()
    sheet().save(ROOT / "design" / "logos_sheet.png")
    print("wrote", len(LOGOS), "logos to", OUT, "and design/logos_sheet.png")
