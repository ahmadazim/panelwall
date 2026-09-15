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
