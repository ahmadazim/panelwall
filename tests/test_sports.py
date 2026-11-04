import json

import numpy as np
from datetime import datetime, timezone, timedelta
from pathlib import Path

from panelwall.data.espn import (parse_scoreboard, parse_event, format_status, live_detail, pick_game, SportsFeed,
                                 Game, Team, MAX_STATUS)
from panelwall.channels.sports import SportsChannel, fit_name
from panelwall.framebuffer import Frame, H
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


def test_wall_rotates_through_every_section_and_renders():
    ch = SportsChannel(feed=SportsFeed(static=BOARD))
    pages = ch.pages()
    assert [p for p in pages if p != "live"] == ["boston", "nfl", "nba", "ucl", "f1", "tennis"]
    assert sum(1 for sl in ch.slides() if sl[0] == "nfl") <= 3                  # the wall caps each section
    total = sum(sl[3] for sl in ch.slides())
    seen = set()
    for _ in range(int(total / 0.5) + 2):
        ch.tick(0.5)
        seen.add(ch.page())
        f = Frame()
        ch.render(f)
        assert f.to_array().max() > 0
    assert seen == set(pages)
    for page in ("boston", "nfl", "nba", "ucl", "f1", "tennis"):
        c = SportsChannel(feed=SportsFeed(static=BOARD), page=page)
        f = Frame()
        c.tick(0.05)
        c.render(f)
        assert f.to_array()[8:].max() > 0, page


def test_per_sport_panels_share_one_feed_and_poll_only_what_is_on_screen():
    feed = SportsFeed(static=BOARD)
    panels = {n: SportsChannel(feed=feed, name=n) for n in ("sports", "boston", "nfl", "nba", "ucl", "f1", "tennis")}
    assert panels["ucl"].sections == ["ucl"] and panels["sports"].sections == list(feed.sections)
    assert len(feed.users) == 7
    assert feed.wanted_sections() == set()                                       # nothing on screen -> nothing polled
    panels["ucl"].active = True
    assert feed.wanted_sections() == {"ucl"}
    panels["f1"].active = True
    assert feed.wanted_sections() == {"ucl", "f1"}
    panels["sports"].active = True
    assert feed.wanted_sections() == set(feed.sections)
    nfl = SportsChannel(feed=SportsFeed(static=BOARD), name="nfl")
    assert {sl[0] for sl in nfl.slides()} == {"nfl"} and len(nfl.slides()) == (len(nfl.feed.nfl_week) + 1) // 2   # every game
    assert nfl.priority() == 4                                                    # Boston live boost only on boston/sports


def test_soccer_goals_red_cards_and_cards_render():
    from panelwall.channels.sports import _goal_text, _last_name
    feed = SportsFeed(static=BOARD)
    scored = [g for g in feed.ucl if g.goals]
    assert scored
    g = scored[0]
    assert sum(1 for x in g.goals if x.home) == g.home.score and sum(1 for x in g.goals if not x.home) == g.away.score
    assert g.home.logo.startswith("https://") and g.home.record
    text = _goal_text(g.goals[0], 60)
    assert fonts.width(text) <= 60 and text.endswith(g.goals[0].minute.replace("'+", "+"))
    assert _last_name("D. Doué") == "DOUE" and _last_name("J. Cook III") == "COOK" and _last_name("Raphinha") == "RAPHINHA"
    reds = [g for g in feed.ucl if g.red_cards]
    ch = SportsChannel(feed=feed, page="ucl")
    for game in (reds or scored)[:1]:
        f = Frame()
        ch._match_card(f, 0, game)
        arr = f.to_array()
        assert arr[1:23, 3:25].max() > 0 and arr[1:23, 103:125].max() > 0          # both crests (fixture tiles)
        assert arr[35:40, :64].max() > 0 or arr[35:40, 64:128].max() > 0          # a goal row


def test_nfl_leaders_compact():
    from panelwall.channels.sports import _compact_leader
    assert _compact_leader("passingYards", "J. Love", "30/41, 288 YDS, 3 TD, 1 INT") == "PASS LOVE 288Y 3TD"
    assert _compact_leader("rushingYards", "J. Cook III", "17 CAR, 80 YDS, 1 TD") == "RUSH COOK 80Y 1TD"
    assert _compact_leader("receivingYards", "C. Watson", "8 REC, 113 YDS") == "REC WATSON 113Y"
    feed = SportsFeed(static=BOARD)
    assert any(g.leaders for g in feed.nfl_week)


