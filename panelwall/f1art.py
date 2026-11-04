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
