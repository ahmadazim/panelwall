import json
from pathlib import Path

from panelwall import fonts
from panelwall.__main__ import fixture_aircraft
from panelwall.channels.flightwall import (FlightWallChannel, card_rows, right_column, fmt_alt, fmt_spd, fmt_trk,
                                           fmt_vr, logo_for, carrier_rank, cycle_candidates, X_TEXT, X_RIGHT, LABEL_GAP, COL_GAP)
from panelwall.config import CONFIG
from panelwall.data.feed import AircraftFeed
from panelwall.framebuffer import Frame, W

FX = Path(__file__).resolve().parent.parent / "fixtures"


def _feed(case):
    return AircraftFeed(static=fixture_aircraft((42.3601, -71.0589), f"flightwall_{case}.json"))


def _by_callsign(feed, cs):
    return next(a for a in feed.aircraft if a.callsign == cs)


def test_formatters_imperial():
    assert fmt_alt(2700) == "2,700ft" and fmt_alt(824) == "824ft" and fmt_alt(10500) == "10.5kft"
    assert fmt_alt(34000) == "34.0kft" and fmt_alt(0) == "0ft" and fmt_alt(None) == "N/A"
    assert fmt_spd(413) == "413kts" and fmt_spd(None) == "N/A"
    assert fmt_trk(300) == "300deg" and fmt_trk(0) == "0deg" and fmt_trk(None) == "N/A"
    assert fmt_vr(640) == "+640ft/m" and fmt_vr(-320) == "-320ft/m" and fmt_vr(0) == "+0ft/m" and fmt_vr(None) == "N/A"


def test_formatters_metric():
    assert fmt_alt(2703, "metric") == "824m"                 # 2703 ft = 824 m, the product photo
    assert fmt_alt(6562, "metric") == "2.0km"
    assert fmt_spd(223, "metric") == "413kph"
    assert fmt_vr(3500, "metric") == "+64kph" and fmt_vr(-1000, "metric") == "-18kph"


def test_card_rows_full_route_and_title_modes():
    a = _by_callsign(_feed("a"), "JBU1287")                   # BOS-LAX
    assert card_rows(a) == ("JetBlue Airways", "BOS-LAX", "Airbus A321neo", "Boston Logan Intl", "Los Angeles Intl")
    assert card_rows(a, "flight")[:2] == ("B6 1287", "BOS-LAX")


def test_card_rows_partial_and_no_route():
    b = _feed("b").aircraft[0]                                 # N741CG, PC-12, no route
    assert card_rows(b) == ("N741CG", "N741CG", "Pilatus PC-12", "N741CG", "")
    b.origin = "MCO"
    assert card_rows(b)[3:] == ("Arriving from Orlando Intl", "")
    b.origin, b.destination = "", "AMS"
    assert card_rows(b)[3:] == ("Departing to Amsterdam Schiphol", "")


def test_right_column_and_logo_choice():
    a = _by_callsign(_feed("a"), "JBU1287")
    assert right_column(a, "imperial") == [("Alt:", "4,250ft"), ("Spd:", "242kts"), ("Trk:", "247deg"), ("Vr:", "+2112ft/m")]
    assert logo_for(a).size == (28, 28)
    b = _feed("b").aircraft[0]
    assert logo_for(b) is not None                             # private silhouette
    a.callsign = "ZZZ123"
    assert logo_for(a) is not None                             # generic plane for unknown carriers


def test_longest_strings_fit_or_clip_cleanly():
    right_w = max(fonts.width(v, fonts.FW) + LABEL_GAP + fonts.width(l, fonts.FW) for l, v in
                  [("Alt:", "34.0kft"), ("Spd:", "462kts"), ("Trk:", "300deg"), ("Vr:", "-2112ft/m")])
    col_left = X_RIGHT - right_w
    assert fonts.width("Southwest Airlines", fonts.FW) <= col_left - COL_GAP - X_TEXT
    assert fonts.width("Boeing 777-300ER", fonts.FW) <= col_left - COL_GAP - X_TEXT
    assert fonts.width("Seattle-Tacoma Intl", fonts.FW) <= col_left - COL_GAP            # row 4 shares the Vr row
    assert fonts.width("Detroit Metropolitan Wayne County", fonts.FW) <= W               # row 5 is full width
    f = Frame()
    f.text(0, 37, "Detroit Metropolitan Wayne County", fonts.FW, max_w=100)            # hard clip, no error
    assert f.to_array()[37:45, 100:].max() == 0 and f.to_array()[37:45, :100].max() > 0


