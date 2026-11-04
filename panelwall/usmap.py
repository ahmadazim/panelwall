"""US state map and chamber charts at LED resolution.

    index, codes = state_index(95, 62)     # numpy (h, w) of state numbers (0 = sea), cached
    img = render_map({"MA": (40,100,235), ...}, 95, 62, default=(28,28,34))
    sil = state_silhouette("OH", 56, 56)   # one state filled as a mask, aspect kept, centred
    seats = hemicycle(435, 120, 60)        # [(x, y)] seat positions, ordered left -> right

The outlines come from assets/data/us_states.json (tools/build_us_map.py: Census 2010 boundaries,
Albers projection, AK/HI insets). Rasterising once into an index map makes every recolour a
numpy lookup, so a full map costs well under a millisecond per frame. States too small to own a
pixel at the requested size (Delaware at 95 px is the edge case) get their centroid pixel.
"""

from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ASSET = Path(__file__).resolve().parent.parent / "assets" / "data" / "us_states.json"


@lru_cache(maxsize=1)
def _shapes() -> tuple[dict, float]:
    d = json.loads(ASSET.read_text())
    return d["states"], float(d["meta"]["height"])


def aspect() -> float:
    """height / width of the whole map."""
    return _shapes()[1]


def codes() -> list[str]:
    return sorted(_shapes()[0])


@lru_cache(maxsize=8)
def state_index(w: int, h: int) -> tuple[np.ndarray, tuple]:
    shapes, _ = _shapes()
    cs = tuple(sorted(shapes))
    s = min((w - 1), (h - 1) / aspect())
    ox = (w - 1 - s) / 2
    oy = (h - 1 - s * aspect()) / 2
    im = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(im)
    for i, c in enumerate(cs, 1):
        for ring in shapes[c]:
            d.polygon([(ox + x * s, oy + y * s) for x, y in ring], fill=i)
    idx = np.asarray(im).copy()
    for i, c in enumerate(cs, 1):                       # every state owns at least one pixel
        if not (idx == i).any():
            pts = [p for ring in shapes[c] for p in ring]
            cx = ox + sum(p[0] for p in pts) / len(pts) * s
            cy = oy + sum(p[1] for p in pts) / len(pts) * s
            idx[min(h - 1, max(0, round(cy))), min(w - 1, max(0, round(cx)))] = i
    return idx, cs


@lru_cache(maxsize=8)
def borders(w: int, h: int) -> np.ndarray:
    """True where a pixel touches a different state (right or below): darkened to separate states."""
    idx, _ = state_index(w, h)
    b = np.zeros_like(idx, bool)
    b[:, 1:] |= (idx[:, 1:] != idx[:, :-1]) & (idx[:, 1:] > 0) & (idx[:, :-1] > 0)
    b[1:, :] |= (idx[1:, :] != idx[:-1, :]) & (idx[1:, :] > 0) & (idx[:-1, :] > 0)
    return b


def render_map(colors: dict, w: int, h: int, default=(28, 28, 34), border: float = 0.5) -> np.ndarray:
    """(h, w, 3) uint8; states not in `colors` get `default`; sea is black."""
    idx, cs = state_index(w, h)
    pal = np.zeros((len(cs) + 1, 3), np.float32)
    for i, c in enumerate(cs, 1):
        pal[i] = colors.get(c, default)
    rgb = pal[idx]
    b = borders(w, h)
    rgb[b] *= border
    return rgb.astype(np.uint8)


def state_pixels(code: str, w: int, h: int) -> np.ndarray:
    idx, cs = state_index(w, h)
    return idx == (cs.index(code) + 1) if code in cs else np.zeros_like(idx, bool)


@lru_cache(maxsize=64)
def state_silhouette(code: str, w: int, h: int) -> np.ndarray | None:
    """Bool mask (h, w) of one state scaled to fill the box (aspect kept, centred)."""
    shapes, _ = _shapes()
    if code not in shapes:
        return None
    rings = shapes[code]
    if code in ("AK", "HI"):                              # use only the larger islands' bbox for scale
        pass
    xs = [x for r in rings for x, _ in r]
    ys = [y for r in rings for _, y in r]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    s = min((w - 1) / max(1e-9, x1 - x0), (h - 1) / max(1e-9, y1 - y0))
    ox = (w - 1 - (x1 - x0) * s) / 2
    oy = (h - 1 - (y1 - y0) * s) / 2
    im = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(im)
    for r in rings:
        d.polygon([(ox + (x - x0) * s, oy + (y - y0) * s) for x, y in r], fill=255)
    return np.asarray(im) > 0


@lru_cache(maxsize=8)
def hemicycle(n: int, w: int, h: int, spacing: float = 2.0, inner_frac: float = 0.36) -> tuple:
    """Parliament-chart seat positions: n seats on concentric half rings in a w x h box (centre bottom),
    returned ordered by angle from the left end to the right end (so party blocks fill from the sides)."""
    cx, cy = (w - 1) / 2, h - 1
    r_out = min(w / 2 - 1, h - 1)
    r_in = r_out * inner_frac
    rings = []
    r = r_in
    while r <= r_out + 1e-6:
        rings.append(r)
        r += spacing
    lengths = [math.pi * r for r in rings]
    total = sum(lengths)
    counts = [max(1, round(n * L / total)) for L in lengths]
    while sum(counts) > n:
        counts[counts.index(max(counts))] -= 1
    while sum(counts) < n:
        counts[-1] += 1
    seats = []
    for r, k in zip(rings, counts):
        for j in range(k):
            a = math.pi * (j + 0.5) / k                   # 0 = left end ... pi = right end
            seats.append((a, round(cx - r * math.cos(a)), round(cy - r * math.sin(a))))
    seats.sort(key=lambda t: (t[0], -math.hypot(t[1] - cx, t[2] - cy)))
    return tuple((x, y) for _, x, y in seats)
