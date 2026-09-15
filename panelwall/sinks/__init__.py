from .base import Sink
from .simulator import SimulatorSink
from .colorlight import ColorlightSink

__all__ = ["Sink", "SimulatorSink", "ColorlightSink", "make_sink"]


def make_sink(name: str, **kw) -> Sink:
    if name == "sim":
        return SimulatorSink(**kw)
    if name == "colorlight":
        return ColorlightSink(**kw)
    raise ValueError(f"unknown sink {name!r} (expected 'sim' or 'colorlight')")
