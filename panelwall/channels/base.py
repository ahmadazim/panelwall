from __future__ import annotations

from ..framebuffer import Frame


class Channel:
    """A thing that can draw the screen.

    tick(dt) is called every frame; do cheap work here (animation timers).
    Slow work (HTTP) must happen in a background thread - see FlightsChannel.
    priority() lets the scheduler pick between channels: higher wins, <=0 means
    'nothing to show right now'.
    """

    name = "channel"

    def tick(self, dt: float) -> None:
        pass

    def priority(self) -> int:
        return 1

    def render(self, frame: Frame) -> None:
        raise NotImplementedError

    def status(self) -> dict:
        """For the control server: {'updated_at': epoch|None, 'last_error': str|None, ...}."""
        return {}

    def close(self) -> None:
        pass
