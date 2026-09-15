import json
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


def test_auto_skips_empty_channels_and_falls_back_to_first():
    a, b = Fake("a", 10, (255, 0, 0)), Fake("b", 5, (0, 255, 0))
    s = _sched([a, b])
    assert s.pick(0.0) is a                      # round-robin starts at the first showable
    a.prio = 0
    s.current = a
    assert s.pick(1.0) is b                      # a has nothing to show -> skipped
    b.prio = 0
    assert s.pick(2.0) is a                      # nothing anywhere -> first panel rather than a blank wall
    s2 = _sched([])
    assert s2.pick(0.0) is None


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


def test_manual_mode_pins_one_channel_whatever_the_priorities(tmp_path):
    st = Settings(tmp_path / "s.json", autoload=False)
    a, b, m = Fake("a", 10, 0), Fake("b", 25, 0), Fake("mbta", 0, 0)
    s = _sched([a, b, m], settings=st)
    assert st.mode == "manual"
    assert s.pick(0.0) is a                      # default pin 'flights' isn't loaded -> first channel
    st.select_channel("mbta")
    f = Frame()
    for t in (0.0, 30.0, 300.0):
        s.step(f, t, 0.05)
        assert s.current is m                    # priority 0 and b's alert (25) are both ignored
    st.force_channel("b", 60)                    # API override still wins
    assert s.pick(301.0) is b
    st.force_channel(None)
    assert s.pick(302.0) is m


def test_auto_mode_cycle_list_dwell_and_alerts(tmp_path):
    st = Settings(tmp_path / "s.json", autoload=False)
    a, b, m = Fake("a", 10, 0), Fake("b", 10, 0), Fake("mbta", 5, 0)
    s = _sched([a, b, m], settings=st)
    st.set_mode("auto")
    st.set_cycle(["b", "mbta"], dwell_seconds=10)
    f = Frame()
    s.step(f, 0.0, 0.05)
    assert s.current is b                        # a is not in the cycle
    s.step(f, 9.0, 0.05)
    assert s.current is b
    s.step(f, 10.0, 0.05)
    assert s.current is m                        # dwell of 10 s, not the constructor's 20
    s.step(f, 20.5, 0.05)
    assert s.current is b
    a.prio = 25                                  # alert on a channel OUTSIDE the cycle: ignored
    s.step(f, 21.0, 0.05)
    assert s.current is b
    b.prio = 10
    m.prio = 25                                  # alert inside the cycle interrupts...
    s.step(f, 22.0, 0.05)
    assert s.current is b                        # ...but m left the screen 1.5 s ago: anti-flap holds it 8 s
    s.step(f, 29.0, 0.05)
    assert s.current is m
    st.set_cycle(alerts=False)
    m.prio = 5
    b.prio = 25
    s.step(f, 30.0, 0.05)
    assert s.current is m                        # alerts off: plain round-robin, m keeps its dwell
    st.set_cycle([])
    assert s.pick(24.0) is None


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
        st.set_cycle(["flights", "mbta"], dwell_seconds=15, alerts=False)
        st.select_channel("radar")
        st.set_mode("auto")
        st.set_brightness(100)
        st.set_location(42.36, -71.06, 8)
        st.set_location(lat=140.0)                        # a typo on the phone: clamped, never sent to the APIs
        assert st.lat == 90.0
        st.set_location(lat=42.36)
        st.set_quiet({"start": "22:00", "end": "06:30", "level": 20})
        st2 = Settings(p)
        assert st2.cycle == ["flights", "mbta"] and st2.brightness == 100
        assert st2.mode == "auto" and st2.channel == "radar" and st2.dwell_seconds == 15 and st2.alerts is False
        p.write_text(json.dumps({"enabled": ["mbta"]}))            # pre-mode settings file still loads
        assert Settings(p).cycle == ["mbta"]
        assert st2.lat == 42.36 and st2.lon == -71.06 and st2.radius_nm == 8
        assert st2.quiet == {"start": "22:00", "end": "06:30", "level": 20}
        assert CONFIG.location.radius_nm == 8            # pushed through to the shared config
        p.write_text("not json")
        st3 = Settings(p)
        assert st3.load_error is not None and st3.brightness == CONFIG.display.brightness
    finally:
        CONFIG.location.lat, CONFIG.location.lon, CONFIG.location.radius_nm = before
