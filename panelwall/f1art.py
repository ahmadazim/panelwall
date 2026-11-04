"""F1 art for the sports board: a side-view car sprite in team livery and the 2026 driver -> team table.

ESPN's F1 results name drivers but not constructors, so the livery comes from DRIVER_TEAM (the
2026 grid as best known; unknown drivers get a neutral grey car). Edit the table when seats change.
"""

from __future__ import annotations

from functools import lru_cache

from PIL import Image, ImageDraw

# team -> (main livery colour, accent)
TEAM_COLORS = {
    "ferrari": ((215, 25, 32), (250, 220, 40)),
    "mercedes": ((35, 200, 180), (25, 25, 30)),
    "redbull": ((25, 40, 110), (230, 30, 50)),
    "mclaren": ((255, 128, 0), (40, 140, 220)),
    "astonmartin": ((0, 110, 85), (200, 230, 60)),
    "alpine": ((0, 100, 200), (240, 110, 180)),
    "williams": ((20, 70, 200), (240, 240, 240)),
    "racingbulls": ((70, 100, 220), (240, 240, 240)),
    "haas": ((200, 200, 205), (210, 30, 40)),
    "audi": ((160, 160, 165), (200, 30, 40)),
    "cadillac": ((40, 40, 45), (210, 180, 90)),
}
DRIVER_TEAM = {   # last name (upper) -> team
    "LECLERC": "ferrari", "HAMILTON": "ferrari",
    "RUSSELL": "mercedes", "ANTONELLI": "mercedes",
    "VERSTAPPEN": "redbull", "HADJAR": "redbull",
    "NORRIS": "mclaren", "PIASTRI": "mclaren",
    "ALONSO": "astonmartin", "STROLL": "astonmartin",
    "GASLY": "alpine", "COLAPINTO": "alpine",
    "ALBON": "williams", "SAINZ": "williams",
    "LAWSON": "racingbulls", "LINDBLAD": "racingbulls",
    "OCON": "haas", "BEARMAN": "haas",
    "HULKENBERG": "audi", "BORTOLETO": "audi",
    "PEREZ": "cadillac", "BOTTAS": "cadillac",
}
GREY_CAR = ((150, 150, 155), (90, 90, 95))
CAR_W, CAR_H = 46, 13


def livery(driver_last: str) -> tuple:
    return TEAM_COLORS.get(DRIVER_TEAM.get(driver_last.upper(), ""), GREY_CAR)


