from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from panelwall.data.prayers import (parse_page, parse_clock, board_time, day_times, next_event, athan_for, PrayersFeed,
                                    PageConfig)
from panelwall.channels.prayers import PrayersChannel, hms, clock12
from panelwall.framebuffer import Frame

HTML = (Path(__file__).resolve().parent.parent / "fixtures" / "fiveprayers.html").read_text()
TZ = ZoneInfo("America/New_York")


def test_parse_page():
    cfg = parse_page(HTML)
    assert (round(cfg.lat, 6), round(cfg.lon, 6)) == (40.388844, -75.127707)
    assert cfg.elev == 456 and cfg.fajr_angle == 15 and cfg.isha_angle == 15 and cfg.isha_minutes == 0
    assert cfg.asr_factor == 1 and cfg.clclt == 1 and cfg.server_day == 17
    assert cfg.iqama_offsets == [0, 0, 0, 5, 5, 0]                       # from the LIVE #fat, not the commented one
    assert cfg.fixed_iqama == {"Fajr": (5, 0), "Dhuhr": (12, 0), "Asr": (15, 0), "Maghrib": (17, 5), "Isha": (19, 5)}
    assert cfg.jumuah == (12, 30) and cfg.title == "Dtowntest" and cfg.method == "isna"
    assert cfg.location.startswith("Doylestown")


def test_parse_clock_and_rounding():
    assert parse_clock("5:05 PM") == (17, 5) and parse_clock("12:30  PM") == (12, 30) and parse_clock("12:10 AM") == (0, 10)
    assert parse_clock('7:00 <span class="meridian">AM</span>') == (7, 0) and parse_clock("nope") is None
    assert board_time(5.4501, "floor") == (5, 27) and board_time(5.4501, "ceil") == (5, 28)
    assert board_time(12.9999, "ceil") == (13, 0) and board_time(23.999, "ceil") == (0, 0)


def test_athan_matches_the_pages_javascript():
    """Expected values were produced by running fiveprayers.org's own ptScript_calcs.js in node
    for the same parameters (see the harness in the commit message)."""
    cfg = parse_page(HTML)
    expected = {
        date(2026, 9, 17): ["5:27 AM", "6:39 AM", "12:55 PM", "4:25 PM", "7:11 PM", "8:22 PM"],
        date(2026, 12, 21): ["5:58 AM", "7:15 AM", "11:59 AM", "2:20 PM", "4:42 PM", "6:00 PM"],
        date(2026, 6, 21): ["3:51 AM", "5:25 AM", "1:03 PM", "5:02 PM", "8:39 PM", "10:14 PM"],
    }
    for d, want in expected.items():
        pd = day_times(cfg, d, TZ)
        got = [clock12(pd.athan[n]) for n in ("Fajr", "Sunrise", "Dhuhr", "Asr", "Maghrib", "Isha")]
        assert got == want, (d, got)


def test_iqama_offset_vs_fixed_and_jumuah():
    cfg = parse_page(HTML)
    pd = day_times(cfg, date(2026, 9, 17), TZ)
    assert clock12(pd.iqama["Maghrib"]) == "7:16 PM" and clock12(pd.iqama["Isha"]) == "8:27 PM"   # athan + 5
    assert clock12(pd.iqama["Fajr"]) == "5:00 AM" and clock12(pd.iqama["Asr"]) == "3:00 PM"        # fixed from HTML
    assert clock12(pd.jumuah) == "12:30 PM"
    cfg.iqama_offsets = [20, 15, 15, 5, 10, -30]
    pd = day_times(cfg, date(2026, 9, 17), TZ)
    assert clock12(pd.iqama["Fajr"]) == "5:47 AM" and clock12(pd.jumuah) == "12:25 PM"            # jumuah = dhuhr - 30
    cfg.isha_minutes = 90
    cfg.isha_angle = 0
    assert athan_for(cfg, date(2026, 9, 17), TZ)["Isha"] == (20, 41)                              # maghrib 7:11 + 90


def test_next_event_including_friday_and_wraparound():
    cfg = parse_page(HTML)
    thu, fri = date(2026, 9, 17), date(2026, 9, 18)
    today, tomorrow = day_times(cfg, thu, TZ), day_times(cfg, fri, TZ)
    at = lambda h, m, d=thu: datetime(d.year, d.month, d.day, h, m, tzinfo=TZ)  # noqa: E731
    assert next_event(today, tomorrow, at(15, 40))[:2] == ("Asr", "ATHAN")
    assert next_event(today, tomorrow, at(19, 12))[:2] == ("Maghrib", "IQAMA")                    # between athan and iqama
    # wraps to tomorrow; this account's fixed Fajr iqama (5:00) is BEFORE the athan (5:27), so it comes first,
    # exactly as the page's own countdown behaves (it flags such rows 'lateIq')
    assert next_event(today, tomorrow, at(23, 0)) == ("Fajr", "IQAMA", tomorrow.iqama["Fajr"])
    cfg2 = parse_page(HTML)
    cfg2.iqama_offsets = [15, 15, 15, 5, 5, 0]
    t2, tm2 = day_times(cfg2, thu, TZ), day_times(cfg2, fri, TZ)
    assert next_event(t2, tm2, at(23, 0)) == ("Fajr", "ATHAN", tm2.athan["Fajr"])
    fri_day, sat_day = tomorrow, day_times(cfg, date(2026, 9, 19), TZ)
    name, kind, when = next_event(fri_day, sat_day, at(12, 0, fri))
    assert (name, kind, clock12(when)) == ("Jumu'ah", "JUMUAH", "12:30 PM")                     # Friday: no Dhuhr countdown


def test_feed_and_channel_render_and_alert():
    now = datetime(2026, 9, 17, 15, 40, tzinfo=TZ)
    ch = PrayersChannel(static_html=HTML, now=now)
    assert ch.priority() == 4
    f = Frame()
    ch.tick(0.05)
    ch.render(f)
    arr = f.to_array()
    assert arr[13:18, :50].max() > 0 and arr[27:35, 172:].max() > 0        # table rows and the countdown
    assert hms(timedelta(seconds=2712)) == "0:45:12" and hms(timedelta(hours=12, seconds=7)) == "12:00:07"
    ch.feed._fixed_now = datetime(2026, 9, 17, 16, 20, tzinfo=TZ)           # 5 min before Asr athan
    assert ch.priority() == 20
    ch.feed._fixed_now = datetime(2026, 9, 17, 16, 30, tzinfo=TZ)           # 5 min after: back to idle
    assert ch.priority() == 4
    empty = PrayersChannel(feed=PrayersFeed(static_html="<html></html>"))
    assert empty.priority() == 0 and empty.feed.parse_error
    empty.render(Frame())
    assert PrayersFeed(static_html=HTML).status()["title"] == "Dtowntest"
