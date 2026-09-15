import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

from panelwall.data.espn import (parse_scoreboard, parse_event, format_status, live_detail, pick_game, SportsFeed,
                                 Game, Team, MAX_STATUS)
from panelwall.channels.sports import SportsChannel, fit_name
from panelwall.framebuffer import Frame
from panelwall import fonts

FX = json.loads((Path(__file__).resolve().parent.parent / "fixtures" / "espn_scoreboards.json").read_text())
NOW = datetime.fromisoformat(FX["_now"])
TZ = NOW.tzinfo


def _team(abbr, score, home, nick="Team"):
    return Team(abbr, f"City {nick}", nick, "bd3039", "0c2340", score, home)


def _game(league, state, us_score, them_score, home=True, start=None, short="", period=0, clock="", name="STATUS_IN_PROGRESS", sit=None):
    start = start or NOW + timedelta(hours=3)
    us, them = _team("BOS", us_score, home, "Red Sox"), _team("MIA", them_score, not home, "Marlins")
    return Game(league, "1", start.astimezone(timezone.utc), state, short, name, period, clock,
                home=us if home else them, away=them if home else us, situation=sit or {})


def test_parse_fixture_shapes():
    for lg in ("mlb", "nfl", "nba", "nhl"):
        games = parse_scoreboard(FX[lg], lg)
        assert games and all(g.home.home and not g.away.home for g in games)
    mlb = parse_scoreboard(FX["mlb"], "mlb")
    live = [g for g in mlb if g.live][0]
    assert live.short_detail == "Top 9th" and live.situation["onFirst"] is True and live.situation["outs"] == 1
    assert live.team("BOS").score == 7 and live.opponent("BOS").abbreviation == "ARI"
    nfl = parse_scoreboard(FX["nfl"], "nfl")
    fin = [g for g in nfl if g.state == "post"][0]
    assert fin.team("NE").score == 10 and fin.opponent("NE").score == 13
    nhl = parse_scoreboard(FX["nhl"], "nhl")
    assert nhl[0].home.alt_color == ""            # ESPN gives null alternateColor for NHL: must not crash


def test_malformed_event_is_skipped_not_fatal():
    good = FX["nhl"]["events"][0]
    bad1 = {"id": "x"}                                          # no competitions
    bad2 = json.loads(json.dumps(good)); del bad2["competitions"][0]["competitors"][0]["team"]["abbreviation"]
    bad3 = json.loads(json.dumps(good)); bad3["date"] = "not a date"
    games = parse_scoreboard({"events": [bad1, good, bad2, bad3]}, "nhl")
    assert len(games) == 1
    assert parse_event({}, "nhl") is None
    assert parse_scoreboard({}, "nhl") == [] and parse_scoreboard(None, "nhl") == []


def test_format_status_every_state():
    sun_1pm = datetime(2026, 9, 20, 13, 0, tzinfo=TZ)
    assert format_status(_game("nfl", "pre", 0, 0, home=False, start=sun_1pm), "BOS", NOW) == "SUN 1P @MIA"
    tue_7pm = datetime(2026, 9, 15, 19, 0, tzinfo=TZ)
    assert format_status(_game("nhl", "pre", 0, 0, home=True, start=tue_7pm), "BOS", NOW) == "7P VS MIA"   # today: no day
    wed = datetime(2026, 9, 16, 19, 0, tzinfo=TZ)
    assert format_status(_game("nhl", "pre", 0, 0, home=True, start=wed), "BOS", NOW) == "WED 7P VS MIA"
    wed_705 = datetime(2026, 9, 16, 19, 5, tzinfo=TZ)
    s = format_status(_game("mlb", "pre", 0, 0, home=True, start=wed_705), "BOS", NOW)
    assert s == "WED 7:05P MIA" and len(s) <= MAX_STATUS                    # 'VS' dropped to fit
    assert format_status(_game("mlb", "pre", 0, 0, home=False, start=wed_705), "BOS", NOW) == "WED 7:05P@MIA"
    wed_1207 = datetime(2026, 9, 16, 12, 7, tzinfo=TZ)
    assert format_status(_game("mlb", "pre", 0, 0, home=False, start=wed_1207), "BOS", NOW) == "12:07P @MIA"   # day dropped
    assert format_status(_game("nba", "post", 112, 98, short="Final", period=4), "BOS", NOW) == "W 112-98"
    assert format_status(_game("nhl", "post", 2, 3, short="Final/OT", period=4), "BOS", NOW) == "L 2-3 OT"
    assert format_status(_game("nfl", "post", 24, 24, short="Final", period=4), "BOS", NOW) == "T 24-24"
    assert format_status(_game("mlb", "in", 7, 6, short="Top 9th", period=9), "BOS", NOW) == "7-6 TOP 9TH"
    s = format_status(_game("nba", "in", 98, 95, short="4:12 - 3rd", period=3, clock="4:12"), "BOS", NOW)
    assert s == "98-95 Q3 4:12" and len(s) <= MAX_STATUS
    s = format_status(_game("nba", "in", 108, 105, short="", period=5, clock="2:00"), "BOS", NOW)
    assert s == "108-105 OT" and len(s) <= MAX_STATUS                       # clock dropped to fit
    assert format_status(_game("nba", "in", 112, 108, period=3, clock="4:12"), "BOS", NOW) == "112-108 Q3"
    assert format_status(_game("mlb", "pre", 0, 0, start=wed, name="STATUS_POSTPONED"), "BOS", NOW) == "WED PPD"