@lru_cache(maxsize=64)
def car_sprite(main: tuple, accent: tuple, wheel_phase: int = 0) -> Image.Image:
    """Side view, nose to the RIGHT, 46x13: front + rear wing, halo, helmet, two wheels with a spoke
    that rotates with wheel_phase (0-3)."""
    im = Image.new("RGBA", (CAR_W, CAR_H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    black, tyre, rim = (20, 20, 24), (35, 35, 40), (150, 150, 155)
    d.polygon([(3, 5), (8, 4), (20, 4), (25, 2), (31, 2), (34, 5), (44, 7), (45, 9), (3, 9)], fill=main)       # body
    d.rectangle([0, 1, 4, 6], fill=main)                                                               # rear wing
    d.rectangle([0, 1, 4, 2], fill=accent)
    d.rectangle([41, 9, 45, 10], fill=accent)                                                          # front wing
    d.line([(9, 7), (40, 7)], fill=accent)                                                             # livery stripe
    d.ellipse([24, 0, 28, 4], fill=(240, 240, 240))                                                    # helmet
    d.point((27, 2), fill=black)
    d.line([(22, 2), (29, 1), (32, 3)], fill=black)                                                    # halo
    for cx in (9, 37):                                                                                 # wheels
        d.ellipse([cx - 4, 5, cx + 4, 12], fill=tyre)
        d.ellipse([cx - 2, 7, cx + 2, 10], fill=black)
        dx, dy = ((0, -1), (1, 0), (0, 1), (-1, 0))[wheel_phase % 4]
        d.point((cx + dx, 8 + dy), fill=rim)
    return im


def tla(last: str) -> str:
    return last.upper()[:3]


# ---- host-country flags, hand-drawn at 14x9 (downscaled flag images go muddy at this size) -------------
FLAG_W, FLAG_H = 14, 9
_R, _W, _B, _G, _Y = (215, 30, 40), (235, 235, 235), (20, 50, 150), (0, 130, 60), (250, 205, 30)
_BLACK, _MAROON = (20, 20, 20), (130, 20, 60)


def _hstripes(d, cols):
    n = len(cols)
    for i, c in enumerate(cols):
        d.rectangle([0, round(i * FLAG_H / n), FLAG_W - 1, round((i + 1) * FLAG_H / n) - 1], fill=c)


def _vstripes(d, cols):
    n = len(cols)
    for i, c in enumerate(cols):
        d.rectangle([round(i * FLAG_W / n), 0, round((i + 1) * FLAG_W / n) - 1, FLAG_H - 1], fill=c)


def _union_jack(d, w, h):
    d.rectangle([0, 0, w - 1, h - 1], fill=_B)
    d.line([(0, 0), (w - 1, h - 1)], fill=_W)
    d.line([(0, h - 1), (w - 1, 0)], fill=_W)
    d.rectangle([w // 2 - 1, 0, w // 2 + 1, h - 1], fill=_W)
    d.rectangle([0, h // 2 - 1, w - 1, h // 2 + 1], fill=_W)
    d.line([(w // 2, 0), (w // 2, h - 1)], fill=_R)
    d.line([(0, h // 2), (w - 1, h // 2)], fill=_R)


def _draw_flag(code: str, d) -> bool:
    if code == "ITA":
        _vstripes(d, [_G, _W, _R])
    elif code == "BEL":
        _vstripes(d, [(60, 60, 60), _Y, _R])                            # black stripe lifted to grey: black is "off" on LEDs
    elif code == "MEX":
        _vstripes(d, [_G, _W, _R])
        d.rectangle([6, 3, 7, 5], fill=(140, 90, 40))                    # the eagle, as a dot
    elif code == "AUT":
        _hstripes(d, [_R, _W, _R])
    elif code == "HUN":
        _hstripes(d, [_R, _W, _G])
    elif code == "NED":
        _hstripes(d, [_R, _W, _B])
    elif code == "MON":
        _hstripes(d, [_R, _W])
    elif code == "ESP":
        d.rectangle([0, 0, FLAG_W - 1, FLAG_H - 1], fill=_Y)
        d.rectangle([0, 0, FLAG_W - 1, 1], fill=_R)
        d.rectangle([0, FLAG_H - 2, FLAG_W - 1, FLAG_H - 1], fill=_R)
    elif code == "AZE":
        _hstripes(d, [(0, 150, 200), _R, _G])
        d.point([(6, 4), (8, 4)], fill=_W)                               # crescent + star, as dots
    elif code == "JPN":
        d.rectangle([0, 0, FLAG_W - 1, FLAG_H - 1], fill=_W)
        d.ellipse([4, 2, 9, 6], fill=_R)
    elif code == "CHN":
        d.rectangle([0, 0, FLAG_W - 1, FLAG_H - 1], fill=_R)
        d.rectangle([2, 2, 3, 3], fill=_Y)
        d.point([(5, 1), (6, 2), (6, 4), (5, 5)], fill=_Y)
    elif code == "CAN":
        d.rectangle([0, 0, FLAG_W - 1, FLAG_H - 1], fill=_W)
        d.rectangle([0, 0, 2, FLAG_H - 1], fill=_R)
        d.rectangle([FLAG_W - 3, 0, FLAG_W - 1, FLAG_H - 1], fill=_R)
        d.polygon([(7, 1), (9, 4), (8, 6), (6, 6), (5, 4)], fill=_R)     # maple leaf
        d.point((7, 7), fill=_R)
    elif code == "GBR":
        _union_jack(d, FLAG_W, FLAG_H)
    elif code == "AUS":
        d.rectangle([0, 0, FLAG_W - 1, FLAG_H - 1], fill=_B)
        _union_jack(d, 7, 5)
        d.point([(3, 7), (10, 2), (12, 4), (10, 6), (8, 4)], fill=_W)    # Commonwealth + Southern Cross stars
    elif code == "USA":
        for y in range(FLAG_H):
            d.line([(0, y), (FLAG_W - 1, y)], fill=_R if y % 2 == 0 else _W)
        d.rectangle([0, 0, 5, 4], fill=_B)
        d.point([(1, 1), (3, 1), (2, 2), (4, 2), (1, 3), (3, 3)], fill=_W)
    elif code == "BRA":
        d.rectangle([0, 0, FLAG_W - 1, FLAG_H - 1], fill=(0, 150, 60))
        d.polygon([(7, 0), (13, 4), (7, 8), (1, 4)], fill=_Y)
        d.ellipse([5, 3, 9, 5], fill=(30, 50, 140))
    elif code == "BHR":
        d.rectangle([0, 0, FLAG_W - 1, FLAG_H - 1], fill=_R)
        d.rectangle([0, 0, 3, FLAG_H - 1], fill=_W)
        for y in range(0, FLAG_H, 2):
            d.point((4, y), fill=_W)                                     # serrated edge
    elif code == "QAT":
        d.rectangle([0, 0, FLAG_W - 1, FLAG_H - 1], fill=_MAROON)
        d.rectangle([0, 0, 3, FLAG_H - 1], fill=_W)
        for y in range(0, FLAG_H, 2):
            d.point((4, y), fill=_W)
    elif code == "SAU":
        d.rectangle([0, 0, FLAG_W - 1, FLAG_H - 1], fill=(0, 110, 50))
        d.line([(3, 3), (10, 3)], fill=_W)                                # the inscription
        d.line([(3, 6), (10, 6)], fill=_W)                                # the sword
    elif code == "UAE":
        _hstripes(d, [_G, _W, _BLACK])
        d.rectangle([0, 0, 3, FLAG_H - 1], fill=_R)
        d.rectangle([4, FLAG_H - 3, FLAG_W - 1, FLAG_H - 1], fill=(55, 55, 55))   # black stripe, lifted to be seen
    elif code == "MYS":
        for y in range(FLAG_H):
            d.line([(0, y), (FLAG_W - 1, y)], fill=_R if y % 2 == 0 else _W)
        d.rectangle([0, 0, 6, 4], fill=_B)
        d.point([(2, 2), (4, 2)], fill=_Y)                               # crescent + star
    elif code == "SGP":
        _hstripes(d, [_R, _W])
        d.point([(2, 1), (2, 3), (4, 1), (5, 2), (4, 3)], fill=_W)       # crescent + stars
    else:
        return False
    return True


# ESPN's circuit.address.country (lower case) -> flag code
COUNTRY_CODES = {
    "australia": "AUS", "china": "CHN", "japan": "JPN", "bahrain": "BHR", "saudi arabia": "SAU",
    "usa": "USA", "united states": "USA", "canada": "CAN", "monaco": "MON", "spain": "ESP",
    "austria": "AUT", "britain": "GBR", "great britain": "GBR", "united kingdom": "GBR", "belgium": "BEL",
    "hungary": "HUN", "netherlands": "NED", "italy": "ITA", "azerbaijan": "AZE", "malaysia": "MYS",
    "singapore": "SGP", "mexico": "MEX", "brazil": "BRA", "qatar": "QAT", "united arab emirates": "UAE",
    "abu dhabi": "UAE",
}


def country_code(country: str, race_name: str = "") -> str | None:
    """ESPN country name -> flag code; falls back to a country named in the race title."""
    code = COUNTRY_CODES.get((country or "").strip().lower())
    if code:
        return code
    name = (race_name or "").lower()
    for key in sorted(COUNTRY_CODES, key=len, reverse=True):
        if key in name:
            return COUNTRY_CODES[key]
    return None


@lru_cache(maxsize=32)
def flag(code: str | None) -> Image.Image | None:
    if not code:
        return None
    im = Image.new("RGBA", (FLAG_W, FLAG_H), (0, 0, 0, 0))
    return im if _draw_flag(code, ImageDraw.Draw(im)) else None