def test_f1_art_and_livery():
    from panelwall.f1art import car_sprite, livery, GREY_CAR, CAR_W, CAR_H
    assert livery("LECLERC")[0] == (215, 25, 32) and livery("NOBODY") == GREY_CAR
    a, b = car_sprite(*livery("NORRIS"), 0), car_sprite(*livery("NORRIS"), 1)
    assert a.size == (CAR_W, CAR_H) and a.tobytes() != b.tobytes()               # wheels turn
    ch = SportsChannel(feed=SportsFeed(static=BOARD), page="f1")
    xs = []
    for _ in range(3):
        ch.tick(1.0)
        f = Frame()
        ch.render(f)
        cols = np.nonzero(f.to_array()[H - CAR_H - 1:H - 1].max(axis=(0, 2)) > 60)[0]
        xs.append(cols.mean() if len(cols) else -1)
    assert len(set(xs)) == 3                                                      # the car moves


def test_logo_processing_and_cache(tmp_path):
    import io
    from PIL import Image as PILImage
    from panelwall.data.logos import LogoCache, process, cache_name
    big = PILImage.new("RGBA", (500, 300), (0, 0, 0, 0))
    big.paste((200, 20, 30, 255), (100, 50, 400, 250))
    buf = io.BytesIO()
    big.save(buf, "PNG")
    tile = process(buf.getvalue(), 22)
    a = np.asarray(tile)
    assert tile.size == (22, 22) and set(np.unique(a[:, :, 3])) <= {0, 255}      # alpha is binary on the LEDs
    assert a[11, 11, 0] > 150                                                    # crest centred
    dark = PILImage.new("RGBA", (100, 100), (10, 10, 10, 255))
    buf = io.BytesIO()
    dark.save(buf, "PNG")
    assert np.asarray(process(buf.getvalue(), 22))[0, 0, 0] > 100                # dark crest gets a light ring
    lc = LogoCache(fetch=False, cache_dir=tmp_path)
    assert lc.get("https://example.invalid/x.png") is None and lc.get(None) is None
    url = SportsFeed(static=BOARD).ucl[0].home.logo
    assert lc.get(url, 22) is not None                                           # fixtures/logos is searched
    tile.save(tmp_path / cache_name("https://example.invalid/y.png", 22))
    assert lc.get("https://example.invalid/y.png", 22) is not None


def test_board_sections_are_configurable_and_empty_board_degrades():
    feed = SportsFeed(static=BOARD, sections=["f1"])
    ch = SportsChannel(feed=feed)
    assert ch.pages() == ["f1"]
    lone = SportsChannel(feed=SportsFeed(static={"_now": BOARD["_now"]}), name="ucl")
    lone.render(Frame())                                                         # 'LOADING' / 'NOTHING ON' path
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


def test_f1_host_country_flags():
    from panelwall.f1art import country_code, flag, FLAG_W, FLAG_H, COUNTRY_CODES
    calendar = ["Australia", "China", "Japan", "Bahrain", "Saudi Arabia", "USA", "Canada", "Monaco", "Spain", "Austria",
                "Britain", "Belgium", "Hungary", "Netherlands", "Italy", "Azerbaijan", "Malaysia", "Singapore", "Mexico",
                "Brazil", "Qatar", "United Arab Emirates"]                      # every ESPN country on the 2026 calendar
    for c in calendar:
        code = country_code(c)
        f = flag(code)
        assert f is not None and f.size == (FLAG_W, FLAG_H), c
        assert np.asarray(f)[:, :, 3].all(), c                                   # fully opaque rectangle
    assert country_code("", "Mexico City Grand Prix") == "MEX"                  # falls back to the race title
    assert country_code("", "Some Other Race") is None and flag(None) is None and flag("XXX") is None
    races = SportsFeed(static=BOARD).races
    assert {r.country for r in races} >= {"Mexico", "Brazil"}
    ch = SportsChannel(feed=SportsFeed(static=BOARD), page="f1")
    f = Frame()
    ch.render(f)
    arr = f.to_array()
    mex = np.asarray(flag("MEX").convert("RGB"))
    x = 2 + fonts.width("F1 ") + 2
    assert (arr[0:FLAG_H, x:x + FLAG_W] == mex).all()                            # the host flag beside the GP name
    assert (arr[18:18 + FLAG_H, 158:158 + FLAG_W] == np.asarray(flag("BRA").convert("RGB"))).all()   # and the next race's


