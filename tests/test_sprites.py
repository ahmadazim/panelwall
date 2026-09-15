import numpy as np

from panelwall import sprites
from panelwall.data.airports import route_progress, great_circle_nm
from panelwall.channels.silhouette import SilhouetteChannel, bearing_text, SOLO_PRIORITY, DETAIL_PRIORITY, DETAIL_SECONDS, DETAIL_COOLDOWN
from panelwall.data.feed import AircraftFeed
from panelwall.data.adsb import parse_aircraft
from panelwall.framebuffer import Frame


def _bbox(img):
    a = np.asarray(img)[:, :, 3]
    ys, xs = np.nonzero(a)
    return xs.min(), ys.min(), xs.max(), ys.max()


def test_every_type_builds_inside_the_box():
    for code, p in sprites.TYPE_PARAMS.items():
        img = sprites.build_sprite(p)
        assert img.size == (sprites.SPRITE_W, sprites.SPRITE_H), code
        x0, y0, x1, y1 = _bbox(img)
        assert x1 - x0 >= 20, f"{code} too small"
        assert y0 >= 0 and y1 < sprites.SPRITE_H, code


def test_required_types_are_covered():
    required = ("A319 A320 A321 A20N A21N B737 B738 B739 B38M B752 B763 B77W B788 B789 A332 A333 A359 "
                "E170 E75L E190 E195 BCS1 BCS3 CRJ2 CRJ7 CRJ9 DH8D C172 C182 P28A SR22 PC12 C402 "
                "E55P CL30 GLF5 C25A C56X C68A R44").split()
    for code in required:
        assert code in sprites.TYPE_PARAMS, code


def test_unknown_type_is_generic_twin_jet():
    assert sprites.params_for("ZZZZ") is sprites.GENERIC
    assert sprites.params_for(None) is sprites.GENERIC
    assert sprites.GENERIC.engines == 2 and sprites.GENERIC.engine_pos == "wing"


def test_airline_colors_recolor_tail():
    default = np.asarray(sprites.sprite_for("A21N", None))
    jetblue = np.asarray(sprites.sprite_for("A21N", "JBU"))
    assert default.shape == jetblue.shape
    assert (default != jetblue).any()                       # tail/stripe differ
    assert sprites.colors_for("xyz") == (sprites.DEFAULT_TAIL, sprites.DEFAULT_STRIPE)
    assert sprites.sprite_for("A21N", "JBU") is sprites.sprite_for("A21N", "JBU")  # cached


def test_sheet_renders():
    sheet = sprites.render_sheet(scale=1, cols=6)
    assert sheet.size[0] > 600 and sheet.size[1] > 100


def test_route_progress():
    assert abs(great_circle_nm(42.36, -71.01, 33.94, -118.41) - 2260) < 40    # BOS-LAX ~2,260 nm
    assert route_progress("BOS", "LAX", 42.36, -71.01) < 0.02                  # still at BOS
    assert route_progress("BOS", "LAX", 33.94, -118.41) > 0.98                 # at LAX
    mid = route_progress("BOS", "LAX", 39.86, -104.67)                        # over Denver: most of the way
    assert 0.6 < mid < 0.75
    assert route_progress("BOS", "XXX", 42.0, -71.0) is None
    assert route_progress("", "", 42.0, -71.0) is None


def test_bearing_text():
    assert bearing_text(42.0, -71.0, 43.0, -71.0) == "N"
    assert bearing_text(42.0, -71.0, 42.0, -70.0) == "E"
    assert bearing_text(42.0, -71.0, 41.3, -71.7) == "SW"


def _feed(*raws):
    return AircraftFeed(static=[parse_aircraft(r, 42.36, -71.06) for r in raws])


RAW1 = {"hex": "a1", "flight": "JBU1287 ", "r": "N2044J", "t": "A21N", "desc": "AIRBUS A-321neo",
        "alt_baro": 4250, "gs": 242, "track": 247, "baro_rate": 2112, "lat": 42.38, "lon": -71.02, "seen": 0.4}
RAW2 = {"hex": "b2", "flight": "N741CG  ", "r": "N741CG", "t": "PC12",
        "alt_baro": 2800, "gs": 168, "track": 96, "baro_rate": -640, "lat": 42.41, "lon": -71.09, "seen": 0.2}


def test_silhouette_priority_and_detail_mode():
    feed = _feed(RAW1)
    ch = SilhouetteChannel(feed=feed)
    ch.tick(0.05)
    assert ch.detail_active() and ch.priority() == DETAIL_PRIORITY      # new closest -> detail
    ch.tick(DETAIL_SECONDS + 1)
    assert not ch.detail_active() and ch.priority() == SOLO_PRIORITY   # one aircraft -> solo card
    feed.aircraft = feed.aircraft + [parse_aircraft(RAW2, 42.36, -71.06)]
    ch.tick(0.05)
    assert ch.priority() == 0                                          # two aircraft, same closest -> hide
    feed.aircraft = list(reversed(feed.aircraft))                      # a DIFFERENT aircraft is now closest...
    ch.tick(0.05)
    assert ch.priority() == 0                                          # ...but the 45 s cooldown hasn't passed
    ch.tick(DETAIL_COOLDOWN)
    ch.tick(0.05)
    assert ch.priority() == DETAIL_PRIORITY                            # now it gets its card
    ch.tick(DETAIL_SECONDS + 1)
    feed.aircraft = list(reversed(feed.aircraft))                      # back to the first one: already shown
    ch.tick(DETAIL_COOLDOWN + 1)
    assert ch.priority() == 0
    feed.aircraft = []
    ch.tick(0.05)
    assert ch.priority() == 0


def test_silhouette_renders_with_and_without_route():
    a = parse_aircraft(RAW1, 42.36, -71.06)
    a.origin, a.destination = "BOS", "LAX"
    ch = SilhouetteChannel(feed=AircraftFeed(static=[a]))
    ch.tick(0.05)
    f = Frame()
    ch.render(f)
    arr = f.to_array()
    assert arr[:, :100].max() > 0 and arr[:, 108:].max() > 0
    b = parse_aircraft(RAW2, 42.36, -71.06)
    ch2 = SilhouetteChannel(feed=AircraftFeed(static=[b]))
    ch2.tick(0.05)
    ch2.render(Frame())
    SilhouetteChannel(feed=AircraftFeed(static=[])).render(Frame())
