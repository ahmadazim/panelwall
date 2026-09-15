import time

from panelwall.channels.base import Channel
from panelwall.data.polling import Backoff, DemandPoller, retry_after_seconds
from panelwall.data.feed import AircraftFeed
from panelwall.framebuffer import Frame
from panelwall.scheduler import Scheduler
from panelwall.settings import Settings
from panelwall.sinks.base import Sink


class Fake(Channel):
    def __init__(self, name):
        self.name = name

    def render(self, frame):
        pass


class NullSink(Sink):
    def show(self, frame):
        pass


def test_backoff_doubles_and_honours_retry_after():
    b = Backoff()
    assert b.remaining() == 0
    assert b.note() == 15 and 14 < b.remaining() <= 15
    assert b.note() == 30
    assert b.note(90) == 90 and 89 < b.remaining() <= 90
    b.reset()
    assert b.note() == 15
    assert retry_after_seconds({"Retry-After": "42"}) == 42.0
    assert retry_after_seconds({"Retry-After": "soon"}) is None and retry_after_seconds(None) is None


def test_feed_is_wanted_only_while_a_registered_channel_is_active():
    feed = AircraftFeed(static=[])                      # static: no thread, just the demand logic
    assert feed.wanted()                                 # nobody registered -> always wanted (demos)
    a, b = Fake("a"), Fake("b")
    feed.register(a)
    feed.register(b)
    feed.register(a)
    assert len(feed.users) == 2 and not feed.wanted()          # channels start inactive: no request before frame 1
    b.active = True
    assert feed.wanted()
    a.active = b.active = False
    assert not feed.wanted()


def test_wait_wanted_returns_when_a_channel_becomes_active():
    feed = AircraftFeed(static=[])
    a = Fake("a")
    feed.register(a)
    import threading
    threading.Timer(0.3, lambda: setattr(a, "active", True)).start()
    t0 = time.time()
    feed._wait_wanted()
    assert 0.2 < time.time() - t0 < 3.0 and feed.paused is False


def test_scheduler_marks_needed_channels(tmp_path):
    st = Settings(tmp_path / "s.json", autoload=False)
    chans = [Fake(n) for n in ("flightwall", "radar", "mbta")]
    s = Scheduler(chans, NullSink(), fps=20, settings=st, wipe_seconds=0)
    s.step(Frame(), 0.0, 0.05)
    assert [c.active for c in chans] == [True, False, False]          # manual: only the pinned panel
    st.select_channel("mbta")
    s.step(Frame(), 1.0, 0.05)
    assert [c.active for c in chans] == [False, False, True]
    st.set_mode("auto")
    st.set_cycle(["radar", "mbta"])
    s.step(Frame(), 2.0, 0.05)
    assert [c.active for c in chans] == [False, True, True]           # auto: the cycle members
    st.force_channel("flightwall", 60)
    s.step(Frame(), 3.0, 0.05)
    assert chans[0].active                                            # forced channel counts too
    s2 = Scheduler(chans, NullSink(), fps=20, wipe_seconds=0)          # no settings: everything active
    s2.step(Frame(), 0.0, 0.05)
    assert all(c.active for c in chans)


def test_live_feeds_start_and_stop_without_network():
    """Regression: the poll threads must construct (a missing import once broke `run` but not the static-feed tests)."""
    from panelwall.data.feed import AircraftFeed
    from panelwall.data.mbta import MbtaFeed
    from panelwall.data.espn import SportsFeed
    from panelwall.data.openmeteo import ForecastFeed

    class NoNet:
        last_error = None
        backoff_until = 0.0

        def __getattr__(self, name):                     # any client method -> no data
            if name == "backoff":
                from panelwall.data.polling import Backoff
                return Backoff()
            return lambda *a, **k: None if name != "nearby" else []

    feeds = [AircraftFeed(client=NoNet(), poll_seconds=60), MbtaFeed(client=NoNet()),
             SportsFeed(client=NoNet()), ForecastFeed(client=NoNet())]
    try:
        for fd in feeds:
            assert fd._thread is not None and fd._thread.is_alive()
    finally:
        for fd in feeds:
            fd.close()
    for fd in feeds:
        fd._thread.join(timeout=5)
        assert not fd._thread.is_alive()


def test_sleep_or_pause_flags_paused_within_a_check_interval():
    feed = AircraftFeed(static=[])
    a = Fake("a")
    a.active = True
    feed.register(a)
    import threading
    threading.Timer(0.2, lambda: setattr(a, "active", False)).start()
    threading.Timer(0.6, lambda: setattr(a, "active", True)).start()
    from panelwall.data import polling
    old = polling.PAUSE_CHECK
    polling.PAUSE_CHECK = 0.1
    try:
        t0 = time.time()
        feed._sleep_or_pause(0.4)                 # sleeps 0.4 s, then must block until a is active again (~0.6 s)
        assert 0.55 < time.time() - t0 < 3.0 and feed.paused is False
    finally:
        polling.PAUSE_CHECK = old
