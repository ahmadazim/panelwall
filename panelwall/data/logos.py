"""Team crests for the sports cards: ESPN logo URLs -> small LED-ready tiles, fetched in the background.

    tile = LOGOS.get(url, 22)      # RGBA 22x22 or None (not fetched yet -> caller draws a badge)

The render thread never waits: a miss queues the URL and returns None; one daemon thread downloads
(ESPN's CDN, keyless), processes and caches. Processing for a 64-row LED wall:
  * crop to the logo's opaque area, fit into size x size (aspect kept, centred)
  * Lanczos downscale, then alpha thresholded to fully on/off (half-transparent edge pixels
    look like dirt on LEDs)
  * a mostly-dark logo gets a 1 px light outline so it doesn't vanish on the black panel
Cache: ~/.panelwall/logos/<sha1(url)>_<size>.png (persists across restarts, so each crest is
downloaded once ever); fixtures/logos/ is also searched so demos and tests render crests offline.
"""

from __future__ import annotations

import hashlib
import io
import os
import queue
import threading
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

CACHE_DIR = Path(os.environ.get("PW_LOGO_CACHE") or "~/.panelwall/logos").expanduser()
FIXTURE_DIR = Path(__file__).resolve().parent.parent.parent / "fixtures" / "logos"


def cache_name(url: str, size: int) -> str:
    return f"{hashlib.sha1(url.encode()).hexdigest()[:16]}_{size}.png"


def _fit(im: Image.Image, size: int, inner: int) -> Image.Image:
    """Logo -> size x size tile with the logo fitted into inner x inner, centred, binary alpha."""
    w, h = im.size
    scale = inner / max(w, h)
    tw, th = max(1, round(w * scale)), max(1, round(h * scale))
    small = im.resize((tw, th), Image.LANCZOS)
    tile = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    tile.paste(small, ((size - tw) // 2, (size - th) // 2), small)
    a = np.asarray(tile.getchannel("A"))
    cut = 110 if (a >= 110).sum() >= 0.18 * size * size else 40      # thin line-art crest: keep faint strokes
    tile.putalpha(Image.fromarray(np.where(a >= cut, 255, 0).astype(np.uint8)))
    return tile


def process(raw: bytes, size: int) -> Image.Image:
    """PNG bytes -> size x size RGBA tile tuned for LEDs."""
    im = Image.open(io.BytesIO(raw)).convert("RGBA")
    bbox = im.getchannel("A").point(lambda a: 255 if a > 24 else 0).getbbox()
    if bbox:
        im = im.crop(bbox)
    tile = _fit(im, size, size)
    arr = np.asarray(tile).astype(np.float32)
    on = arr[:, :, 3] > 0
    if on.any():
        lum = (0.3 * arr[:, :, 0] + 0.59 * arr[:, :, 1] + 0.11 * arr[:, :, 2])[on].mean()
        if lum < 55:                                   # mostly-dark crest: shrink 1 px a side and ring it
            tile = _fit(im, size, size - 2)
            edge = tile.getchannel("A").filter(ImageFilter.MaxFilter(3))
            out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
            out.paste(Image.new("RGBA", (size, size), (150, 150, 160, 255)), (0, 0), edge)
            out.paste(tile, (0, 0), tile)
            tile = out
    return tile


class LogoCache:
    def __init__(self, fetch: bool = True, cache_dir: Path | None = None):
        self.fetch = fetch
        self.cache_dir = cache_dir or CACHE_DIR
        self._mem: dict[tuple[str, int], Image.Image | None] = {}
        self._pending: set[tuple[str, int]] = set()
        self._q: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None
        self.last_error: str | None = None
        self._lock = threading.Lock()

    def _load_disk(self, url: str, size: int) -> Image.Image | None:
        name = cache_name(url, size)
        for d in (self.cache_dir, FIXTURE_DIR):
            p = d / name
            if p.exists():
                try:
                    return Image.open(p).convert("RGBA")
                except OSError:
                    continue
        return None

    def get(self, url: str | None, size: int = 22) -> Image.Image | None:
        if not url:
            return None
        key = (url, size)
        if key in self._mem:
            return self._mem[key]
        tile = self._load_disk(url, size)
        if tile is not None:
            self._mem[key] = tile
            return tile
        if self.fetch:
            with self._lock:
                if key not in self._pending:
                    self._pending.add(key)
                    self._q.put(key)
                    if self._thread is None or not self._thread.is_alive():
                        self._thread = threading.Thread(target=self._worker, daemon=True, name="logo-fetch")
                        self._thread.start()
        return None

    def _worker(self) -> None:
        while True:
            try:
                url, size = self._q.get(timeout=30)
            except queue.Empty:
                return
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "panelwall/0.1"})
                with urllib.request.urlopen(req, timeout=10) as r:
                    tile = process(r.read(), size)
                self.cache_dir.mkdir(parents=True, exist_ok=True)
                tile.save(self.cache_dir / cache_name(url, size))
                self._mem[(url, size)] = tile
                self.last_error = None
            except Exception as e:           # a missing crest is cosmetic: keep the badge, don't retry this run
                self._mem[(url, size)] = None
                self.last_error = f"logo {type(e).__name__}: {e}"
            finally:
                with self._lock:
                    self._pending.discard((url, size))


LOGOS = LogoCache()
