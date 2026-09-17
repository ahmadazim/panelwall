from panelwall.data.airports import display_name, shorten_name, lookup, coords, route_progress
from panelwall.data.airlines import airline_full_name, FULL_NAMES, AIRLINES
from panelwall.data.aircraft_types import type_long_name, LONG_TYPES, TYPES
from panelwall import fonts


def test_airport_display_names_from_the_product_photos():
    expected = {
        "OAK": "Oakland Intl", "SEA": "Seattle-Tacoma Intl", "SFO": "San Francisco Intl", "HND": "Tokyo Haneda Intl",
        "DFW": "Dallas-Fort Worth Intl", "DTW": "Detroit Metropolitan Wayne County", "MCO": "Orlando Intl",
        "EWR": "Newark Liberty Intl", "LAX": "Los Angeles Intl", "DCA": "Reagan National",
    }
    for code, name in expected.items():
        assert display_name(code) == name, code


def test_shorten_rule_and_fallbacks():
    assert shorten_name("Seattle–Tacoma International Airport") == "Seattle-Tacoma Intl"   # en dash -> hyphen
    assert shorten_name("Manchester-Boston Regional Airport") == "Manchester-Boston Rgnl"
    assert shorten_name("Some Municipal Airport") == "Some Muni"
    assert shorten_name("Dublin Airport") == "Dublin"
    assert display_name("XXXX") == "XXXX" and display_name("") == "" and display_name(None) == ""
    assert display_name("bos") == "Boston Logan Intl"


def test_csv_loaded_and_coords_feed_progress():
    a = lookup("BOS")
    assert a and a.municipality == "Boston" and a.country == "US" and 42.3 < a.lat < 42.4
    assert coords("SEA") and coords("ZZZZ") is None
    assert 0.6 < route_progress("BOS", "LAX", 39.86, -104.67) < 0.75         # now sourced from the CSV
    assert len(__import__("panelwall.data.airports", fromlist=["_load"])._load()) > 5000


def test_airline_full_names_cover_every_code():
    for code in AIRLINES:
        assert code in FULL_NAMES, code
    assert airline_full_name("SWA1187") == "Southwest Airlines"
    assert airline_full_name("JBU1287 ") == "JetBlue Airways"
    assert airline_full_name("N741CG") == "" and airline_full_name("") == ""


def test_long_type_names_cover_every_code():
    for code in TYPES:
        assert code in LONG_TYPES, code
    assert type_long_name("B737") == "Boeing 737-700" and type_long_name("A21N") == "Airbus A321neo"
    assert type_long_name("E145") == "Embraer ERJ-145" and type_long_name("PC12") == "Pilatus PC-12"
    assert type_long_name("CRJ9") == "Bombardier CRJ-900" and type_long_name("GLF6") == "Gulfstream G650"
    assert type_long_name("ZZZZ") == "ZZZZ" and type_long_name("") == ""


def test_fw_font_widths():
    assert fonts.width("Seattle-Tacoma Intl", fonts.FW) == 114 <= 256
    assert fonts.width("Dallas-Fort Worth Intl", fonts.FW) == 132 <= 256
    assert fonts.width("Detroit Metropolitan Wayne County", fonts.FW) == 198 <= 256
    assert fonts.FW.getbbox("Southwest Airlines")[3] == 10                   # 10 px cell, 7 px caps in rows 1-7


def test_bitmap_font_survives_non_latin1_text():
    from panelwall.fonts import safe_text
    from panelwall.framebuffer import Frame
    assert safe_text("\u0130stanbul Airport", fonts.FW) == "Istanbul Airport"        # the crash on the Pi
    assert safe_text("S\u00e3o Paulo-Guarulhos", fonts.FW) == "Sao Paulo-Guarulhos"
    assert safe_text("Z\u00fcrich  \u00d8rsted  \u0141\u00f3d\u017a", fonts.FW) == "Zurich  Orsted  Lodz"
    assert safe_text("\u6771\u4eac", fonts.FW) == "??"
    assert safe_text("\u0130stanbul", fonts.MEDIUM) == "\u0130stanbul"                # TrueType: untouched
    f = Frame()
    for s in ("\u0130stanbul Airport", "\u6771\u4eac\u56fd\u969b\u7a7a\u6e2f", "Z\u00fcrich"):
        f.text(0, 2, s, fonts.FW)                                                     # must not raise
        assert fonts.width(s, fonts.FW) > 0
