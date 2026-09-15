import json
import time
from datetime import datetime
from pathlib import Path

from panelwall.data.openmeteo import parse_forecast, wmo, compass, is_precip, ForecastFeed
from panelwall.channels.forecast import ForecastChannel
from panelwall.framebuffer import Frame

FX = json.loads((Path(__file__).resolve().parent.parent / "fixtures" / "openmeteo.json").read_text())


def test_parse_fixture():
    fc = parse_forecast(FX)
    assert fc.time == datetime(2026, 9, 15, 0, 15) and fc.temp == 57.2 and fc.humidity == 61 and fc.code == 0
    assert len(fc.hourly) == 168 and fc.hourly[0].time == datetime(2026, 9, 15, 0, 0)
    assert len(fc.daily) == 7 and fc.daily[0].hi == 72.1 and fc.daily[0].sunset == datetime(2026, 9, 15, 19, 9)
    assert fc.daily[0].precip == 1 and isinstance(fc.daily[0].precip, int)


def test_parse_is_defensive():
    fc = parse_forecast({})
    assert fc.temp is None and fc.hourly == [] and fc.daily == []
    fc = parse_forecast({"current": {"temperature_2m": "x"}, "hourly": {"time": ["bad", "2026-09-15T01:00"], "temperature_2m": [1]},
                         "daily": {"time": ["2026-09-15"], "weather_code": [61]}})
    assert fc.temp is None and len(fc.hourly) == 1 and fc.hourly[0].temp is None
    assert fc.daily[0].code == 61 and fc.daily[0].hi is None and fc.daily[0].sunrise is None
    assert parse_forecast(None).temp is None


def test_wmo_and_compass():
    assert wmo(0) == ("sun", "CLEAR") and wmo(2) == ("partly", "PARTLY CLOUDY") and wmo(3) == ("cloud", "OVERCAST")
    assert wmo(45) == ("fog", "FOG") and wmo(55) == ("rain", "DRIZZLE") and wmo(65) == ("rain", "RAIN")
    assert wmo(75) == ("snow", "SNOW") and wmo(81) == ("rain", "SHOWERS") and wmo(86) == ("snow", "SNOW SHOWERS")
    assert wmo(96) == ("storm", "THUNDERSTORM") and wmo(None) == ("cloud", "UNKNOWN") and wmo(42)[1] == "UNKNOWN"
    assert not is_precip(3) and is_precip(51) and is_precip(95)
    assert compass(0) == "N" and compass(337) == "NW" and compass(22) == "N" and compass(23) == "NE" and compass(180) == "S"
    assert compass(None) == ""


def test_hours_from_current_hour_and_wrap():
    fc = parse_forecast(FX)
    hrs = fc.hours_from(datetime(2026, 9, 15, 0, 15))
    assert [h.time.hour for h in hrs] == list(range(12))
    hrs = fc.hours_from(datetime(2026, 9, 15, 23, 40))
    assert [h.time.hour for h in hrs] == [23, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    assert fc.hours_from(datetime(2030, 1, 1)) == []


def test_feed_alert_on_precip_onset():
    feed = ForecastFeed(static=FX)
    assert feed.now() == datetime(2026, 9, 15, 0, 15) and feed.alert_until == 0.0
    rainy = json.loads(json.dumps(FX)); rainy["current"]["weather_code"] = 61
    feed._ingest(rainy)
    assert feed.alert_until > time.time()
    feed.alert_until = 0.0
    cloudy = json.loads(json.dumps(FX)); cloudy["current"]["weather_code"] = 3
    feed._ingest(cloudy)                       # rain -> clouds is not an alert
    assert feed.alert_until == 0.0
    feed._ingest({})                           # garbage reply keeps the previous forecast
    assert feed.forecast is not None and feed.forecast.code == 3


def test_channel_views_and_priority():
    ch = ForecastChannel(feed=ForecastFeed(static=FX))
    assert ch.priority() == 3
    assert ch.view == "week"
    ch.tick(20.5)
    assert ch.view == "hourly"
    ch.tick(20.0)
    assert ch.view == "week"
    for view in ("week", "hourly"):
        c = ForecastChannel(feed=ForecastFeed(static=FX), view=view)
        f = Frame()
        c.render(f)
        arr = f.to_array()
        assert arr.max() > 0
        if view == "hourly":
            assert arr[:, 66:70].max() == 0          # nothing bleeds into the gutter left of x=70
    ch.feed.alert_until = 10 ** 12
    assert ch.priority() == 8
    empty = ForecastChannel(feed=ForecastFeed(static={"_now": "2026-09-15T00:15:00"}))
    assert empty.priority() == 0
    empty.render(Frame())


def test_extreme_values_render():
    hot = json.loads(json.dumps(FX))
    hot["current"]["temperature_2m"] = 105.0
    hot["daily"]["temperature_2m_max"] = [105.0] * 7
    hot["daily"]["precipitation_probability_max"] = [100] * 7
    hot["hourly"]["temperature_2m"] = [104.0 + (i % 3) for i in range(168)]
    hot["_now"] = "2026-09-15T23:40:00"
    for view in ("week", "hourly"):
        ForecastChannel(feed=ForecastFeed(static=hot), view=view).render(Frame())


def test_http_400_reports_open_meteo_reason(monkeypatch):
    import io
    import urllib.error
    import urllib.request
    from panelwall.data.openmeteo import OpenMeteoClient

    def boom(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 400, "Bad Request", {}, io.BytesIO(
            b'{"error":true,"reason":"Latitude must be in range of -90 to 90. Given: 140.0."}'))
    monkeypatch.setattr(urllib.request, "urlopen", boom)
    c = OpenMeteoClient()
    assert c.fetch(140.0, 0.0) is None
    assert c.last_error.startswith("HTTP 400 open-meteo: Latitude must be in range")
