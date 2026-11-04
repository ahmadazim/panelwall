"""Build assets/data/us_states.json - projected, simplified US state outlines for the election map.

    python tools/build_us_map.py [path/to/gz_2010_us_040_00_20m.json]

Source: US Census Bureau 2010 cartographic boundary file (20m), public domain, as GeoJSON
(https://eric.clst.org/assets/wiki/uploads/Stuff/gz_2010_us_040_00_20m.json). Downloaded if no
path is given. Projection: Albers equal-area conic like most US election maps (contiguous states:
standard parallels 29.5/45.5 N, centre 96 W); Alaska (scaled to 35 %) and Hawaii are re-projected
with their own parallels and placed as insets bottom-left. Coordinates are normalised so the
whole map is 1.0 wide; y grows downward. Rings are Douglas-Peucker simplified to ~0.08 % of
the width, which is invisible at LED resolution and keeps the asset small.
"""

from __future__ import annotations

import json
import math
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "data" / "us_states.json"
URL = "https://eric.clst.org/assets/wiki/uploads/Stuff/gz_2010_us_040_00_20m.json"

FIPS = {"01": "AL", "02": "AK", "04": "AZ", "05": "AR", "06": "CA", "08": "CO", "09": "CT", "10": "DE", "11": "DC",
        "12": "FL", "13": "GA", "15": "HI", "16": "ID", "17": "IL", "18": "IN", "19": "IA", "20": "KS", "21": "KY",
        "22": "LA", "23": "ME", "24": "MD", "25": "MA", "26": "MI", "27": "MN", "28": "MS", "29": "MO", "30": "MT",
        "31": "NE", "32": "NV", "33": "NH", "34": "NJ", "35": "NM", "36": "NY", "37": "NC", "38": "ND", "39": "OH",
        "40": "OK", "41": "OR", "42": "PA", "44": "RI", "45": "SC", "46": "SD", "47": "TN", "48": "TX", "49": "UT",
        "50": "VT", "51": "VA", "53": "WA", "54": "WV", "55": "WI", "56": "WY"}


def albers(lat1, lat2, lat0, lon0):
    p1, p2, p0 = map(math.radians, (lat1, lat2, lat0))
    n = (math.sin(p1) + math.sin(p2)) / 2
    c = math.cos(p1) ** 2 + 2 * n * math.sin(p1)
    rho0 = math.sqrt(c - 2 * n * math.sin(p0)) / n

    def proj(lon, lat):
        rho = math.sqrt(c - 2 * n * math.sin(math.radians(lat))) / n
        th = n * math.radians(lon - lon0)
        return rho * math.sin(th), -(rho0 - rho * math.cos(th))      # y down
    return proj


CONUS = albers(29.5, 45.5, 37.5, -96)
AK = albers(55, 65, 50, -154)
HI = albers(8, 18, 3, -157)


def simplify(pts, tol):
    """Douglas-Peucker. A closed ring (first == last) is split at the point farthest from its start,
    otherwise every point's distance to the zero-length start-end segment comes out 0."""
    if len(pts) < 4:
        return pts
    if pts[0] == pts[-1]:
        far = max(range(len(pts)), key=lambda i: (pts[i][0] - pts[0][0]) ** 2 + (pts[i][1] - pts[0][1]) ** 2)
        return _dp(pts[:far + 1], tol)[:-1] + _dp(pts[far:], tol)
    return _dp(pts, tol)


def _dp(pts, tol):
    if len(pts) < 3:
        return pts
    def rec(a, b):
        (x1, y1), (x2, y2) = pts[a], pts[b]
        dx, dy = x2 - x1, y2 - y1
        L = math.hypot(dx, dy) or 1e-12
        best, idx = -1.0, -1
        for i in range(a + 1, b):
            x0, y0 = pts[i]
            d = abs(dy * x0 - dx * y0 + x2 * y1 - y2 * x1) / L
            if d > best:
                best, idx = d, i
        if best > tol:
            return rec(a, idx)[:-1] + rec(idx, b)
        return [pts[a], pts[b]]
    return rec(0, len(pts) - 1)


def main(path: str | None) -> None:
    if path:
        doc = json.loads(Path(path).read_text(encoding="latin-1"))
    else:
        with urllib.request.urlopen(URL, timeout=60) as r:
            doc = json.loads(r.read().decode("latin-1"))
    raw: dict[str, list] = {}
    for f in doc["features"]:
        code = FIPS.get(f["properties"]["STATE"])
        if not code or code == "DC":
            continue
        geom = f["geometry"]
        polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
        proj = AK if code == "AK" else HI if code == "HI" else CONUS
        rings = []
        for poly in polys:
            ring = [(lon - 360 if lon > 0 else lon, lat) for lon, lat in poly[0]]       # outer ring only; Aleutians wrap
            rings.append([proj(lon, lat) for lon, lat in ring])
        raw[code] = rings
    # contiguous bbox
    xs = [x for c, rs in raw.items() if c not in ("AK", "HI") for r in rs for x, _ in r]
    ys = [y for c, rs in raw.items() if c not in ("AK", "HI") for r in rs for _, y in r]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    w = x1 - x0

    def place(code, scale, tx, ty):
        rs = raw[code]
        ax = [x for r in rs for x, _ in r]
        ay = [y for r in rs for _, y in r]
        bx, by = min(ax), max(ay)
        raw[code] = [[((x - bx) * scale + tx, (y - by) * scale + ty) for x, y in r] for r in rs]

    # Alaska: 35 % scale, bottom-left; Hawaii: to its right, bottom
    place("AK", 0.35, x0 + 0.00 * w, y1 + 0.02 * w)
    place("HI", 1.0, x0 + 0.21 * w, y1 + 0.02 * w)
    # Alaska's west tip may poke left of the frame: recompute the global bbox
    allx = [x for rs in raw.values() for r in rs for x, _ in r]
    ally = [y for rs in raw.values() for r in rs for _, y in r]
    gx0, gx1, gy0, gy1 = min(allx), max(allx), min(ally), max(ally)
    W = gx1 - gx0
    tol = 0.0008
    states = {}
    for code, rs in sorted(raw.items()):
        out = []
        for r in rs:
            norm = [((x - gx0) / W, (y - gy0) / W) for x, y in r]
            s = simplify(norm, tol)
            if len(s) >= 3:
                out.append([[round(x, 4), round(y, 4)] for x, y in s])
        states[code] = out
    meta = {"source": "US Census Bureau 2010 cartographic boundary file 1:20,000,000 (public domain)",
            "projection": "Albers equal-area conic; AK (35%) and HI insets bottom-left; x in [0,1], y down",
            "height": round((gy1 - gy0) / W, 4)}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"meta": meta, "states": states}, separators=(",", ":")))
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes), {len(states)} states, aspect 1 : {meta['height']}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
