"""Runtime settings: what the phone UI can change, persisted to ~/.panelwall/settings.json.

Threading contract: the web thread WRITES (through the set_* methods, under a
lock, bumping `revision`), the scheduler thread READS (plain attribute reads,
which are atomic in CPython). Location changes are also pushed into
CONFIG.location so the data feeds and channels see them without knowing about
this object.

Display modes:
  manual (default) - `channel` is pinned; nothing else is ever shown.
  auto             - round-robin over `cycle` (None = every loaded channel), `dwell_seconds`
                     on each, skipping channels with nothing to show; when `alerts` is on, a
                     channel spiking to priority >= 20 (score, new aircraft) interrupts briefly.

Persisted keys: mode, channel, cycle, dwell_seconds, alerts, brightness, quiet{start,end,level},
lat, lon, radius_nm. `force` (show one channel for N seconds, API only) is not persisted.
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, time as dtime
from pathlib import Path

from .config import CONFIG

DEFAULT_PATH = Path(os.environ.get("PW_SETTINGS") or "~/.panelwall/settings.json").expanduser()

QUIET_DEFAULT = {"start": "23:00", "end": "07:00", "level": 0x40}


def _parse_hhmm(s: str) -> dtime:
    h, m = s.split(":")
    return dtime(int(h), int(m))


class Settings:
    def __init__(self, path: Path | str | None = None, autoload: bool = True):
        self.path = Path(path).expanduser() if path else DEFAULT_PATH
        self._lock = threading.RLock()
        self.revision = 0
        self.mode: str = "manual"                       # manual | auto
        self.channel: str = "flightwall"                # pinned channel in manual mode
        self.cycle: list[str] | None = None             # auto mode: channels to rotate; None = all loaded
        self.dwell_seconds: float = 20.0                # auto mode: time on each channel
        self.alerts: bool = True                        # auto mode: let priority>=20 spikes interrupt
        self.brightness: int = CONFIG.display.brightness
        self.quiet: dict = dict(QUIET_DEFAULT)
        self.lat: float = CONFIG.location.lat
        self.lon: float = CONFIG.location.lon
        self.radius_nm: float = CONFIG.location.radius_nm
        self._force: tuple[str, float] | None = None    # (channel name, until epoch)
        self.load_error: str | None = None
        if autoload:
            self.load()

    # ---- persistence -----------------------------------------------------------
    def load(self) -> bool:
        try:
            data = json.loads(self.path.read_text())
        except FileNotFoundError:
            return False
        except Exception as e:  # corrupt file: keep defaults, report it
            self.load_error = f"{type(e).__name__}: {e}"
            return False
        with self._lock:
            if data.get("mode") in ("manual", "auto"):
                self.mode = data["mode"]
            if isinstance(data.get("channel"), str) and data["channel"]:
                self.channel = data["channel"]
            cyc = data.get("cycle", data.get("enabled"))          # 'enabled' = pre-mode name for the same list
            if isinstance(cyc, list):
                self.cycle = [str(x) for x in cyc]
            if isinstance(data.get("dwell_seconds"), (int, float)):
                self.dwell_seconds = max(3.0, float(data["dwell_seconds"]))
            if isinstance(data.get("alerts"), bool):
                self.alerts = data["alerts"]
            if isinstance(data.get("brightness"), int):
                self.brightness = max(0, min(255, data["brightness"]))
            if isinstance(data.get("quiet"), dict):
                self._set_quiet_unlocked(data["quiet"])
            loc = {k: data[k] for k in ("lat", "lon", "radius_nm") if isinstance(data.get(k), (int, float))}
            if loc:
                self._set_location_unlocked(loc.get("lat"), loc.get("lon"), loc.get("radius_nm"))
        return True

    def save(self) -> None:
        with self._lock:
            payload = json.dumps(self.to_persist(), indent=1)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(payload)
            os.replace(tmp, self.path)
        except OSError as e:
            self.load_error = f"save failed: {e}"

    def to_persist(self) -> dict:
        return {"mode": self.mode, "channel": self.channel, "cycle": self.cycle, "dwell_seconds": self.dwell_seconds,
                "alerts": self.alerts, "brightness": self.brightness, "quiet": dict(self.quiet),
                "lat": self.lat, "lon": self.lon, "radius_nm": self.radius_nm}

    # ---- writers (web thread) --------------------------------------------------
    def _bump(self):
        self.revision += 1

    def set_mode(self, mode: str) -> None:
        if mode not in ("manual", "auto"):
            raise ValueError("mode must be 'manual' or 'auto'")
        with self._lock:
            self.mode = mode
            self._bump()
        self.save()

    def select_channel(self, name: str) -> None:
        """The user tapped a panel: pin it and drop into manual mode."""
        with self._lock:
            self.channel = str(name)
            self.mode = "manual"
            self._force = None
            self._bump()
        self.save()

    def set_cycle(self, names: list[str] | None = ..., dwell_seconds: float | None = None, alerts: bool | None = None) -> None:
        with self._lock:
            if names is not ...:
                self.cycle = None if names is None else [str(n) for n in names]
            if dwell_seconds is not None:
                self.dwell_seconds = max(3.0, min(3600.0, float(dwell_seconds)))
            if alerts is not None:
                self.alerts = bool(alerts)
            self._bump()
        self.save()

    # kept for the old API name: the 'enabled' list is the auto-cycle list
    def set_enabled(self, names: list[str] | None) -> None:
        self.set_cycle(names)

    @property
    def enabled(self) -> list[str] | None:
        return self.cycle

    def set_brightness(self, level: int) -> None:
        with self._lock:
            self.brightness = max(0, min(255, int(level)))
            self._bump()
        self.save()

    def _set_quiet_unlocked(self, q: dict) -> None:
        new = dict(self.quiet)
        for k in ("start", "end"):
            if k in q and q[k] is not None:
                _parse_hhmm(str(q[k]))               # validate
                new[k] = str(q[k])
        if q.get("level") is not None:
            new["level"] = max(0, min(255, int(q["level"])))
        self.quiet = new

    def set_quiet(self, q: dict) -> None:
        with self._lock:
            self._set_quiet_unlocked(q)
            self._bump()
        self.save()

    def _set_location_unlocked(self, lat, lon, radius_nm) -> None:
        if lat is not None:
            self.lat = max(-90.0, min(90.0, float(lat)))
        if lon is not None:
            self.lon = max(-180.0, min(180.0, float(lon)))
        if radius_nm is not None:
            self.radius_nm = max(1.0, float(radius_nm))
        CONFIG.location.lat, CONFIG.location.lon, CONFIG.location.radius_nm = self.lat, self.lon, self.radius_nm

    def set_location(self, lat=None, lon=None, radius_nm=None) -> None:
        with self._lock:
            self._set_location_unlocked(lat, lon, radius_nm)
            self._bump()
        self.save()

    def force_channel(self, name: str | None, seconds: float = 60.0) -> None:
        with self._lock:
            self._force = None if not name else (str(name), time.time() + max(1.0, float(seconds)))
            self._bump()

    # ---- readers (scheduler thread) ---------------------------------------------
    def in_cycle(self, name: str) -> bool:
        cyc = self.cycle
        return True if cyc is None else name in cyc

    is_enabled = in_cycle

    def forced(self, now: float | None = None) -> str | None:
        f = self._force
        if f is None:
            return None
        if (now if now is not None else time.time()) >= f[1]:
            return None
        return f[0]

    def forced_until(self) -> float | None:
        f = self._force
        return f[1] if f else None

    def effective_brightness(self, now: datetime | None = None) -> int:
        """Quiet-hours level between start and end (may wrap midnight), else brightness."""
        now = now or datetime.now()
        q = self.quiet
        try:
            start, end = _parse_hhmm(q["start"]), _parse_hhmm(q["end"])
        except (KeyError, ValueError):
            return self.brightness
        t = now.time().replace(second=0, microsecond=0)
        quiet = (start <= t < end) if start <= end else (t >= start or t < end)
        return int(q.get("level", QUIET_DEFAULT["level"])) if quiet else self.brightness

    def snapshot(self) -> dict:
        with self._lock:
            d = self.to_persist()
            d["force"] = {"channel": self._force[0], "until": self._force[1]} if self.forced() else None
            d["effective_brightness"] = self.effective_brightness()
            d["revision"] = self.revision
            d["path"] = str(self.path)
            return d
