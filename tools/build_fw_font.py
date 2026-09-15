"""Build assets/fonts/glcd5x7.pil/.pbm from assets/fonts/glcdfont.c (Adafruit GFX classic font, BSD).

The classic GFX font is 5 columns x 8 rows per glyph (bit 0 = top row, bit 7 =
descender row), drawn with a 6 px advance. That is exactly the FlightWall's
look: 7 px caps, slashed zero, lowercase with descenders, 6 px per character.

    python tools/build_fw_font.py
"""

import io
import re
from pathlib import Path

from PIL import BdfFontFile

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "assets" / "fonts" / "glcdfont.c"
OUT = ROOT / "assets" / "fonts" / "glcd5x7"

data = [int(x, 16) for x in re.findall(r"0x([0-9A-Fa-f]{2})", SRC.read_text())]
assert len(data) >= 256 * 5, len(data)

lines = ["STARTFONT 2.1", "FONT -adafruit-glcd-medium-r-normal--8-80-75-75-c-60-iso10646-1",
         "SIZE 8 75 75", "FONTBOUNDINGBOX 6 8 0 -1",
         "STARTPROPERTIES 2", "FONT_ASCENT 7", "FONT_DESCENT 1", "ENDPROPERTIES", "CHARS 224"]
for code in range(32, 256):
    cols = data[code * 5: code * 5 + 5]
    rows = []
    for r in range(8):
        bits = 0
        for c in range(5):
            if cols[c] >> r & 1:
                bits |= 0x80 >> c
        rows.append(f"{bits:02X}")
    lines += [f"STARTCHAR U+{code:04X}", f"ENCODING {code}", "SWIDTH 600 0", "DWIDTH 6 0",
              "BBX 5 8 0 -1", "BITMAP", *rows, "ENDCHAR"]
lines.append("ENDFONT")
bdf = "\n".join(lines).encode()
BdfFontFile.BdfFontFile(io.BytesIO(bdf)).save(str(OUT))
print("wrote", OUT.with_suffix(".pil"), OUT.with_suffix(".pbm"))
