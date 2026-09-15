"""Pixel fonts bundled in assets/fonts.

SMALL  = Silkscreen 8px   -> 5px-tall caps, ~6px advance. ~42 chars across 256px.
MEDIUM = Press Start 2P 8px -> true 8x8 cells. 32 chars across.
LARGE  = Press Start 2P 16px -> 16x16 cells. 16 chars across. "Hero" text only.
FW     = Adafruit GFX classic 5x7 (glcd5x7.pil, built by tools/build_fw_font.py from glcdfont.c, BSD).
         6px advance, 7px caps, descenders in row 8, slashed zero, TRUE LOWERCASE. 42 chars across.
         This is the FlightWall's font (or indistinguishable from it) - use it for that replica only.
"""

from pathlib import Path

from PIL import ImageFont

_ASSETS = Path(__file__).resolve().parent.parent / "assets" / "fonts"

SMALL = ImageFont.truetype(str(_ASSETS / "Silkscreen.ttf"), 8)
MEDIUM = ImageFont.truetype(str(_ASSETS / "PressStart2P.ttf"), 8)
LARGE = ImageFont.truetype(str(_ASSETS / "PressStart2P.ttf"), 16)
FW = ImageFont.load(str(_ASSETS / "glcd5x7.pil"))       # bitmap font: getbbox/getlength work like the TTFs


def width(s: str, font=SMALL) -> int:
    return int(font.getlength(s))
