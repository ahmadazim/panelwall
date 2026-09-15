import json
import urllib.error
import urllib.request

import pytest

from panelwall.__main__ import fixture_channel
from panelwall.framebuffer import Frame
from panelwall.scheduler import Scheduler
from panelwall.settings import Settings
from panelwall.sinks.base import Sink
from panelwall.web import ControlServer, make_icon


class NullSink(Sink):
    def show(self, frame):
        pass


@pytest.fixture
def server(tmp_path):
    settings = Settings(tmp_path / "settings.json", autoload=False)
    chans = [fixture_channel(n) for n in ("flights", "radar", "silhouette", "mbta")]
    sched = Scheduler(chans, NullSink(), fps=20, settings=settings, wipe_seconds=0)
    sched.step(Frame(), 0.0, 0.05)
    srv = ControlServer(sched, settings, port=0, host="127.0.0.1").start()
    yield srv, settings, sched
    srv.stop()
    for c in chans:
        c.close()


def _get(srv, path):
    with urllib.request.urlopen(f"http://127.0.0.1:{srv.port}{path}", timeout=5) as r:
        return r.status, r.headers.get("Content-Type", ""), r.read()


def _post(srv, path, body):
    req = urllib.request.Request(f"http://127.0.0.1:{srv.port}{path}", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_index_manifest_icon(server):
    srv, _, _ = server
    status, ctype, body = _get(srv, "/")
    assert status == 200 and "text/html" in ctype and b"panelwall" in body and b"apple-touch-icon" in body
    assert b"Auto cycle" in body and b"Pick one panel" in body
    status, ctype, body = _get(srv, "/manifest.webmanifest")
    assert status == 200 and json.loads(body)["display"] == "standalone"
    status, ctype, body = _get(srv, "/icon.png")
    assert status == 200 and body[:8] == b"\x89PNG\r\n\x1a\n"
    assert make_icon(64)[:4] == b"\x89PNG"


def test_state(server):
    srv, settings, sched = server
    status, _, body = _get(srv, "/api/state")
    st = json.loads(body)
    assert status == 200
    assert {c["name"] for c in st["channels"]} == {"flights", "radar", "silhouette", "mbta"}
    assert st["current"] == sched.current_name
    assert st["cycle"] == ["flights", "radar", "silhouette", "mbta"] and st["mode"] == "manual"
    assert st["dwell_seconds"] == 20 and st["alerts"] is True
    assert st["brightness"]["configured"] == settings.brightness and "quiet" in st["brightness"]
    assert st["location"]["radius_nm"] == settings.radius_nm
    assert st["uptime_s"] >= 0 and st["force"] is None
    for c in st["channels"]:
        assert "updated_at" in c["status"] and "last_error" in c["status"]


def test_preview_png(server):
    srv, _, _ = server
    status, ctype, body = _get(srv, "/preview.png")
    assert status == 200 and ctype == "image/png" and body[:8] == b"\x89PNG\r\n\x1a\n"
    from PIL import Image
    import io
    im = Image.open(io.BytesIO(body))
    assert im.size == (256 * 3, 64 * 3)
    assert _get(srv, "/preview.png")[2] == body        # cached within a second


def test_default_is_manual_and_channel_endpoint_pins(server, tmp_path):
    srv, settings, sched = server
    status, _, body = _get(srv, "/api/state")
    st = json.loads(body)
    assert st["mode"] == "manual" and st["channel"] == "flightwall"
    assert sched.pick(0.0).name == "flights"                  # the pinned channel isn't loaded here -> first channel
    status, st = _post(srv, "/api/channel", {"channel": "mbta"})
    assert status == 200 and st["mode"] == "manual" and st["channel"] == "mbta"
    assert sched.pick(1.0).name == "mbta" and sched.pick(500.0).name == "mbta"
    assert json.loads((tmp_path / "settings.json").read_text())["channel"] == "mbta"   # persisted
    assert _post(srv, "/api/channel", {"channel": "nope"})[0] == 400


def test_mode_and_cycle_endpoints(server, tmp_path):
    srv, settings, sched = server
    status, st = _post(srv, "/api/mode", {"mode": "auto"})
    assert status == 200 and st["mode"] == "auto"
    status, st = _post(srv, "/api/cycle", {"channels": ["radar", "mbta"], "dwell_seconds": 12, "alerts": False})
    assert status == 200 and st["cycle"] == ["radar", "mbta"] and st["dwell_seconds"] == 12 and st["alerts"] is False
    saved = json.loads((tmp_path / "settings.json").read_text())
    assert saved["cycle"] == ["radar", "mbta"] and saved["dwell_seconds"] == 12 and saved["mode"] == "auto"
    assert sched.pick(1.0).name == "radar"
    status, st = _post(srv, "/api/cycle", {"dwell_seconds": 30})       # partial update keeps the list
    assert status == 200 and st["cycle"] == ["radar", "mbta"] and st["dwell_seconds"] == 30
    status, st = _post(srv, "/api/channels", {"enabled": ["mbta"]})     # old name still works
    assert status == 200 and st["cycle"] == ["mbta"] and st["enabled"] == ["mbta"]
    assert _post(srv, "/api/channels", {"enabled": ["nope"]})[0] == 400
    assert _post(srv, "/api/cycle", {"channels": "mbta"})[0] == 400
    assert _post(srv, "/api/cycle", {"dwell_seconds": "slow"})[0] == 400
    assert _post(srv, "/api/mode", {"mode": "party"})[0] == 400
    status, st = _post(srv, "/api/channel", {"channel": "flights"})    # picking a panel leaves auto mode
    assert st["mode"] == "manual"


def test_show_endpoint(server):
    srv, settings, sched = server
    status, st = _post(srv, "/api/show", {"channel": "radar", "seconds": 30})
    assert status == 200 and st["force"]["channel"] == "radar"
    assert sched.pick(0.0).name == "radar"
    status, st = _post(srv, "/api/show", {"channel": None})
    assert status == 200 and st["force"] is None
    assert _post(srv, "/api/show", {"channel": "bogus"})[0] == 400


def test_brightness_endpoint(server):
    srv, settings, _ = server
    status, st = _post(srv, "/api/brightness", {"level": 77})
    assert status == 200 and st["brightness"]["configured"] == 77 and settings.brightness == 77
    status, st = _post(srv, "/api/brightness", {"quiet": {"start": "22:30", "end": "06:00", "level": 10}})
    assert status == 200 and st["brightness"]["quiet"] == {"start": "22:30", "end": "06:00", "level": 10}
    assert _post(srv, "/api/brightness", {"quiet": {"start": "nonsense"}})[0] == 400
    assert _post(srv, "/api/brightness", {})[0] == 400
    assert _post(srv, "/api/brightness", {"level": 999})[1]["brightness"]["configured"] == 255   # clamped


def test_location_endpoint(server):
    srv, settings, _ = server
    from panelwall.config import CONFIG
    before = (CONFIG.location.lat, CONFIG.location.lon, CONFIG.location.radius_nm)
    try:
        status, st = _post(srv, "/api/location", {"lat": 42.36, "lon": -71.06, "radius_nm": 8})
        assert status == 200 and st["location"] == {"lat": 42.36, "lon": -71.06, "radius_nm": 8.0}
        assert CONFIG.location.radius_nm == 8.0
        assert _post(srv, "/api/location", {"lat": "x"})[0] == 400
    finally:
        settings.set_location(*before)


def test_bad_json_and_404(server):
    srv, _, _ = server
    req = urllib.request.Request(f"http://127.0.0.1:{srv.port}/api/channels", data=b"{not json",
                                 headers={"Content-Type": "application/json"}, method="POST")
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req, timeout=5)
    assert e.value.code == 400
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(f"http://127.0.0.1:{srv.port}/nope", timeout=5)
    assert e.value.code == 404
    assert _post(srv, "/api/nope", {})[0] == 404