def test_commercial_flights_cycle_before_private():
    feed = _feed("c")                                          # 7 aircraft: 6 airline callsigns + N741CG
    acs = feed.aircraft
    private = _by_callsign(feed, "N741CG")
    assert carrier_rank(private) == 2
    assert carrier_rank(_by_callsign(feed, "JBU1287")) == 0
    unknown = parse_like = None
    picked = cycle_candidates(acs, 5)
    assert private not in picked                                # 6 commercial flights fill the five slots
    assert [carrier_rank(a) for a in picked] == [0] * 5
    dists = [a.distance_nm for a in picked]
    assert dists == sorted(dists)                               # nearest first within the group
    # with only 2 commercial flights the private one comes LAST
    few = [private, _by_callsign(feed, "JBU1287"), _by_callsign(feed, "EIN138")]
    assert [a.callsign.strip() for a in cycle_candidates(few, 5)][-1] == "N741CG"
    # an airline-style callsign we don't know ranks between known carriers and private
    from panelwall.data.adsb import Aircraft
    odd = Aircraft("zz", "EJA123", "N1EJ", "C68A", 20000, False, 400, 90, 0, 42.4, -71.0, 0.5)
    assert carrier_rank(odd) == 1
    assert [carrier_rank(a) for a in cycle_candidates(few + [odd], 5)] == [0, 0, 1, 2]
    # the ranking is what the channel cycles
    ch = FlightWallChannel(feed=feed)
    ch.tick(0.05)
    assert private.hex not in ch.order and len(ch.order) == 5


def test_cycle_order_is_stable_and_keeps_the_current_aircraft():
    feed = _feed("c")
    ch = FlightWallChannel(feed=feed)
    ch.tick(0.05)
    assert len(ch.order) == 5 and ch.order == [a.hex for a in cycle_candidates(feed.aircraft, 5)]
    first = ch.order[0]
    ch.tick(CONFIG.flightwall.cycle_seconds)                   # advance one card
    assert ch.index == 1
    showing = ch.order[1]
    acs = list(feed.aircraft)
    acs[0], acs[1] = acs[1], acs[0]                            # list reshuffled, same set of candidates:
    feed.aircraft = acs                                        # -> order and index untouched
    ch.tick(0.05)
    assert ch.order[0] == first and ch.index == 1 and ch.current().hex == showing
    feed.aircraft = [a for a in feed.aircraft if a.hex != first]   # the set changes: the shown card keeps its slot
    ch.tick(0.05)
    assert ch.current().hex == showing and first not in ch.order and len(ch.order) == 5
    feed.aircraft = feed.aircraft[:1]
    ch.tick(0.05)
    assert len(ch.order) == 1 and ch.current() is not None
    feed.aircraft = []
    ch.tick(0.05)
    assert ch.current() is None and ch.priority() == 2


def test_render_all_cases():
    for case in "abcd":
        ch = FlightWallChannel(feed=_feed(case))
        ch.tick(0.05)
        f = Frame()
        ch.render(f)
        arr = f.to_array()
        assert arr.max() > 0
        if case == "c":
            assert len(ch.aircraft) == 7 and len(ch.order) == 5           # cycles the nearest five, no extra text
        if case == "d":
            assert ch.priority() == 2
    ch = FlightWallChannel(feed=_feed("a"))
    assert ch.priority() == 10


def test_black_gap_frame_on_swap():
    ch = FlightWallChannel(feed=_feed("a"))
    ch.tick(0.05)
    ch.render(Frame())
    ch.tick(CONFIG.flightwall.cycle_seconds + 0.1)
    f = Frame()
    ch.render(f)
    assert f.to_array().max() == 0                             # one black frame
    f = Frame()
    ch.render(f)
    assert f.to_array().max() > 0


def test_clock_mode(monkeypatch):
    ch = FlightWallChannel(feed=_feed("d"))
    monkeypatch.setattr(ch.cfg, "no_flights", "clock")
    monkeypatch.setattr(ch.cfg, "clocks", [("EST", "America/New_York"), ("GMT", "Europe/London"), ("JST", "Asia/Tokyo")])
    f = Frame()
    ch.render(f)
    arr = f.to_array()
    assert arr.max() > 0 and arr[:12].max() == 0 and arr[52:].max() == 0   # three stacked rows, vertically centred
    monkeypatch.setattr(ch.cfg, "clocks", [("BAD", "Nowhere/Nowhere")])
    ch.render(Frame())                                         # bad tz must not raise
