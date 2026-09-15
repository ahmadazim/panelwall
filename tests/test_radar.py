import math

from panelwall.channels.radar import project, altitude_color, RadarChannel, R
from panelwall.framebuffer import Frame, AMBER, GREEN, CYAN, GREY
from panelwall.data.feed import AircraftFeed
from panelwall.data.adsb import parse_aircraft


def test_project_cardinal_directions():
    lat0, lon0 = 42.36, -71.06
    # 1 degree north = 60 nm; at radius 60 nm that lands exactly on the outer ring (clipped to R-1)
    dx, dy = project(lat0 + 1, lon0, lat0, lon0, 60.0)
    assert abs(dx) < 1e-6 and dy < 0            # north is up (negative y)
    # east: +x
    dx, dy = project(lat0, lon0 + 0.1, lat0, lon0, 60.0)
    assert dx > 0 and abs(dy) < 1e-6
    # longitude is compressed by cos(lat)
    dx_e, _ = project(lat0, lon0 + 0.1, lat0, lon0, 60.0)
    _, dy_n = project(lat0 + 0.1, lon0, lat0, lon0, 60.0)
    assert abs(dx_e / -dy_n - math.cos(math.radians(lat0))) < 1e-6


def test_project_clips_to_ring():
    dx, dy = project(50.0, -71.06, 42.36, -71.06, 8.0)   # ~460 nm away
    assert abs(math.hypot(dx, dy) - (R - 1)) < 1e-6


def test_project_scale():
    # 4 nm north at radius 8 nm -> half the scope radius up
    dx, dy = project(42.36 + 4 / 60, -71.06, 42.36, -71.06, 8.0)
    assert abs(dy + R / 2) < 1e-6 and abs(dx) < 1e-6


def test_altitude_bands():
    assert altitude_color(1500) == AMBER
    assert altitude_color(5000) == GREEN
    assert altitude_color(35000) == CYAN
    assert altitude_color(None) == GREY


def test_radar_renders_static_fixture():
    raw = {"hex": "abc123", "flight": "JBU1287 ", "t": "A21N", "alt_baro": 4250, "gs": 242, "track": 247,
           "baro_rate": 2000, "lat": 42.38, "lon": -71.02, "seen": 0.5}
    a = parse_aircraft(raw, 42.36, -71.06)
    ch = RadarChannel(feed=AircraftFeed(static=[a]))
    assert ch.priority() == 10
    f = Frame()
    ch.tick(0.05)
    ch.render(f)
    arr = f.to_array()
    assert arr[:, :64].max() > 0 and arr[:, 70:].max() > 0   # scope and list both drew something
    empty = RadarChannel(feed=AircraftFeed(static=[]))
    assert empty.priority() == 1
    empty.render(Frame())
