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


BOARD = json.loads((Path(__file__).resolve().parent.parent / "fixtures" / "espn_board.json").read_text())


def test_board_feed_ingests_every_source():
    feed = SportsFeed(static=BOARD)
    assert {g.league for g in feed.games} >= {"nfl", "nba", "nhl"}
    assert all(feed.tracked_abbr(g) for g in feed.games)                       # only tracked teams' games
    pats = feed.team_games("nfl", "NE")
    assert pats and pats[0].team("NE").color                                   # schedule colours filled in
    assert len(feed.nfl_week) >= 10 and feed.nfl_week_number
    assert len(feed.ucl) >= 9 and all(g.league == "ucl" for g in feed.ucl)
    assert feed.races and any(r.results for r in feed.races) and any(r.state == "pre" for r in feed.races)
    assert feed.matches and feed.tournaments


def test_score_event_from_live_scoreboard():
    import copy
    import time
    feed = SportsFeed(static=BOARD)
    live = copy.deepcopy(BOARD["scoreboards"]["nba"])
    ev = next(e for e in live["events"] if any(t["team"]["abbreviation"] == "BOS" for t in e["competitions"][0]["competitors"]))
    ev["status"]["type"]["state"] = "in"
    for t in ev["competitions"][0]["competitors"]:
        t["score"] = "50"
    feed._scores.clear()                                                      # as if the board started mid-game
    feed._ingest_live("nba", copy.deepcopy(live))
    assert feed.any_live() and feed.event_until == 0.0                       # first sighting: no event
    for t in ev["competitions"][0]["competitors"]:
        if t["team"]["abbreviation"] == "BOS":
            t["score"] = "53"
    feed._ingest_live("nba", live)
    assert feed.event_until > time.time() and feed.event_game == ev["id"]


def test_week_status_and_game_rows():
    from panelwall.data.espn import week_status, game_row
    sun_1pm = datetime(2026, 9, 20, 13, 0, tzinfo=TZ)
    assert week_status(_game("nfl", "pre", 0, 0, home=False, start=sun_1pm), "BOS", NOW) == "1P @MIA"
    assert week_status(_game("nhl", "pre", 0, 0, home=True, start=sun_1pm), "BOS", NOW) == "1P VS MIA"
    assert week_status(_game("nba", "post", 112, 98, short="Final", period=4), "BOS", NOW) == "W 112-98"
    g = _game("nfl", "post", 24, 19, home=False, short="Final", period=4)
    assert game_row(g, NOW) == ("BOS 24 @MIA 19", "F")


def test_f1_and_tennis_parsers():
    from panelwall.data.espn import parse_f1, parse_tennis, match_row, round_short
    races = parse_f1(BOARD["f1"])
    done = [r for r in races if r.state == "post"]
    assert done and done[-1].results[0][0] == 1 and len(done[-1].results) == 6
    assert all(r.short.isascii() and "GRAND PRIX" not in r.short for r in races)          # 'SAO PAULO GP'
    assert parse_f1({}) == [] and parse_f1({"events": [{"bad": 1}]}) == []
    ts, ms = parse_tennis(BOARD["tennis"]["atp"], "atp")
    assert ts and ts[0].tour == "ATP"
    post = [m for m in ms if m.state == "post"]
    assert post and " D. " in match_row(post[0]).upper()
    assert round_short("Final") == "F" and round_short("Semifinals") == "SF" and round_short("Quarterfinals") == "QF"
    assert round_short("Round 2") == "R2"
    assert parse_tennis({}, "wta") == ([], [])


def test_board_pages_rotate_and_render():
    ch = SportsChannel(feed=SportsFeed(static=BOARD))
    pages = ch.pages()
    assert pages[:5] == ["boston", "nfl", "ucl", "f1", "tennis"] or "live" in pages
    assert ch.priority() in (4, 12)
    for page in ("boston", "nfl", "ucl", "f1", "tennis", "live"):
        c = SportsChannel(feed=SportsFeed(static=BOARD), page=page)
        f = Frame()
        c.tick(0.05)
        c.render(f)
        assert f.to_array()[8:].max() > 0, page                                # each page draws below the header
    seen = set()
    for _ in range(int(len(pages) * 10 / 0.5) + 1):
        ch.tick(0.5)
        seen.add(ch.page())
    assert seen == set(pages)                                                   # every page shown on its timer


def test_board_sections_are_configurable_and_empty_board_degrades():
    feed = SportsFeed(static=BOARD, sections=["f1"])
    ch = SportsChannel(feed=feed)
    assert ch.pages() == ["f1"]
    empty = SportsChannel(feed=SportsFeed(static={"_now": BOARD["_now"]}))
    assert empty.pages() == [] and empty.priority() == 0
    empty.render(Frame())


def test_client_never_uses_the_dead_date_range_form(monkeypatch):
    """ESPN started answering `dates=YYYYMMDD-YYYYMMDD` with HTTP 400 (Nov 2026): that broke the board."""
    from panelwall.data.espn import EspnClient
    urls = []
    c = EspnClient()
    monkeypatch.setattr(c, "get", lambda path, params=None: urls.append(c.url(path, params)) or {"events": []})
    feed = SportsFeed(static={"_now": BOARD["_now"]})
    feed.client = c
    feed._next.clear()
    feed._poll_once()
    assert urls and not any("-20" in u.split("dates=")[-1] for u in urls if "dates=" in u)
    assert any("/teams/ne/schedule" in u for u in urls) and any("uefa.champions/scoreboard?dates=" in u for u in urls)
    assert any("racing/f1/scoreboard?dates=" in u for u in urls) and any("tennis/atp/scoreboard" in u for u in urls)


def test_three_digit_score_fits_and_name_falls_back():
    t = _team("BOS", 112, True, "Celtics")
    assert fit_name(t, 92 - fonts.width("112", fonts.LARGE) - 4 - 12) == "BOS"
    assert fit_name(t, 92 - fonts.width("7", fonts.LARGE) - 4 - 12) == "CELTICS"
    assert fonts.width("112", fonts.LARGE) <= 92 - 12 - fonts.width("BOS") - 4
