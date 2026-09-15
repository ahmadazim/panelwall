"""Shared plumbing for the background pollers: demand-driven pausing and 429 backoff.

Why: with six channels loaded, every feed used to poll all the time, even though
only one panel is on screen. Free APIs (adsb.lol, MBTA without a key, ESPN)
rate-limited us. Now:

  * A feed knows which channels read it (`register`). It polls only while at
    least one of them is `active` - the scheduler marks a channel active when it
    can currently be shown (manual mode: the pinned panel; auto mode: the cycle
    members; plus any forced channel). Otherwise the feed sleeps, checking every
    PAUSE_CHECK seconds, and fetches immediately when it is wanted again.
  * `Backoff` turns an HTTP 429 (or a transient 403) into a wait: Retry-After if
    the server sent one, else 15 s doubling to 5 min. The feed's poll loop waits
    max(interval, backoff).
"""

from __future__ import annotations

import threading
import time

PAUSE_CHECK = 2.0
BACKOFF_MIN, BACKOFF_MAX = 15.0, 300.0


class Backoff:
    def __init__(self):
        self.until = 0.0
        self._next = BACKOFF_MIN

    def note(self, retry_after: float | None = None) -> float:
        """Record a rate-limit response; returns the seconds we will wait."""
        wait = float(retry_after) if retry_after else self._next
        self._next = min(BACKOFF_MAX, self._next * 2)
        self.until = time.time() + wait
        return wait

    def reset(self) -> None:
        self._next = BACKOFF_MIN

    def remaining(self) -> float:
        return max(0.0, self.until - time.time())


def retry_after_seconds(headers) -> float | None:
    try:
        v = headers.get("Retry-After") if headers else None
        return float(v) if v else None
    except (TypeError, ValueError):
        return None


class DemandPoller:
    """Mixin for feeds. Subclasses set `_stop` (threading.Event) and call `_sleep_or_pause`."""

    users: list
    paused: bool = False

    def _init_demand(self) -> None:
        self.users = []
        self.paused = False
        self._stop = threading.Event()

    def register(self, channel) -> None:
        if channel not in self.users:
            self.users.append(channel)

    def wanted(self) -> bool:
        """True when no channel is registered (demos, tests) or any registered one is active."""
        return not self.users or any(getattr(u, "active", True) for u in self.users)

    def _wait_wanted(self) -> None:
        """Block while nobody needs this feed. Returns as soon as someone does (or on stop)."""
        while not self._stop.is_set() and not self.wanted():
            self.paused = True
            self._stop.wait(PAUSE_CHECK)
        self.paused = False

    def _sleep_or_pause(self, seconds: float) -> None:
        """Wait `seconds`, waking early only to stop; then block further while unwanted."""
        self._stop.wait(seconds)
        self._wait_wanted()
