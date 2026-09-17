"""Pixel fonts bundled in assets/fonts.

SMALL  = Silkscreen 8px   -> 5px-tall caps, ~6px advance. ~42 chars across 256px.
MEDIUM = Press Start 2P 8px -> true 8x8 cells. 32 chars across.
LARGE  = Press Start 2P 16px -> 16x16 cells. 16 chars across. "Hero" text only.
FW     = X11 misc-fixed 6x10 (6x10.pil, built by tools/build_fw_font.py from 6x10.bdf, public domain).
         6px advance, 7px caps in rows 1-7 of a 10px cell, descenders to row 9, TRUE LOWERCASE, pointed A.
         Matches the FlightWall's typeface (compared against the product photos). 42 chars across.
"""

import unicodedata
from pathlib import Path

from PIL import ImageFont

_ASSETS = Path(__file__).resolve().parent.parent / "assets" / "fonts"

SMALL = ImageFont.truetype(str(_ASSETS / "Silkscreen.ttf"), 8)
MEDIUM = ImageFont.truetype(str(_ASSETS / "PressStart2P.ttf"), 8)
LARGE = ImageFont.truetype(str(_ASSETS / "PressStart2P.ttf"), 16)
FW = ImageFont.load(str(_ASSETS / "6x10.pil"))          # bitmap font: getbbox/getlength work like the TTFs


_SPECIAL = str.maketrans({"ß": "ss", "æ": "ae", "Æ": "AE", "ø": "o", "Ø": "O", "œ": "oe", "Œ": "OE", "ð": "d", "Ð": "D",
                          "þ": "th", "Þ": "Th", "ł": "l", "Ł": "L", "đ": "d", "Đ": "D", "ı": "i", "İ": "I",
                          "\u2013": "-", "\u2014": "-", "\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"',
                          "\u00a0": " "})


def safe_text(s: str, font=None) -> str:
    """Make `s` drawable by `font`. Bitmap (.pil) fonts only know Latin-1 and Pillow raises
    UnicodeEncodeError on anything else (an 'İstanbul' airport name crashed the frame loop on
    the Pi). Accents are stripped (NFKD), a few letters transliterated, anything left that the
    font cannot encode becomes '?'. TrueType fonts are left alone."""
    if not isinstance(font, ImageFont.ImageFont):
        return s
    s = s.translate(_SPECIAL)
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))
    return "".join(c if ord(c) < 256 else "?" for c in s)


def width(s: str, font=SMALL) -> int:
    return int(font.getlength(safe_text(s, font)))
