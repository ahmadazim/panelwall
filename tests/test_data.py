import json
from pathlib import Path

from panelwall.data.adsb import parse_aircraft, parse_route
from panelwall.data.airlines import short_flight, parse_callsign

FX = json.loads((Path(__file__).resolve().parent.parent / "fixtures" / "bos_point.json").read_text())


def test_callsign_parsing():
    assert parse_callsign("JBU1287 ") == ("B6", "JETBLUE", "1287")
    assert short_flight("DAL2314") == "DL 2314"
    assert short_flight("N741CG") == "N741CG"          # private: unknown prefix -> raw
    assert short_flight("") == ""


def test_parse_aircraft_fields():
    a = parse_aircraft(FX["ac"][0], 42.3601, -71.0589)
    assert a.flight == "B6 1287" and a.type_name == "A321NEO"
    assert a.altitude == 4250 and a.speed == 242 and a.track == 247 and a.vrate == 2112
    assert a.phase == "CLIMBING"
    assert 2.0 < a.distance_nm < 3.0


def test_ground_aircraft():
    a = parse_aircraft(FX["ac"][-1], 42.3601, -71.0589)
    assert a.on_ground and a.altitude == 0 and a.phase == "GROUND"


def test_parse_route_variants():
    assert parse_route({"_airport_codes_iata": "BOS-LAX", "plausible": True}) == ("BOS", "LAX")
    assert parse_route({"airport_codes": "KBOS-KLAX"}) == ("BOS", "LAX")
    assert parse_route({"airport_codes": "EIDW-KBOS", "_airport_codes_iata": "DUB-BOS"}) == ("DUB", "BOS")
    assert parse_route({"_airport_codes_iata": "unknown"}) == ("", "")
    assert parse_route({"_airport_codes_iata": "BOS-LAX", "plausible": False}) == ("", "")
    assert parse_route({}) == ("", "")


def test_parse_adsbdb_route():
    from panelwall.data.adsb import parse_adsbdb_route
    doc = {"response": {"flightroute": {"callsign": "UAL755",
           "origin": {"iata_code": "IAD", "latitude": 38.9445, "longitude": -77.4558},
           "destination": {"iata_code": "BOS", "latitude": 42.3643, "longitude": -71.0052}}}}
    assert parse_adsbdb_route(doc) == ("IAD", "BOS", (38.9445, -77.4558), (42.3643, -71.0052))
    assert parse_adsbdb_route({"response": "unknown callsign"}) == ("", "", None, None)
    assert parse_adsbdb_route({}) == ("", "", None, None)
    assert parse_adsbdb_route({"response": {"flightroute": {"origin": {"iata_code": "IAD"}, "destination": {}}}}) == ("", "", None, None)


def test_429_sets_backoff_and_friendly_error(monkeypatch):
    import time
    from panelwall.data import adsb
    c = adsb.AdsbClient(routes_base="")
    calls = []

    def boom(url, timeout, body=None):
        calls.append(url)
        raise adsb.ApiError(429, "<html>\r\n429 Too Many Requests\r\nnginx\r\n</html>", retry_after=None)
    monkeypatch.setattr(adsb, "_request", boom)
    assert c.nearby(42.0, -71.0, 8) == []
    assert "429" in c.last_error and "nginx" not in c.last_error and "retrying in 15 s" in c.last_error
    assert c.backoff_until - time.time() > 10
    c.nearby(42.0, -71.0, 8)                                   # second 429 doubles the wait
    assert c.backoff_until - time.time() > 25
    monkeypatch.setattr(adsb, "_request", lambda url, timeout, body=None: (429, "") if False else (_ for _ in ()).throw(adsb.ApiError(429, "", retry_after=90.0)))
    c.nearby(42.0, -71.0, 8)
    assert 85 < c.backoff_until - time.time() <= 90         # Retry-After header wins


def test_routes_are_throttled_and_cached(monkeypatch):
    from panelwall.data import adsb
    from panelwall.config import CONFIG
    c = adsb.AdsbClient(routes_base="https://routes.example")
    seen = []

    def fake(url, timeout, body=None):
        seen.append(url)
        cs = url.rsplit("/", 1)[1]
        if cs.startswith("N"):
            raise adsb.ApiError(404, '{"response":"unknown callsign"}')
        return 200, '{"response":{"flightroute":{"origin":{"iata_code":"BOS","latitude":42.36,"longitude":-71.01},"destination":{"iata_code":"LAX","latitude":33.94,"longitude":-118.41}}}}'
    monkeypatch.setattr(adsb, "_request", fake)
    acs = [adsb.parse_aircraft({"hex": f"h{i}", "flight": f"JBU{100+i} ", "lat": 42.4, "lon": -71.0, "alt_baro": 5000}, 42.36, -71.06) for i in range(5)]
    acs.append(adsb.parse_aircraft({"hex": "pvt", "flight": "N741CG", "lat": 42.4, "lon": -71.0, "alt_baro": 3000}, 42.36, -71.06))
    c._attach_routes(acs)
    per_poll = CONFIG.data.route_lookups_per_poll
    assert len(seen) == per_poll == 2                                      # polite: 2 lookups per poll
    assert acs[0].route == "BOS>LAX" and acs[0].extra["route_pos"] == ((42.36, -71.01), (33.94, -118.41))
    assert acs[4].route == ""                                              # not yet looked up
    assert not any(u.endswith("N741CG") for u in seen)                     # N-numbers are never asked
    seen.clear()
    c._attach_routes(acs)
    assert len(seen) == 2 and acs[3].route == "BOS>LAX" and acs[4].route == ""   # cache hits cost nothing
    seen.clear()
    c._attach_routes(acs)
    assert len(seen) == 1 and acs[4].route == "BOS>LAX"                    # the last one fills in


def test_route_lookup_failure_is_not_a_channel_error(monkeypatch):
    from panelwall.data import adsb
    c = adsb.AdsbClient(routes_base="https://routes.example")

    def slow(url, timeout, body=None):
        raise TimeoutError("The read operation timed out")
    monkeypatch.setattr(adsb, "_request", slow)
    a = adsb.parse_aircraft({"hex": "h1", "flight": "JBU100 ", "lat": 42.4, "lon": -71.0, "alt_baro": 5000}, 42.36, -71.06)
    c._attach_routes([a])
    assert c.last_error is None and c.route_error.startswith("routes: TimeoutError")
    assert a.route == ""