def test_boston_screens_one_per_team_in_season():
    ch = SportsChannel(feed=SportsFeed(static=BOARD), name="boston")
    teams = ch._active_teams()
    assert ("nba", "BOS") in teams and ("nhl", "BOS") in teams and ("nfl", "NE") in teams
    assert ("mlb", "BOS") not in teams                                          # out of season (last game in September)
    assert [sl[2] for sl in ch.slides()] == teams and all(sl[0] == "boston" for sl in ch.slides())
    info = ch.feed.team_info[("nba", "BOS")]
    assert info["name"] == "Celtics" and info["record"] and "Atlantic" in info["standing"]
    last, nxt = ch._team_games(("nba", "BOS"))
    assert last.state == "post" and nxt.state == "pre" and last.start < nxt.start
    f = Frame()
    ch._slide_team(f, ("nba", "BOS"))
    arr = f.to_array()
    assert arr[0:9, 13:60].max() > 0                                            # header: name / league / record
    assert arr[10:32, 3:25].max() > 0 and arr[10:32, 131:153].max() > 0         # crests on both cards
    assert arr[59:64, 40:90, 0].max() > 150 or arr[59:64, 40:90, 1].max() > 150  # WIN / LOSS on the last-game card
    assert arr[59:64, 160:230].max() > 0                                         # countdown on the next-game card


def test_boston_screen_follows_a_live_game_and_mlb_bases():
    import copy
    feed = SportsFeed(static=BOARD)
    g = next(g for g in feed.team_games("nba", "BOS") if g.state == "pre")
    g.state, g.period, g.clock = "in", 3, "4:12"
    ch = SportsChannel(feed=feed, name="boston")
    assert ch._live_teams() == [("nba", "BOS")] and ch._team_games(("nba", "BOS"))[0] is g
    assert ch.priority() == 12
    wall = SportsChannel(feed=feed)
    assert sum(1 for sl in wall.slides() if sl[0] == "live") >= 2                  # live team returns after sections
    f = Frame()
    ch._slide_team(f, ("nba", "BOS"))
    assert f.to_array()[35:40, 40:90, 1].max() > 150                              # green Q3 4:12
    mlb = copy.deepcopy(g)
    mlb.league, mlb.situation = "mlb", {"onFirst": True, "onSecond": False, "onThird": True, "outs": 2}
    f = Frame()
    ch._match_card(f, 0, mlb)
    assert f.to_array()[34:41, 40:60, 0].max() > 200                             # lit amber bases


def test_nba_panel_cards_with_team_leaders():
    feed = SportsFeed(static=BOARD)
    assert len(feed.nba_day) >= 2 and all(g.league == "nba" for g in feed.nba_day)
    assert any(t.leaders for g in feed.nba_day for t in (g.home, g.away))
    ch = SportsChannel(feed=feed, name="nba")
    slides = ch.slides()
    assert slides and all(sl[0] == "nba" for sl in slides) and len(slides) == (len(feed.nba_day) + 1) // 2
    f = Frame()
    slides[0][1](f, slides[0][2])
    arr = f.to_array()
    assert arr[35:40, :60].max() > 0 and arr[35:40, 70:128].max() > 0              # leaders on both sides


def test_newly_selected_sport_is_fetched_without_waiting_out_the_sleep():
    feed = SportsFeed(static={"_now": BOARD["_now"]})
    feed.fetched.clear()
    nba = SportsChannel(feed=feed, name="nba")
    ucl = SportsChannel(feed=feed, name="ucl")
    ucl.active = True
    feed._next = {"ucl": 1e18}                    # UCL was fetched; nothing else wanted -> nothing due
    assert not feed._anything_due()
    ucl.active, nba.active = False, True          # the user picks NBA on the phone
    assert feed._anything_due()                   # -> the poll loop wakes within 2 s
    f = Frame()
    nba.render(f)                                 # never fetched yet -> LOADING, not NOTHING ON
    feed.fetched.add("nba")
    nba.render(Frame())
