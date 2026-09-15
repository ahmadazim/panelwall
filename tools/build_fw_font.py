"""Build assets/fonts/6x10.pil/.pbm from assets/fonts/6x10.bdf (X11 misc-fixed, public domain).

The FlightWall's typeface matches the classic X11 "6x10" terminal font: 6 px advance,
7 px caps (rows 1-7 of the 10 px cell), lowercase with descenders to row 9, pointed A,
hooked t. The BDF is the copy shipped in hzeller/rpi-rgb-led-matrix/fonts (public
domain, "Share and enjoy" - see the COPYRIGHT line inside the file).

    python tools/build_fw_font.py
"""

from pathlib import Path

from PIL import BdfFontFile

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "assets" / "fonts" / "6x10.bdf"
OUT = ROOT / "assets" / "fonts" / "6x10"

# The 6x10 colon and period are 3-pixel "+" dots; the FlightWall's are single pixels.
# Patch those two glyphs' bitmaps before converting.
PATCHES = {
    "colon":  ["00", "00", "00", "20", "00", "00", "20", "00", "00", "00"],
    "period": ["00", "00", "00", "00", "00", "00", "00", "20", "00", "00"],
}

import io
import re

text = SRC.read_text(encoding="latin-1")
for name, rows in PATCHES.items():
    m = re.search(rf"STARTCHAR {name}\n(?:.*\n)*?BITMAP\n((?:[0-9A-Fa-f]+\n){{10}})ENDCHAR", text)
    assert m, name
    text = text[: m.start(1)] + "\n".join(rows) + "\n" + text[m.end(1):]
BdfFontFile.BdfFontFile(io.BytesIO(text.encode("latin-1"))).save(str(OUT))
print("wrote", OUT.with_suffix(".pil"), OUT.with_suffix(".pbm"), "(colon/period patched to single-pixel dots)")
