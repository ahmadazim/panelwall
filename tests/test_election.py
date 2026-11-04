import copy
import json
import time
from pathlib import Path

import numpy as np

from panelwall.channels.election import ElectionChannel, D_COL, R_COL
from panelwall.data.elections import ElectionFeed, parse_control, parse_races
from panelwall.framebuffer import Frame
from panelwall.usmap import codes, hemicycle, render_map, state_index, state_pixels, state_silhouette

FX = json.loads((Path(__file__).resolve().parent.parent / "fixtures" / "nyt_election.json").read_text())


def _feed():
    return ElectionFeed(static=copy.deepcopy(FX))


def test_parse_races_and_control():
    sen = {(r.office, r.state): r for r in parse_races(FX["senate"])}
    nc = sen[("S", "NC")]
    assert nc.called and nc.flip and nc.winner.name == "Cooper" and nc.winner.party == "D"
    assert nc.leader.pct > nc.runner_up.pct and 0 < nc.reporting <= 100
    gov = {(r.office, r.state): r for r in parse_races(FX["governor"])}
    assert gov[("G", "GA")].called and gov[("G", "GA")].flip and gov[("G", "GA")].winner.name == "Bottoms"
    ch = parse_control(FX["governor"])
    assert ch["S"].total == 100 and ch["S"].to_win == 51 and ch["S"].holdover == {"D": 34, "R": 31, "I": 0}
    assert ch["S"].seats["D"] >= 34 and ch["S"].contested == 35
    assert ch["H"].total == 435 and ch["H"].to_win == 218
    parse_races({"races": [{"bogus": 1}, None, {"reporting_units": [None]}]})  # junk never raises
    assert parse_control({"partyControlData": {"results": [{"offices": {"S": None}}]}}) == {}


def test_new_calls_detected_but_startup_calls_are_history():
    feed = _feed()
    assert feed.calls == []                                                   # already-called races aren't news
    sen = copy.deepcopy(FX["senate"])
    race = next(r for r in sen["races"] if r["race_call_status"] != "called" and r["reporting_units"][0]["candidates"])
    race["race_call_status"] = "called"
    race["outcome"]["won"] = [race["reporting_units"][0]["candidates"][0]["nyt_id"]]
    feed._ingest(sen, None)
    assert len(feed.calls) == 1 and feed.calls[0][1].state == race["reporting_units"][0]["state_postal"]
    ch = ElectionChannel(feed=feed)
    assert ch.banner() is not None and ch.priority() == 25 and ch.view() == "banner"
    feed.calls[0] = (time.time() - 3600, feed.calls[0][1])
    assert ch.banner() is None and ch.priority() in (2, 6)


def test_map_every_state_visible_and_coloured():
    idx, cs = state_index(96, 62)
    assert len(codes()) == 50
    for c in cs:
        assert state_pixels(c, 96, 62).any(), c                               # Delaware & RI included
    rgb = render_map({"MA": D_COL, "TX": R_COL}, 96, 62)
    tx = state_pixels("TX", 96, 62)
    assert tuple(np.median(rgb[tx], axis=0).astype(int)) == R_COL
    assert state_silhouette("NC", 62, 60).sum() > 500 and state_silhouette("XX", 10, 10) is None


def test_hemicycle_seats():
    seats = hemicycle(435, 96, 62)
    assert len(seats) == 435 and len(set(seats)) == 435                       # no two seats on one LED
    assert all(0 <= x < 96 and 0 <= y < 62 for x, y in seats)
    assert seats[0][0] < 20 and seats[-1][0] > 76                              # ordered left -> right


def test_every_view_renders():
    feed = _feed()
    for v in ("S", "G", "H"):
        f = Frame()
        ElectionChannel(feed=feed, view=v).render(f)
        assert np.asarray(f.img).any()
    ch = ElectionChannel(feed=feed)
    assert ch.views() == ["S", "G", "H"] and ch.priority() in (2, 6)
    nc = feed.results.races[("S", "NC")]
    feed.calls = [(time.time(), nc)]
    f = Frame()
    ch.render(f)
    a = np.asarray(f.img)
    left = a[:, :64].astype(int)
    assert ((left[..., 2] > 150) & (left[..., 0] < 100)).sum() > 300          # NC silhouette in Dem blue


def test_no_data_message():
    feed = ElectionFeed(static={})
    f = Frame()
    ElectionChannel(feed=feed).render(f)
    assert ElectionChannel(feed=feed).priority() == 0 and np.asarray(f.img).any()
