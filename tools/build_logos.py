"""Generate assets/logos/<ICAO>.png - 28x28 RGBA pixel-art airline logos for the FlightWall card.

    python tools/build_logos.py            # writes the PNGs
    python -m panelwall logos              # PNGs + design/logos_sheet.png at 6x for review

Hand-drawn approximations of the real airline marks for PERSONAL, non-commercial use
on one living-room display (the same way the FlightWall product photos show them).
Every tile fills the full 28x28 block and uses at least two brand colours; fine detail
that cannot survive 28 px is dropped in favour of silhouette + colour. 'private' is
used for N-number aircraft, 'generic' for carriers without a tile.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "logos"
N = 28
WHITE = (240, 240, 240, 255)


def canvas():
    im = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    return im, ImageDraw.Draw(im)


def _heart_mask() -> Image.Image:
    m = Image.new("L", (N, N), 0)
    d = ImageDraw.Draw(m)
    d.ellipse([0, 1, 14, 15], fill=255)
    d.ellipse([13, 1, 27, 15], fill=255)
    d.polygon([(0, 9), (27, 9), (14, 27)], fill=255)
    return m


def swa():
    """Southwest heart (as on the product photo): blue body, a wide red band sloping from the
    upper-left lobe to the lower-right, a thin gold band above it on the upper-right lobe, and a
    light outline."""
    im, _ = canvas()
    blue, red, orange, gold = (35, 74, 170, 255), (228, 30, 46, 255), (247, 111, 33, 255), (255, 191, 39, 255)
    body = Image.new("RGBA", (N, N), blue)
    d = ImageDraw.Draw(body)
    d.polygon([(0, -2), (N, 10), (N, -2)], fill=gold)                     # everything above the red band
    d.polygon([(0, -2), (N, 10), (N, 13), (0, 1)], fill=orange)            # thin orange band on its edge
    d.polygon([(0, 1), (N, 13), (N, 25), (0, 13)], fill=red)               # the wide red band
    mask = _heart_mask()
    im.paste(body, (0, 0), mask)
    # 1 px light outline: the mask's edge pixels
    edge = mask.filter(ImageFilter.FIND_EDGES).point(lambda v: 255 if v else 0)
    im.paste(Image.new("RGBA", (N, N), (225, 225, 235, 255)), (0, 0), edge)
    return im


def dal():
    """Delta widget (as in the customer photos): bright red triangle with a dark chevron cut
    across its lower third and a bright base strip under it."""
    im, d = canvas()
    bright, dark = (235, 40, 60, 255), (110, 8, 28, 255)
    d.polygon([(14, 0), (27, 27), (0, 27)], fill=bright)
    d.polygon([(1, 22), (14, 14), (26, 22), (26, 25), (14, 18), (1, 25)], fill=dark)
    return im


def aal():
    """American eagle-side flag: slanted stripes silver / red / blue, tall and narrow, leaning right."""
    im, d = canvas()
    silver, red, blue = (190, 195, 205, 255), (215, 25, 45, 255), (0, 100, 190, 255)
    d.polygon([(8, 0), (14, 0), (6, 27), (0, 27)], fill=silver)
    d.polygon([(14, 0), (20, 0), (12, 27), (6, 27)], fill=red)
    d.polygon([(20, 0), (27, 0), (19, 27), (12, 27)], fill=blue)
    d.polygon([(22, 0), (27, 0), (27, 8)], fill=silver)                    # eagle head highlight
    return im


def ual():
    """United: blue square, white globe with meridian / parallel arcs."""
    im, d = canvas()
    blue = (0, 51, 160, 255)
    d.rectangle([0, 0, 27, 27], fill=blue)
    d.ellipse([3, 3, 24, 24], fill=WHITE)
    for box in ([8, 3, 19, 24], [11, 3, 16, 24]):
        d.ellipse(box, outline=blue)
    d.line([(3, 13), (24, 13)], fill=blue)
    d.line([(5, 8), (22, 8)], fill=blue)
    d.line([(5, 18), (22, 18)], fill=blue)
    d.line([(13, 3), (13, 24)], fill=blue)
    d.ellipse([3, 3, 24, 24], outline=blue)
    return im


def jbu():
    """JetBlue: navy square, tail-fin pattern in white and light blue."""
    im, d = canvas()
    d.rectangle([0, 0, 27, 27], fill=(0, 51, 141, 255))
    d.polygon([(3, 25), (12, 3), (17, 3), (10, 25)], fill=WHITE)
    d.polygon([(10, 25), (17, 3), (24, 3), (18, 25)], fill=(60, 170, 235, 255))
    d.polygon([(18, 25), (24, 3), (27, 3), (27, 12), (23, 25)], fill=(0, 110, 200, 255))
    return im


def nks():
    """Spirit: yellow square, black 'S' mark."""
    im, d = canvas()
    d.rectangle([0, 0, 27, 27], fill=(255, 220, 0, 255))
    k = (15, 15, 15, 255)
    d.rounded_rectangle([6, 4, 21, 8], radius=2, fill=k)
    d.rectangle([6, 4, 10, 14], fill=k)
    d.rounded_rectangle([6, 12, 21, 16], radius=2, fill=k)
    d.rectangle([17, 12, 21, 23], fill=k)
    d.rounded_rectangle([6, 19, 21, 23], radius=2, fill=k)
    return im


def fft():
    """Frontier: green rounded square, the animal-tail 'F' in white with a lighter green tail stroke."""
    im, d = canvas()
    green, light = (0, 106, 68, 255), (120, 200, 80, 255)
    d.rounded_rectangle([0, 0, 27, 27], radius=5, fill=green)
    d.rectangle([7, 5, 10, 23], fill=WHITE)
    d.rectangle([7, 5, 22, 8], fill=WHITE)
    d.rectangle([7, 13, 18, 16], fill=WHITE)
    d.polygon([(20, 17), (27, 12), (27, 20), (21, 23)], fill=light)       # the tail curl
    return im


def asa():
    """Alaska: the Eskimo face - navy circle, white face, dark eyes and smile, teal hood."""
    im, d = canvas()
    navy = (1, 66, 106, 255)
    d.ellipse([0, 0, 27, 27], fill=navy)
    d.rounded_rectangle([5, 3, 22, 9], radius=3, fill=(60, 180, 190, 255))   # hood / fur trim
    d.ellipse([6, 7, 21, 23], fill=WHITE)
    d.rectangle([9, 12, 10, 14], fill=navy)
    d.rectangle([17, 12, 18, 14], fill=navy)
    d.arc([9, 12, 18, 20], 15, 165, fill=navy, width=2)
    d.rectangle([12, 22, 15, 24], fill=navy)                                   # chin shadow
    return im


def ein():
    """Aer Lingus shamrock: bright green, three round leaves and a curved stem."""
    im, d = canvas()
    g, g2 = (0, 150, 110, 255), (0, 120, 88, 255)
    d.ellipse([8, 0, 19, 11], fill=g)
    d.ellipse([0, 7, 11, 18], fill=g)
    d.ellipse([16, 7, 27, 18], fill=g)
    d.ellipse([8, 8, 19, 19], fill=g2)
    d.line([(13, 17), (13, 24), (17, 27)], fill=g2, width=3)
    return im


def baw():
    """British Airways speedmarque: a red ribbon over white over blue, sweeping up to the right."""
    im, d = canvas()
    d.polygon([(0, 14), (27, 2), (27, 9), (0, 21)], fill=(200, 16, 46, 255))
    d.polygon([(0, 21), (27, 9), (27, 14), (0, 25)], fill=WHITE)
    d.polygon([(0, 25), (27, 14), (27, 21), (2, 27)], fill=(7, 82, 156, 255))
    return im


def aca():
    """Air Canada rondelle: red ring with a red maple leaf."""
    im, d = canvas()
    r = (240, 30, 40, 255)
    d.ellipse([0, 0, 27, 27], outline=r, width=3)
    leaf = [(14, 3), (16, 8), (20, 6), (19, 11), (24, 12), (19, 16), (21, 20), (16, 18), (15, 25),
            (13, 25), (12, 18), (7, 20), (9, 16), (4, 12), (9, 11), (8, 6), (12, 8)]
    d.polygon(leaf, fill=r)
    return im


def kap():
    """Cape Air: blue square, yellow sun, white gull-wing aircraft."""
    im, d = canvas()
    d.rectangle([0, 0, 27, 27], fill=(0, 70, 140, 255))
    d.ellipse([14, 2, 26, 14], fill=(255, 200, 40, 255))
    d.polygon([(1, 20), (10, 14), (27, 17), (27, 19), (10, 19), (1, 24)], fill=WHITE)   # swept wing/plane
    d.polygon([(6, 24), (13, 22), (14, 25), (7, 27)], fill=WHITE)
    return im


def private():
    """N-number aircraft: grey high-wing single, top view, nose up."""
    im, d = canvas()
    c, c2 = (185, 185, 185, 255), (120, 120, 120, 255)
    d.rectangle([12, 2, 15, 26], fill=c)                        # fuselage
    d.rectangle([1, 9, 26, 12], fill=c)                         # wing
    d.rectangle([8, 23, 19, 25], fill=c)                        # tail
    d.rectangle([13, 0, 14, 2], fill=c2)                        # prop
    d.line([(9, 1), (18, 1)], fill=c2)
    return im


def generic():
    """Unknown carrier: white airliner silhouette, top view, nose up."""
    im, d = canvas()
    pts = [(14, 0), (16, 3), (16, 10), (27, 18), (27, 21), (16, 17), (16, 23), (20, 26), (20, 27),
           (14, 26), (8, 27), (8, 26), (12, 23), (12, 17), (1, 21), (1, 18), (12, 10), (12, 3)]
    d.polygon(pts, fill=WHITE)
    d.rectangle([13, 4, 14, 8], fill=(120, 160, 220, 255))      # cockpit
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
