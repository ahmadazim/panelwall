"""Procedural side-profile aircraft sprites (nose left), max 100x32 px.

One builder, `build_sprite(params, tail_color, stripe_color)`, draws a plane
from a handful of shape parameters; `TYPE_PARAMS` maps ICAO type designators
to those parameters. New types are one dict line, not new artwork.

    img = sprite_for("A21N", airline_icao="JBU")   # RGBA PIL image, cached

Geometry is in a 100x32 box with the fuselage centreline at y=16. Lengths are
in pixels and roughly proportional to the real aircraft (A321 = 86, C172 = 30).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from functools import lru_cache

from PIL import Image, ImageDraw

SPRITE_W, SPRITE_H = 100, 32
YC = 16  # fuselage centreline

BODY = (232, 232, 232)
BODY_SHADE = (196, 196, 196)
NACELLE = (128, 128, 128)
INTAKE = (55, 55, 55)
GLASS = (50, 80, 130)
DEFAULT_TAIL = (120, 120, 120)
DEFAULT_STRIPE = (120, 120, 120)

# ICAO operator -> (tail color, cheatline color)
AIRLINE_COLORS: dict[str, tuple[tuple[int, int, int], tuple[int, int, int]]] = {
    "JBU": ((0, 90, 200), (0, 90, 200)),
    "DAL": ((200, 30, 40), (30, 50, 120)),
    "AAL": ((200, 30, 40), (170, 170, 185)),
    "UAL": ((0, 70, 180), (0, 70, 180)),
    "SWA": ((40, 60, 200), (255, 200, 0)),
    "EIN": ((0, 140, 60), (0, 140, 60)),
    "BAW": ((20, 40, 120), (200, 30, 40)),
}


@dataclass(frozen=True)
class SpriteParams:
    length: int = 76                 # nose tip to tail end, px
    height: int = 8                  # fuselage height, px
    engines: int = 2
    engine_pos: str = "wing"         # wing | tail | nose
    prop: bool = False               # propeller instead of jet nacelle
    tail: str = "conventional"       # conventional | t_tail
    winglets: bool = True
    high_wing: bool = False
    kind: str = "plane"              # plane | heli


# ---- family presets ----------------------------------------------------------
_JET = SpriteParams()
_WIDE = SpriteParams(height=9)
_REGIONAL = SpriteParams(height=7)
_REAR_JET = SpriteParams(height=6, engine_pos="tail", tail="t_tail")     # CRJ / bizjet / MD-80
_HIGH_TURBOPROP = SpriteParams(height=6, prop=True, high_wing=True, tail="t_tail", winglets=False)
_GA_HIGH = SpriteParams(length=38, height=5, engines=1, engine_pos="nose", prop=True, high_wing=True, winglets=False)
_GA_LOW = SpriteParams(length=38, height=5, engines=1, engine_pos="nose", prop=True, winglets=False)
_TWIN_PROP = SpriteParams(length=46, height=6, engines=2, prop=True, winglets=False)
_HELI = SpriteParams(length=52, height=8, engines=0, kind="heli", winglets=False)

TYPE_PARAMS: dict[str, SpriteParams] = {
    # Airbus narrowbody
    "A318": replace(_JET, length=64), "A319": replace(_JET, length=70), "A19N": replace(_JET, length=70),
    "A320": replace(_JET, length=76), "A20N": replace(_JET, length=76),
    "A321": replace(_JET, length=86), "A21N": replace(_JET, length=86),
    # Boeing 737
    "B737": replace(_JET, length=72, winglets=False), "B738": replace(_JET, length=78), "B739": replace(_JET, length=84),
    "B37M": replace(_JET, length=74), "B38M": replace(_JET, length=80), "B39M": replace(_JET, length=86), "B3XM": replace(_JET, length=90),
    "B733": replace(_JET, length=66, winglets=False), "B734": replace(_JET, length=72, winglets=False),
    # Boeing 757 / 767 / 777 / 787
    "B752": replace(_JET, length=88, winglets=True), "B753": replace(_JET, length=92, winglets=True),
    "B762": replace(_WIDE, length=84, winglets=False), "B763": replace(_WIDE, length=90, winglets=False), "B764": replace(_WIDE, length=92),
    "B772": replace(_WIDE, length=90, height=10, winglets=False), "B77W": replace(_WIDE, length=92, height=10, winglets=False),
    "B77L": replace(_WIDE, length=90, height=10, winglets=False), "B773": replace(_WIDE, length=92, height=10, winglets=False),
    "B788": replace(_WIDE, length=88), "B789": replace(_WIDE, length=92), "B78X": replace(_WIDE, length=92),
    "B744": replace(_WIDE, length=92, height=11, engines=4, winglets=True), "B748": replace(_WIDE, length=92, height=11, engines=4),
    # Airbus widebody
    "A332": replace(_WIDE, length=88), "A333": replace(_WIDE, length=92), "A339": replace(_WIDE, length=92),
    "A359": replace(_WIDE, length=92), "A35K": replace(_WIDE, length=92),
    "A343": replace(_WIDE, length=92, engines=4), "A346": replace(_WIDE, length=92, engines=4),
    "A388": replace(_WIDE, length=92, height=12, engines=4),
    # Embraer / A220
    "E170": replace(_REGIONAL, length=58), "E75L": replace(_REGIONAL, length=62), "E75S": replace(_REGIONAL, length=62),
    "E190": replace(_REGIONAL, length=66), "E195": replace(_REGIONAL, length=70),
    "E290": replace(_REGIONAL, length=66), "E295": replace(_REGIONAL, length=72),
    "BCS1": replace(_REGIONAL, length=64, winglets=False), "BCS3": replace(_REGIONAL, length=70, winglets=False),
    # CRJ (rear engines, T-tail)
    "CRJ2": replace(_REAR_JET, length=50, winglets=True), "CRJ7": replace(_REAR_JET, length=58, winglets=True),
    "CRJ9": replace(_REAR_JET, length=64, winglets=True), "CRJX": replace(_REAR_JET, length=70, winglets=True),
    # MD-80 family / 717 (rear engines, T-tail)
    "MD82": replace(_REAR_JET, length=84, height=8, winglets=False), "MD83": replace(_REAR_JET, length=84, height=8, winglets=False),
    "MD88": replace(_REAR_JET, length=84, height=8, winglets=False), "MD90": replace(_REAR_JET, length=88, height=8, winglets=False),
    "B712": replace(_REAR_JET, length=76, height=8, winglets=False),
    # Turboprops
    "DH8D": replace(_HIGH_TURBOPROP, length=62), "DH8C": replace(_HIGH_TURBOPROP, length=56),
    "AT72": replace(_HIGH_TURBOPROP, length=56), "AT76": replace(_HIGH_TURBOPROP, length=56),
    "PC12": replace(_GA_LOW, length=50, height=6, tail="t_tail"),
    "TBM7": replace(_GA_LOW, length=44), "TBM8": replace(_GA_LOW, length=44), "TBM9": replace(_GA_LOW, length=44),
    "C208": replace(_GA_HIGH, length=50, height=6),
    "BE20": replace(_TWIN_PROP, length=50, tail="t_tail"), "BE9L": replace(_TWIN_PROP, length=48, tail="t_tail"),
    "B350": replace(_TWIN_PROP, length=54, tail="t_tail"),
    # Piston GA - high wing
    "C172": _GA_HIGH, "C182": _GA_HIGH, "C150": replace(_GA_HIGH, length=34), "C152": replace(_GA_HIGH, length=34),
    "C177": _GA_HIGH, "C206": replace(_GA_HIGH, length=42), "C210": replace(_GA_HIGH, length=42), "GA8": replace(_GA_HIGH, length=42),
    # Piston GA - low wing
    "P28A": _GA_LOW, "PA28": _GA_LOW, "P28R": _GA_LOW, "P28T": _GA_LOW, "PA32": replace(_GA_LOW, length=42),
    "SR22": _GA_LOW, "SR20": _GA_LOW, "S22T": _GA_LOW, "BE36": replace(_GA_LOW, length=40), "BE33": _GA_LOW, "BE35": _GA_LOW,
    "M20P": _GA_LOW, "M20T": _GA_LOW, "DA40": _GA_LOW, "RV10": _GA_LOW, "RV7": replace(_GA_LOW, length=34), "COL4": _GA_LOW,
    "PA46": replace(_GA_LOW, length=44), "P46T": replace(_GA_LOW, length=44),
    # Piston twins
    "C402": _TWIN_PROP, "C310": _TWIN_PROP, "C340": _TWIN_PROP, "C414": _TWIN_PROP, "C421": _TWIN_PROP,
    "BE58": _TWIN_PROP, "BE55": _TWIN_PROP, "BE76": replace(_TWIN_PROP, length=42, tail="t_tail"),
    "PA34": _TWIN_PROP, "PA44": replace(_TWIN_PROP, length=42, tail="t_tail"), "PA31": _TWIN_PROP,
    "DA42": _TWIN_PROP, "DA62": _TWIN_PROP,
    # Business jets (rear engines, T-tail, winglets)
    "E55P": replace(_REAR_JET, length=46, winglets=True), "E50P": replace(_REAR_JET, length=40, winglets=True),
    "CL30": replace(_REAR_JET, length=58, height=7, winglets=True), "CL35": replace(_REAR_JET, length=58, height=7, winglets=True),
    "CL60": replace(_REAR_JET, length=62, height=7, winglets=True),
    "GLF4": replace(_REAR_JET, length=66, height=7, winglets=True), "GLF5": replace(_REAR_JET, length=70, height=7, winglets=True),
    "GLF6": replace(_REAR_JET, length=70, height=7, winglets=True), "GL5T": replace(_REAR_JET, length=70, height=7, winglets=True),
    "GL7T": replace(_REAR_JET, length=72, height=7, winglets=True), "GLEX": replace(_REAR_JET, length=70, height=7, winglets=True),
    "C25A": replace(_REAR_JET, length=44, winglets=True), "C25B": replace(_REAR_JET, length=46, winglets=True),
    "C56X": replace(_REAR_JET, length=48, winglets=True), "C680": replace(_REAR_JET, length=52, winglets=True),
    "C68A": replace(_REAR_JET, length=52, winglets=True), "C700": replace(_REAR_JET, length=56, winglets=True),
    "C750": replace(_REAR_JET, length=56, winglets=True),
    "LJ45": replace(_REAR_JET, length=48, winglets=True), "LJ60": replace(_REAR_JET, length=50, winglets=True),
    "HDJT": replace(_REAR_JET, length=40, winglets=True), "PRM1": replace(_REAR_JET, length=44, winglets=True),
    "FA7X": replace(_REAR_JET, length=58, height=7, engines=3, winglets=True), "F2TH": replace(_REAR_JET, length=56, height=7, winglets=True),
    "FA50": replace(_REAR_JET, length=54, height=7, engines=3, winglets=True), "PC24": replace(_REAR_JET, length=48, winglets=True),
    # Helicopters
    "R44": replace(_HELI, length=44, height=7), "R66": replace(_HELI, length=46, height=7),
    "EC35": _HELI, "EC45": _HELI, "A109": _HELI, "S76": replace(_HELI, length=58),
    "B06": replace(_HELI, length=50), "B407": replace(_HELI, length=52), "AS50": _HELI, "H60": replace(_HELI, length=62, height=9),
}

GENERIC = _JET  # unknown type -> generic twin-jet


def params_for(type_code: str | None) -> SpriteParams:
    return TYPE_PARAMS.get((type_code or "").upper(), GENERIC)


def colors_for(airline_icao: str | None) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    return AIRLINE_COLORS.get((airline_icao or "").upper(), (DEFAULT_TAIL, DEFAULT_STRIPE))


# ---- the builder ----------------------------------------------------------------
def build_sprite(p: SpriteParams, tail_color=DEFAULT_TAIL, stripe_color=DEFAULT_STRIPE) -> Image.Image:
    img = Image.new("RGBA", (SPRITE_W, SPRITE_H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if p.kind == "heli":
        _draw_heli(d, p, tail_color, stripe_color)
    else:
        _draw_plane(d, p, tail_color, stripe_color)
    return img


def _draw_plane(d: ImageDraw.ImageDraw, p: SpriteParams, tail_c, stripe_c) -> None:
    h = p.height
    top, bot = YC - h // 2, YC - h // 2 + h - 1          # inclusive fuselage rows
    x_tip = 2                                             # nose tip
    x_n = x_tip + max(3, h - 1)                           # nose -> straight body
    x_end = x_tip + p.length                              # tail end (rear of fuselage)
    tail_len = max(6, int(h * 1.6))
    x_t = x_end - tail_len                                # body -> tail cone
    small = h <= 6

    # tail cone: bottom rises to meet the top (airliner up-swept tail)
    d.polygon([(x_t, top), (x_end, top), (x_end, top + max(1, h // 4)), (x_t, bot)], fill=BODY)
    # main body
    d.rectangle([x_n, top, x_t, bot], fill=BODY)
    # nose: rounded-ish wedge
    d.polygon([(x_n, top), (x_tip, YC - (0 if small else 1)), (x_tip, YC + 1), (x_n, bot)], fill=BODY)
    if not small:
        d.point((x_tip + 1, top + 1), fill=(0, 0, 0, 0))

    # wing (near wing sweeps back and down toward the viewer)
    body_len = x_t - x_n
    x_r = x_n + int(body_len * (0.36 if p.engine_pos == "tail" else 0.30))
    rw = max(5, int(p.length * 0.17))
    sweep = max(3, int(p.length * 0.12))
    drop = 4 if small else (6 if h <= 7 else 8)
    if p.high_wing:
        # a slab on top of the fuselage, slightly forward of the root
        d.rectangle([x_r - 2, top - 2, x_r + rw + sweep, top - 1], fill=BODY_SHADE)
        d.line([(x_r + rw // 2, top - 1), (x_r + rw // 2 + 2, bot + 1)], fill=NACELLE)  # strut
        wing_low_y = None
    else:
        tipw = max(3, rw // 3)
        d.polygon([(x_r, bot), (x_r + rw, bot), (x_r + rw + sweep, bot + drop), (x_r + rw + sweep - tipw, bot + drop)],
                  fill=BODY_SHADE)
        wing_low_y = bot + drop
        if p.winglets:
            d.line([(x_r + rw + sweep, bot + drop), (x_r + rw + sweep + 1, bot + drop - 3)], fill=stripe_c)

    # tail fin + stabilizer
    fin_h = max(5, int(h * 1.3))
    fin_x0 = x_end - max(6, int(h * 1.5)) - 2
    d.polygon([(fin_x0, top), (x_end - 3, top - fin_h), (x_end + 2, top - fin_h), (x_end, top)], fill=tail_c)
    if p.tail == "t_tail":
        y = top - fin_h
        d.polygon([(x_end - 7, y), (x_end + 6, y - 1), (x_end + 6, y), (x_end - 5, y + 1)], fill=BODY_SHADE)
    else:
        y = top + h // 3
        d.polygon([(x_end - 6, y), (x_end + 6, y - 2), (x_end + 6, y - 1), (x_end - 1, y + 1)], fill=BODY_SHADE)

    # engines
    if p.engine_pos == "wing" and p.engines >= 1 and wing_low_y is not None:
        nl = max(7, int(p.length * 0.15))
        nh = 3 if small else (5 if h <= 8 else 6)
        pods = [(x_r - nl // 3, bot + 3)]
        if p.engines >= 4:
            pods.append((x_r + rw // 2 + sweep // 2, bot + drop - nh + 1))
        for ex, ey in pods:
            d.line([(ex + nl // 2, bot + 1), (ex + nl // 2, ey)], fill=NACELLE)  # pylon
            if p.prop:
                d.rectangle([ex, ey, ex + nl - 2, ey + nh], fill=NACELLE)
                d.line([(ex - 1, ey - 2), (ex - 1, ey + nh + 2)], fill=BODY_SHADE)  # propeller disc
            else:
                d.rounded_rectangle([ex, ey, ex + nl, ey + nh], radius=2, fill=NACELLE)
                d.rectangle([ex, ey + 1, ex + 1, ey + nh - 1], fill=INTAKE)
    elif p.engine_pos == "wing" and p.engines >= 1 and p.high_wing:
        # turboprop nacelles hang under the high wing, in front of the fuselage
        nl = max(8, int(p.length * 0.16))
        ex = x_r + 1
        d.rectangle([ex, top - 1, ex + nl, top + 2], fill=NACELLE)
        d.line([(ex - 1, top - 5), (ex - 1, top + 5)], fill=BODY_SHADE)
        if p.engines >= 2:
            d.rectangle([ex + nl + 3, top - 1, ex + nl + 5, top], fill=NACELLE)  # far engine peeking out
    elif p.engine_pos == "tail" and p.engines >= 1:
        nl = max(8, int(p.length * 0.18))
        nh = 3 if small else 4
        ex = x_t - nl + 2
        d.rounded_rectangle([ex, top - nh, ex + nl, top], radius=2, fill=NACELLE)
        d.rectangle([ex, top - nh + 1, ex + 1, top - 1], fill=INTAKE)
        if p.engines >= 3:  # centre engine in the tail (Falcon)
            d.rectangle([x_end - 4, top - 2, x_end - 1, top], fill=NACELLE)
    elif p.engine_pos == "nose" and p.prop:
        d.line([(x_tip, YC - 4), (x_tip, YC + 4)], fill=BODY_SHADE)
        d.point((x_tip + 1, YC), fill=INTAKE)

    # cockpit, windows, cheatline
    d.line([(x_n - 1, top + 1), (x_n + 1, top + 1)], fill=GLASS)
    if not small:
        for x in range(x_n + 5, x_t - 1, 3):
            d.point((x, top + 2), fill=GLASS)
        d.line([(x_n + 1, bot - 1), (x_t + 1, bot - 1)], fill=stripe_c)
    else:
        d.point((x_n + 3, top + 1), fill=GLASS)
        d.line([(x_n + 1, bot), (x_t, bot)], fill=stripe_c)


def _draw_heli(d: ImageDraw.ImageDraw, p: SpriteParams, tail_c, stripe_c) -> None:
    h = p.height
    top, bot = YC - h // 2 + 1, YC - h // 2 + h
    x0 = 4
    cab_w = int(p.length * 0.45)
    # cabin (rounded), tail boom, tail fin + rotor
    d.rounded_rectangle([x0, top, x0 + cab_w, bot], radius=3, fill=BODY)
    d.polygon([(x0 + cab_w - 2, top + 2), (x0 + p.length, YC - 1), (x0 + p.length, YC + 1), (x0 + cab_w - 2, bot - 1)], fill=BODY_SHADE)
    d.polygon([(x0 + p.length - 6, YC - 1), (x0 + p.length - 2, YC - 7), (x0 + p.length + 1, YC - 7), (x0 + p.length, YC)], fill=tail_c)
    d.line([(x0 + p.length + 1, YC - 10), (x0 + p.length + 1, YC - 4)], fill=BODY_SHADE)
    # windows + stripe
    d.rectangle([x0 + 2, top + 1, x0 + cab_w // 2, top + 2], fill=GLASS)
    d.line([(x0 + 1, bot - 1), (x0 + cab_w - 1, bot - 1)], fill=stripe_c)
    # mast + main rotor
    mx = x0 + cab_w // 2
    d.rectangle([mx - 1, top - 3, mx, top - 1], fill=NACELLE)
    d.line([(mx - cab_w, top - 4), (mx + cab_w, top - 4)], fill=BODY_SHADE)
    d.line([(mx - cab_w // 2, top - 5), (mx + cab_w // 2, top - 5)], fill=BODY_SHADE)
    # skids
    d.line([(x0 + 2, bot + 3), (x0 + cab_w - 2, bot + 3)], fill=NACELLE)
    d.line([(x0 + 5, bot + 1), (x0 + 5, bot + 3)], fill=NACELLE)
    d.line([(x0 + cab_w - 5, bot + 1), (x0 + cab_w - 5, bot + 3)], fill=NACELLE)


@lru_cache(maxsize=256)
def _cached(p: SpriteParams, tail_c, stripe_c) -> Image.Image:
    return build_sprite(p, tail_c, stripe_c)


def sprite_for(type_code: str | None, airline_icao: str | None = None) -> Image.Image:
    tail_c, stripe_c = colors_for(airline_icao)
    return _cached(params_for(type_code), tail_c, stripe_c)


# ---- review sheet -----------------------------------------------------------------
def render_sheet(scale: int = 4, cols: int = 3) -> Image.Image:
    """Every entry of TYPE_PARAMS (plus GENERIC), LED-look, labelled. For eyeballing."""
    import numpy as np
    from PIL import ImageFont
    from .sinks.simulator import led_image
    from .data.aircraft_types import type_name
    from . import fonts

    entries = list(TYPE_PARAMS.items()) + [("????", GENERIC)]
    label_font = ImageFont.truetype(fonts.SMALL.path, 16)
    tile_w, tile_h = SPRITE_W * scale, SPRITE_H * scale + 22
    rows = (len(entries) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * (tile_w + 12) + 12, rows * (tile_h + 12) + 12), (20, 20, 22))
    sd = ImageDraw.Draw(sheet)
    for i, (code, p) in enumerate(entries):
        cx, cy = 12 + (i % cols) * (tile_w + 12), 12 + (i // cols) * (tile_h + 12)
        spr = build_sprite(p, *colors_for("JBU" if p.kind == "plane" and not p.prop else None))
        rgb = Image.new("RGB", spr.size, (0, 0, 0))
        rgb.paste(spr, (0, 0), spr)
        sheet.paste(led_image(np.asarray(rgb), scale), (cx, cy))
        sd.text((cx, cy + SPRITE_H * scale + 4), f"{code}  {type_name(code) if code != '????' else 'UNKNOWN'}",
                font=label_font, fill=(220, 220, 220))
    return sheet
