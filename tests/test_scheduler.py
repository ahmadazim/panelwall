from datetime import datetime

import numpy as np

from panelwall.channels.base import Channel
from panelwall.framebuffer import Frame, H, W
from panelwall.scheduler import Scheduler, wipe_up
from panelwall.settings import Settings
from panelwall.sinks.base import Sink


class Fake(Channel):
    def __init__(self, name, prio, color):
        self.name, self.prio, self.color = name, prio, color

    def priority(self):
        return self.prio

    def render(self, frame):
        frame.rect([0, 0, W - 1, H - 1], fill=self.color)


class CaptureSink(Sink):
    def __init__(self):
        self.frames, self.brightness = [], None

    def show(self, frame):
        self.frames.append(frame)

    def set_brightness(self, level):
        self.brightness = level


def _sched(chs, settings=None, **kw):
    return Scheduler(chs, CaptureSink(), fps=20, settings=settings, wipe_seconds=0, **kw)


def test_highest_priority_wins_and_zero_hides():
    a, b = Fake("a", 10, (255, 0, 0)), Fake("b", 5, (0, 255, 0))
    s = _sched([a, b])
    assert s.pick(0.0) is a
    a.prio = 0
    s.current = a
    assert s.pick(1.0) is b
    b.prio = 0
    assert s.pick(2.0) is None


def test_equal_priority_rotates_every_rotate_seconds():
    a, b, c = Fake("a", 10, 0), Fake("b", 10, 0), Fake("c", 10, 0)
    s = _sched([a, b, c], rotate_seconds=20)
    f = Frame()
    s.step(f, 0.0, 0.05)
    assert s.current is a
    s.step(f, 19.0, 0.05)
    assert s.current is a
    s.step(f, 20.0, 0.05)
    assert s.current is b
    s.step(f, 40.5, 0.05)
    assert s.current is c
    s.step(f, 61.0, 0.05)
    assert s.current is a


def test_higher_priority_preempts_immediately_but_not_within_hold():
    a, b = Fake("a", 10, 0), Fake("b", 0, 0)
    s = _sched([a, b], min_hold=8)
    f = Frame()
    s.step(f, 0.0, 0.05)
    assert s.current is a
    b.prio = 25                                  # detail mode pops
    s.step(f, 1.0, 0.05)
    assert s.current is b                        # preempts at once
    b.prio = 0                                   # ...and vanishes
    s.step(f, 2.0, 0.05)
    assert s.current is a
    b.prio = 25                                  # blinks back 1 s later
    s.step(f, 3.0, 0.05)
    assert s.current is a                        # cooldown: b left the screen <8 s ago
    s.step(f, 10.5, 0.05)
    assert s.current is b                        # cooldown over


def test_forced_channel_and_disabled_channels(tmp_path):
    st = Settings(tmp_path / "s.json", autoload=False)
    a, b, m = Fake("a", 10, 0), Fake("b", 10, 0), Fake("mbta", 5, 0)
    s = _sched([a, b, m], settings=st)
    assert s.pick(0.0) is a
    st.force_channel("mbta", 60)
    assert s.pick(0.0) is m
    st.force_channel(None)
    st.set_enabled(["b", "mbta"])
    s.current = None
    assert s.pick(1.0) is b
    st.set_enabled(["mbta"])
    assert s.pick(2.0) is m
    st.set_enabled([])
    assert s.pick(3.0) is None


def test_wipe_up_blends_bottom_to_top():
    old = np.zeros((H, W, 3), np.uint8)
    new = np.full((H, W, 3), 200, np.uint8)
    half = wipe_up(old, new, 0.5)
    assert half[0, 0, 0] == 0 and half[H - 1, 0, 0] == 200 and half[H // 2, 0, 0] == 200
    assert (wipe_up(old, new, 0.0) == old).all() and (wipe_up(old, new, 1.0) == new).all()


def test_scheduler_wipes_on_switch():
    a, b = Fake("a", 10, (255, 0, 0)), Fake("b", 0, (0, 0, 255))
    s = Scheduler([a, b], CaptureSink(), fps=20, wipe_seconds=0.3)
    f = Frame()
    s.step(f, 0.0, 0.05)
    b.prio = 20
    out = s.step(f, 0.1, 0.05)           # the switch: wipe starts, old frame still fully shown
    assert tuple(out[H - 1, 0]) == (255, 0, 0)
    out = s.step(f, 0.25, 0.05)          # halfway through the wipe
    assert tuple(out[0, 0]) == (255, 0, 0) and tuple(out[H - 1, 0]) == (0, 0, 255)
    out = s.step(f, 0.5, 0.05)
    assert tuple(out[0, 0]) == (0, 0, 255)


def test_brightness_schedule_applied_to_sink(tmp_path):
    st = Settings(tmp_path / "s.json", autoload=False)
    st.set_brightness(0xBF)
    st.set_quiet({"start": "23:00", "end": "07:00", "level": 0x40})
    assert st.effective_brightness(datetime(2026, 9, 15, 12, 0)) == 0xBF
    assert st.effective_brightness(datetime(2026, 9, 15, 23, 30)) == 0x40
    assert st.effective_brightness(datetime(2026, 9, 15, 3, 0)) == 0x40
    assert st.effective_brightness(datetime(2026, 9, 15, 7, 0)) == 0xBF
    st.set_quiet({"start": "01:00", "end": "05:00"})          # non-wrapping window keeps level
    assert st.effective_brightness(datetime(2026, 9, 15, 2, 0)) == 0x40
    assert st.effective_brightness(datetime(2026, 9, 15, 23, 30)) == 0xBF
    a = Fake("a", 10, 0)
    sink = CaptureSink()
    s = Scheduler([a], sink, fps=20, settings=st, wipe_seconds=0)
    s.step(Frame(), 0.0, 0.05)
    assert sink.brightness == st.effective_brightness()


def test_settings_persist_and_reload(tmp_path):
    from panelwall.config import CONFIG
    before = (CONFIG.location.lat, CONFIG.location.lon, CONFIG.location.radius_nm)
    p = tmp_path / "settings.json"
    try:
        st = Settings(p, autoload=False)
        st.set_enabled(["flights", "mbta"])
        st.set_brightness(100)
        st.set_location(42.36, -71.06, 8)
        st.set_quiet({"start": "22:00", "end": "06:30", "level": 20})
        st2 = Settings(p)
        assert st2.enabled == ["flights", "mbta"] and st2.brightness == 100
        assert st2.lat == 42.36 and st2.lon == -71.06 and st2.radius_nm == 8
        assert st2.quiet == {"start": "22:00", "end": "06:30", "level": 20}
        assert CONFIG.location.radius_nm == 8            # pushed through to the shared config
        p.write_text("not json")
        st3 = Settings(p)
        assert st3.load_error is not None and st3.brightness == CONFIG.display.brightness
    finally:
        CONFIG.location.lat, CONFIG.location.lon, CONFIG.location.radius_nm = before
