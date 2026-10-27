import json
from datetime import datetime
from pathlib import Path

from panelwall.data.mbta import (parse_stops, parse_vehicles, parse_predictions, select_branch, upcoming,
                                 MbtaFeed, Stop, Vehicle, BRANCHES)
from panelwall.channels.mbta import MbtaChannel, train_x, station_x
from panelwall.framebuffer import Frame

FX = json.loads((Path(__file__).resolve().parent.parent / "fixtures" / "mbta_red.json").read_text())


def test_parse_stops_in_route_order_with_both_branches():
    stops = parse_stops(FX["stops"])
    assert stops[0].id == "place-alfcl" and stops[0].name == "Alewife"
    assert stops[3].abbrev == "HVD"
    assert len(stops) == 22
    ids = {s.id for s in stops}
    assert BRANCHES["Ashmont"] <= ids and BRANCHES["Braintree"] <= ids


def test_select_branch():
    stops = parse_stops(FX["stops"])
    br = select_branch(stops, "Braintree")
    assert len(br) == 18 and br[-1].id == "place-brntn" and "place-asmnl" not in {s.id for s in br}
    ash = select_branch(stops, "Ashmont")
    assert len(ash) == 17 and ash[-1].id == "place-asmnl"
    assert select_branch(stops, "nonsense") == stops


def test_abbrev_fallback():
    assert Stop("place-xyz", "Wonderland").abbrev == "WON"


def test_parse_vehicles_resolves_parent_station():
    vs = parse_vehicles(FX["vehicles"])
    assert len(vs) == 15
    assert all(v.stop_id.startswith("place-") for v in vs)          # child platform -> parent station
    assert {v.direction_id for v in vs} <= {0, 1}
    assert {v.status for v in vs} <= {"STOPPED_AT", "INCOMING_AT", "IN_TRANSIT_TO"}
    # without `included`, the raw stop id is kept rather than dropped
    raw = {"data": FX["vehicles"]["data"][:1]}
    assert parse_vehicles(raw)[0].stop_id == FX["vehicles"]["data"][0]["relationships"]["stop"]["data"]["id"]


def test_parse_predictions_and_upcoming():
    preds = parse_predictions(FX["predictions"])
    assert len(preds) == 10 and preds[0].when <= preds[1].when
    now = datetime.fromisoformat(FX["_now"])
    south, north = upcoming(preds, 0, now), upcoming(preds, 1, now)
    assert south == [3, 13, 15] and north == [5, 8, 15]
    # trains already gone are dropped
    late = datetime.fromisoformat("2026-09-15T00:30:00-04:00")
    assert upcoming(preds, 0, late) == []
    # null times are skipped, not crashed on
    assert parse_predictions({"data": [{"attributes": {"arrival_time": None, "departure_time": None, "direction_id": 0}}]}) == []


def test_train_x_placement():
    stops = [Stop(f"s{i}", f"S{i}") for i in range(5)]
    n = len(stops)
    assert train_x(Vehicle("v", "s2", 0, "STOPPED_AT"), stops) == station_x(2, n)
    # southbound heading to s2 comes from s1 -> between them
    x = train_x(Vehicle("v", "s2", 0, "IN_TRANSIT_TO"), stops)
    assert station_x(1, n) < x < station_x(2, n)
    # northbound heading to s2 comes from s3
    x = train_x(Vehicle("v", "s2", 1, "INCOMING_AT"), stops)
    assert station_x(2, n) < x < station_x(3, n)
    assert train_x(Vehicle("v", "other-branch", 0, "STOPPED_AT"), stops) is None


def test_channel_renders_fixture_and_empty():
    ch = MbtaChannel(feed=MbtaFeed(static=FX))
    assert ch.priority() == 5
    f = Frame()
    ch.tick(0.05)
    ch.render(f)
    arr = f.to_array()
    assert arr[22, 6:250].max() > 0          # the line is drawn
    assert arr[44:49, 200:].max() > 0        # minutes on the right
    empty = MbtaChannel(feed=MbtaFeed(static={}))
    empty.render(Frame())                    # "LOADING..." path must not raise


GFX = json.loads((Path(__file__).resolve().parent.parent / "fixtures" / "mbta_green.json").read_text())


def _green(key):
    from panelwall.config import MBTA_LINES
    return MbtaFeed(static=dict(GFX[key], _now=GFX["_now"]), spec=MBTA_LINES[key])


def test_green_feeds_orient_direction0_to_the_right():
    b, c, d = _green("greenb"), _green("greenc"), _green("greend")
    assert b.directions == ("Boston College", "Government Center")
    assert b.stops[0].name == "Government Center" and b.stops[-1].name == "Boston College"      # API order kept
    assert c.stops[0].name == "Government Center" and c.stops[-1].name == "Cleveland Circle"     # API order flipped
    assert d.stops[0].name == "Union Square" and d.stops[-1].name == "Riverside"
    assert b.home_stop().name == "Washington Street" and c.home_stop().name == "Kenmore"
    assert all(v.stop_id.startswith("place-") for v in b.vehicles)                               # parents resolved


def test_bus_65_predictions_and_row():
    from panelwall.data.mbta import tiny_name
    b = _green("greenb")
    assert b.spec.bus_route == "65" and b.bus_directions == ("Brighton Center", "Ruggles Station")
    assert len(b.bus_predictions) >= 2 and {p.direction_id for p in b.bus_predictions} == {0, 1}
    out = upcoming(b.bus_predictions, 0, b.now(), n=2)
    assert out and all(m >= 0 for m in out)
    assert tiny_name("Brighton Center") == "BRIGHTON" and tiny_name("Government Center") == "GOV CTR" and tiny_name("Boston College") == "BC"
    ch = MbtaChannel(feed=b)
    assert ch.name == "greenb"
    f = Frame()
    ch.tick(0.05)
    ch.render(f)
    arr = f.to_array()
    assert arr[59:64, :40].max() > 0 and arr[41:46, :60].max() > 0                              # bus row + two arrival rows


def test_dense_lines_label_every_fourth_stop_and_always_home():
    from panelwall.channels.mbta import label_rows, station_x
    b = _green("greenb")
    rows = label_rows(b.stops, b.home)
    hi = next(i for i, s in enumerate(b.stops) if s.id == b.home)
    assert hi in rows
    top = sorted(station_x(i, len(b.stops)) for i, r in rows.items() if r == "top")
    assert all(b - a >= 20 for a, b in zip(top, top[1:]))                                      # no label collisions
    red = parse_stops(FX["stops"])
    red = select_branch(red, "Braintree")
    assert len(label_rows(red, "place-harsq")) == len(red)                                      # Red still labels every stop


def test_green_overview_renders():
    from panelwall.channels.green import GreenOverviewChannel
    feeds = {k: _green(k) for k in ("greenb", "greenc", "greend")}
    ch = GreenOverviewChannel(feeds)
    assert ch.priority() == 5 and all(ch in f.users for f in feeds.values())
    f = Frame()
    ch.render(f)
    arr = f.to_array()
    for y in (14, 26, 38):
        assert arr[y, 34:222, 1].max() > 100                                                     # three green strips
    assert arr[50:55, :40].max() > 0 and arr[59:64, :40].max() > 0
    GreenOverviewChannel({"greenb": MbtaFeed(static={}, spec=feeds["greenb"].spec)}).render(Frame())   # loading path