def test_live_detail():
    assert live_detail(_game("nfl", "in", 0, 0, period=2, clock="7:31")) == "Q2 7:31"
    assert live_detail(_game("nhl", "in", 0, 0, period=3, clock="12:30")) == "P3 12:30"
    assert live_detail(_game("nhl", "in", 0, 0, period=4, clock="4:00")) == "OT 4:00"
    assert live_detail(_game("nba", "in", 0, 0, period=6, clock="1:00")) == "2OT 1:00"
    assert live_detail(_game("mlb", "in", 0, 0, short="Mid 7th")) == "MID 7TH"


def test_pick_game_prefers_live_then_next_then_last():
    past = _game("mlb", "post", 1, 2, start=NOW - timedelta(days=1), short="Final")
    older = _game("mlb", "post", 5, 2, start=NOW - timedelta(days=2), short="Final")
    nxt = _game("mlb", "pre", 0, 0, start=NOW + timedelta(days=1))
    later = _game("mlb", "pre", 0, 0, start=NOW + timedelta(days=2))
    live = _game("mlb", "in", 3, 3, short="Bot 5th")
    assert pick_game([older, past, later, nxt, live], NOW) is live
    assert pick_game([older, past, later, nxt], NOW) is nxt
    assert pick_game([older, past], NOW) is past
    assert pick_game([], NOW) is None


def test_feed_static_and_score_event():
    feed = SportsFeed(static=FX)
    assert feed.now() == NOW and len(feed.games) >= 5
    assert feed.any_live()
    assert {g.league for g in feed.games} == {"mlb", "nfl", "nhl"}           # NBA: no Boston game
    assert feed.event_until == 0.0
    # a second ingest with the live score changed -> event window opens
    doc = json.loads(json.dumps(FX["mlb"]))
    for t in doc["events"][0]["competitions"][0]["competitors"]:
        if t["team"]["abbreviation"] == "BOS":
            t["score"] = "9"
    feed._ingest({"mlb": doc})
    import time
    assert feed.event_until > time.time() and feed.event_game == doc["events"][0]["id"]


def test_channel_priority_and_render():
    ch = SportsChannel(feed=SportsFeed(static=FX))
    assert ch.priority() == 12                        # live tracked game in the fixture
    f = Frame()
    ch.tick(0.05)
    ch.render(f)
    arr = f.to_array()
    assert arr[11:27, 44:92].max() > 0                # a score was drawn in the LARGE font
    assert arr[12:60, 132:].max() > 0                 # right-hand list
    ch.feed.event_until = 10 ** 12
    assert ch.priority() == 25
    empty = SportsChannel(feed=SportsFeed(static={"_now": FX["_now"]}))
    assert empty.priority() == 0
    empty.render(Frame())


def test_three_digit_score_fits_and_name_falls_back():
    t = _team("BOS", 112, True, "Celtics")
    assert fit_name(t, 92 - fonts.width("112", fonts.LARGE) - 4 - 12) == "BOS"
    assert fit_name(t, 92 - fonts.width("7", fonts.LARGE) - 4 - 12) == "CELTICS"
    assert fonts.width("112", fonts.LARGE) <= 92 - 12 - fonts.width("BOS") - 4
