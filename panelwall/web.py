"""Phone-friendly control server (standard library only).

    server = ControlServer(scheduler, settings).start()   # tries :80, falls back to :8080

Routes:
  GET  /                    single-page UI (inline HTML/JS; installable as an iOS home-screen app)
  GET  /manifest.webmanifest, /icon.png
  GET  /api/state           JSON: channels + enabled + current, brightness, quiet, location,
                            uptime, per-channel last fetch / last error
  POST /api/channel         {"channel": "radar"}                     pin one panel (manual mode)
  POST /api/mode            {"mode": "manual" | "auto"}
  POST /api/cycle           {"channels": [...], "dwell_seconds": 20, "alerts": true}   auto-cycle setup
  POST /api/channels        {"enabled": [...]}                       old name for the cycle list
  POST /api/show            {"channel": "radar", "seconds": 60}     temporary override (API only)
  POST /api/brightness      {"level": 0-255} and/or {"quiet": {"start","end","level"}}
  POST /api/location        {"lat", "lon", "radius_nm"}
  GET  /preview.png         the current frame through sinks.simulator.led_image at 3x,
                            regenerated at most once per second

Thread model: the HTTP handlers run on the server's threads. They READ
scheduler.latest / scheduler.current (plain attribute reads) and WRITE only
through Settings.set_* (locked). Nothing here touches the frame loop.
"""

from __future__ import annotations

import io
import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import numpy as np
from PIL import Image, ImageDraw

from .framebuffer import W, H
from .scheduler import Scheduler
from .settings import Settings
from .sinks.simulator import led_image

PREVIEW_SCALE = 3
PREVIEW_MIN_INTERVAL = 1.0


def lan_ip() -> str:
    """Best-effort LAN address for the 'open this on your phone' hint (no packets are sent)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return socket.gethostbyname(socket.gethostname())


def make_icon(size: int = 180) -> bytes:
    """App icon: dark tile with a 4x2 amber 'panel' grid."""
    img = Image.new("RGB", (size, size), (14, 14, 16))
    d = ImageDraw.Draw(img)
    pad, gap = size // 9, size // 30
    cw = (size - 2 * pad - 3 * gap) / 4
    ch = (size - 2 * pad - gap) / 2
    for r in range(2):
        for c in range(4):
            x0, y0 = pad + c * (cw + gap), pad + r * (ch + gap)
            d.rounded_rectangle([x0, y0, x0 + cw, y0 + ch], radius=size // 40, fill=(255, 176, 0))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


class ControlServer:
    def __init__(self, scheduler: Scheduler, settings: Settings, port: int | None = None,
                 host: str = "0.0.0.0"):
        self.scheduler = scheduler
        self.settings = settings
        self.host = host
        self.ports = [port] if port is not None else [80, 8080]
        self.port: int | None = None
        self.httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._preview: tuple[float, bytes] | None = None
        self._preview_lock = threading.Lock()
        self._icon = make_icon()

    def start(self) -> "ControlServer":
        last_err = None
        for p in self.ports:
            try:
                self.httpd = ThreadingHTTPServer((self.host, p), self._handler_class())
                break
            except OSError as e:          # EACCES on :80 without root, EADDRINUSE, ...
                last_err = e
                self.httpd = None
        if self.httpd is None:
            raise OSError(f"control server: no port available ({last_err})")
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        self._thread = threading.Thread(target=self.httpd.serve_forever, daemon=True, name="web")
        self._thread.start()
        return self

    def stop(self) -> None:
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()

    def url(self) -> str:
        return f"http://{lan_ip()}" + ("" if self.port == 80 else f":{self.port}")

    # ---- data -----------------------------------------------------------------------
    def state(self) -> dict:
        sc, st = self.scheduler, self.settings
        snap = st.snapshot()
        chans = []
        for c in sc.channels:
            try:
                status = c.status()
            except Exception as e:  # a channel's status must never break the API
                status = {"last_error": f"status(): {e}"}
            try:
                prio = c.priority()
            except Exception:
                prio = None
            chans.append({"name": c.name, "enabled": st.is_enabled(c.name), "priority": prio, "status": status})
        return {
            "uptime_s": round(time.time() - sc.started_at, 1),
            "frames": sc.frames,
            "current": sc.current_name,
            "channels": chans,
            "mode": snap["mode"],
            "channel": snap["channel"],
            "cycle": [c.name for c in sc.channels if st.in_cycle(c.name)],
            "dwell_seconds": snap["dwell_seconds"],
            "alerts": snap["alerts"],
            "enabled": [c.name for c in sc.channels if st.in_cycle(c.name)],
            "brightness": {"configured": snap["brightness"], "effective": snap["effective_brightness"],
                           "quiet": snap["quiet"]},
            "location": {"lat": snap["lat"], "lon": snap["lon"], "radius_nm": snap["radius_nm"]},
            "force": snap["force"],
            "settings_path": snap["path"],
            "settings_error": st.load_error,
        }

    def preview_png(self) -> bytes:
        with self._preview_lock:
            now = time.time()
            if self._preview and now - self._preview[0] < PREVIEW_MIN_INTERVAL:
                return self._preview[1]
            frame = self.scheduler.latest
            if frame is None:
                frame = np.zeros((H, W, 3), np.uint8)
            buf = io.BytesIO()
            led_image(frame, PREVIEW_SCALE).save(buf, "PNG")
            self._preview = (now, buf.getvalue())
            return self._preview[1]

    # ---- POST handlers: return (status, body) ------------------------------------------
    def post(self, path: str, body: dict) -> tuple[int, dict]:
        st = self.settings
        names = {c.name for c in self.scheduler.channels}
        if path == "/api/channel":
            ch = body.get("channel")
            if ch not in names:
                return 400, {"error": f"unknown channel {ch!r}", "known": sorted(names)}
            st.select_channel(ch)
        elif path == "/api/mode":
            try:
                st.set_mode(str(body.get("mode")))
            except ValueError as e:
                return 400, {"error": str(e)}
        elif path in ("/api/cycle", "/api/channels"):
            lst = body.get("channels", body.get("enabled", ...))
            if lst is not ... and not isinstance(lst, list):
                return 400, {"error": "expected {'channels': [names]}"}
            if lst is not ...:
                unknown = [n for n in lst if n not in names]
                if unknown:
                    return 400, {"error": f"unknown channels: {unknown}", "known": sorted(names)}
            try:
                st.set_cycle(lst, body.get("dwell_seconds"), body.get("alerts"))
            except (TypeError, ValueError):
                return 400, {"error": "dwell_seconds must be a number, alerts a boolean"}
        elif path == "/api/show":
            ch = body.get("channel")
            if ch is None:
                st.force_channel(None)
            elif ch not in names:
                return 400, {"error": f"unknown channel {ch!r}", "known": sorted(names)}
            else:
                st.force_channel(ch, float(body.get("seconds", 60)))
        elif path == "/api/brightness":
            if "level" in body:
                try:
                    st.set_brightness(int(body["level"]))
                except (TypeError, ValueError):
                    return 400, {"error": "level must be an int 0-255"}
            if "quiet" in body:
                try:
                    st.set_quiet(body["quiet"] or {})
                except (TypeError, ValueError, AttributeError):
                    return 400, {"error": "quiet must be {'start':'HH:MM','end':'HH:MM','level':0-255}"}
            if "level" not in body and "quiet" not in body:
                return 400, {"error": "expected 'level' and/or 'quiet'"}
        elif path == "/api/location":
            try:
                st.set_location(body.get("lat"), body.get("lon"), body.get("radius_nm"))
            except (TypeError, ValueError):
                return 400, {"error": "lat/lon/radius_nm must be numbers"}
        else:
            return 404, {"error": "not found"}
        return 200, self.state()

    # ---- the handler ---------------------------------------------------------------------
    def _handler_class(self):
        server = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "panelwall/0.1"

            def log_message(self, fmt, *args):  # quiet; the frame loop's console is more useful
                pass

            def _send(self, status: int, ctype: str, data: bytes, cache: str = "no-store"):
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", cache)
                self.end_headers()
                self.wfile.write(data)

            def _json(self, status: int, obj) -> None:
                self._send(status, "application/json", json.dumps(obj).encode())

            def do_GET(self):
                path = urlparse(self.path).path
                if path == "/":
                    self._send(200, "text/html; charset=utf-8", INDEX_HTML.encode())
                elif path == "/api/state":
                    self._json(200, server.state())
                elif path == "/preview.png":
                    self._send(200, "image/png", server.preview_png())
                elif path == "/manifest.webmanifest":
                    self._send(200, "application/manifest+json", json.dumps(MANIFEST).encode(), "max-age=3600")
                elif path in ("/icon.png", "/apple-touch-icon.png"):
                    self._send(200, "image/png", server._icon, "max-age=86400")
                else:
                    self._json(404, {"error": "not found"})

            def do_POST(self):
                path = urlparse(self.path).path
                n = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(n) if n else b""
                try:
                    body = json.loads(raw.decode() or "{}")
                    if not isinstance(body, dict):
                        raise ValueError("body must be a JSON object")
                except ValueError as e:
                    self._json(400, {"error": f"bad JSON: {e}"})
                    return
                try:
                    status, obj = server.post(path, body)
                except Exception as e:  # never let a handler bug kill the server thread
                    status, obj = 500, {"error": f"{type(e).__name__}: {e}"}
                self._json(status, obj)

        return Handler


MANIFEST = {
    "name": "panelwall",
    "short_name": "panelwall",
    "start_url": "/",
    "display": "standalone",
    "background_color": "#0e0e10",
    "theme_color": "#0e0e10",
    "icons": [{"src": "/icon.png", "sizes": "180x180", "type": "image/png"}],
}

INDEX_HTML = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="panelwall">
<meta name="theme-color" content="#0e0e10">
<link rel="manifest" href="/manifest.webmanifest">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
<title>panelwall</title>
<style>
  :root { color-scheme: dark; --bg:#0e0e10; --card:#18181c; --fg:#e8e8e8; --dim:#8a8a90; --amber:#ffb000; --line:#2a2a30; }
  * { box-sizing: border-box; }
  body { margin:0; background:var(--bg); color:var(--fg); font:16px/1.4 -apple-system, system-ui, sans-serif;
         padding: env(safe-area-inset-top) 12px calc(env(safe-area-inset-bottom) + 24px); }
  h1 { font-size:20px; margin:16px 0 8px; letter-spacing:.04em; }
  h1 small { color:var(--dim); font-weight:normal; font-size:13px; margin-left:8px; }
  h2 { font-size:13px; text-transform:uppercase; letter-spacing:.08em; color:var(--dim); margin:20px 0 8px; }
  .card { background:var(--card); border-radius:12px; padding:12px; }
  #preview { display:block; width:100%; image-rendering:pixelated; border-radius:8px; background:#000; aspect-ratio:4/1; }
  .row { display:flex; align-items:center; justify-content:space-between; gap:10px; padding:10px 0; border-top:1px solid var(--line); }
  .row:first-child { border-top:0; padding-top:0; }
  .row:last-child { padding-bottom:0; }
  .name { font-weight:600; text-transform:uppercase; letter-spacing:.04em; }
  .meta { color:var(--dim); font-size:12px; }
  .err { color:#f05050; }
  .now { color:var(--amber); }
  button { background:#2a2a30; color:var(--fg); border:0; border-radius:8px; padding:8px 12px; font:inherit; font-size:14px; }
  button.primary { background:var(--amber); color:#000; font-weight:600; }
  button:active { opacity:.7; }
  input[type=range] { width:100%; accent-color:var(--amber); }
  input[type=time], input[type=number], input[type=text] { background:#0e0e10; color:var(--fg); border:1px solid var(--line);
        border-radius:8px; padding:8px; font:inherit; width:100%; }
  label { display:block; font-size:12px; color:var(--dim); margin-bottom:4px; }
  .grid { display:grid; grid-template-columns:1fr 1fr 1fr; gap:8px; }
  .seg { display:flex; gap:6px; }
  .seg button { flex:1; padding:10px; }
  .seg button.on { background:var(--amber); color:#000; font-weight:600; }
  .pick { cursor:pointer; }
  .pick.on .name { color:var(--amber); }
  .pick .radio { width:18px; height:18px; border-radius:50%; border:2px solid #555; flex:none; }
  .pick.on .radio { border-color:var(--amber); background:var(--amber); box-shadow: inset 0 0 0 4px var(--card); }
  .switch { position:relative; width:46px; height:28px; flex:none; }
  .switch input { opacity:0; width:0; height:0; }
  .switch span { position:absolute; inset:0; background:#3a3a42; border-radius:14px; transition:.15s; }
  .switch span:before { content:""; position:absolute; width:22px; height:22px; left:3px; top:3px; background:#fff; border-radius:50%; transition:.15s; }
  .switch input:checked + span { background:var(--amber); }
  .switch input:checked + span:before { transform:translateX(18px); }
  #toast { position:fixed; left:50%; bottom:calc(env(safe-area-inset-bottom) + 16px); transform:translateX(-50%);
           background:#2a2a30; padding:8px 14px; border-radius:20px; font-size:13px; opacity:0; transition:.2s; pointer-events:none; }
  #toast.on { opacity:1; }
</style></head>
<body>
<h1>panelwall <small id="uptime"></small></h1>
<div class="card">
  <img id="preview" src="/preview.png" alt="current frame">
  <div class="row" style="margin-top:10px"><div><span class="meta">Now showing</span><br><span class="name now" id="current">-</span></div>
    <div id="forceinfo" class="meta"></div><button id="release" hidden>Release</button></div>
</div>

<h2>Display</h2>
<div class="card">
  <div class="seg" id="modeseg">
    <button data-mode="manual">Pick one panel</button>
    <button data-mode="auto">Auto cycle</button>
  </div>
  <div id="autoopts" hidden>
    <div class="row"><div>Stay on each panel <span class="meta" id="dwelllabel"></span></div></div>
    <input type="range" id="dwell" min="5" max="120" step="5">
    <div class="row"><div>Alerts interrupt the cycle<br><span class="meta">a score, a new closest aircraft</span></div>
      <label class="switch"><input type="checkbox" id="alerts"><span></span></label></div>
    <p class="meta" style="margin:8px 0 0">Tick the panels to cycle through. Panels with nothing to show are skipped.</p>
  </div>
</div>

<h2 id="chanhead">Panels</h2>
<div class="card" id="channels"></div>

<h2>Brightness</h2>
<div class="card">
  <div class="row"><div>Level <span class="meta" id="blabel"></span></div><div class="meta" id="beff"></div></div>
  <input type="range" id="bright" min="0" max="255" step="1">
  <div class="grid" style="margin-top:10px">
    <div><label>Quiet from</label><input type="time" id="qstart"></div>
    <div><label>Quiet until</label><input type="time" id="qend"></div>
    <div><label>Quiet level</label><input type="number" id="qlevel" min="0" max="255"></div>
  </div>
  <div style="margin-top:10px; text-align:right"><button class="primary" id="savequiet">Save quiet hours</button></div>
</div>

<h2>Location</h2>
<div class="card">
  <div class="grid">
    <div><label>Latitude</label><input type="number" step="0.0001" id="lat"></div>
    <div><label>Longitude</label><input type="number" step="0.0001" id="lon"></div>
    <div><label>Radius (nm)</label><input type="number" step="1" min="1" id="radius"></div>
  </div>
  <div style="margin-top:10px; text-align:right"><button class="primary" id="saveloc">Save location</button></div>
</div>

<h2>Status</h2>
<div class="card" id="status"></div>
<div id="toast"></div>

<script>
const $ = (id) => document.getElementById(id);
let state = null, dirtyBright = false;

function ago(ts) {
  if (!ts) return 'never';
  const s = Math.max(0, Math.round(Date.now()/1000 - ts));
  return s < 60 ? s + 's ago' : s < 3600 ? Math.round(s/60) + 'm ago' : Math.round(s/3600) + 'h ago';
}
function fmtUptime(s) { s = Math.round(s); const h = Math.floor(s/3600), m = Math.floor(s%3600/60); return h ? `${h}h ${m}m up` : `${m}m up`; }
function toast(msg) { const t = $('toast'); t.textContent = msg; t.classList.add('on'); setTimeout(() => t.classList.remove('on'), 1600); }

async function api(path, body) {
  const r = await fetch(path, body ? {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)} : {});
  const j = await r.json();
  if (!r.ok) { toast(j.error || ('HTTP ' + r.status)); throw new Error(j.error); }
  if (body) { state = j; render(); }
  return j;
}

function render() {
  const s = state; if (!s) return;
  $('uptime').textContent = fmtUptime(s.uptime_s);
  $('current').textContent = s.current || 'nothing';
  const f = s.force;
  $('forceinfo').textContent = f ? `override: ${f.channel} for ${Math.max(0, Math.round(f.until - Date.now()/1000))}s` : '';
  $('release').hidden = !f;
  const auto = s.mode === 'auto';
  document.querySelectorAll('#modeseg button').forEach(b => b.classList.toggle('on', b.dataset.mode === s.mode));
  $('autoopts').hidden = !auto;
  $('chanhead').textContent = auto ? 'Panels in the cycle' : 'Panels';
  if (document.activeElement !== $('dwell')) $('dwell').value = s.dwell_seconds;
  $('dwelllabel').textContent = `${Math.round($('dwell').value)} s`;
  $('alerts').checked = !!s.alerts;
  const cyc = new Set(s.cycle);
  $('channels').innerHTML = s.channels.map(c => auto ? `
    <div class="row">
      <div><div class="name ${c.name === s.current ? 'now' : ''}">${c.name}</div>
           <div class="meta">${c.priority > 0 ? 'has content' : 'nothing to show right now'}${c.status.last_error ? ' · <span class="err">error</span>' : ''}</div></div>
      <label class="switch"><input type="checkbox" data-cycle="${c.name}" ${cyc.has(c.name) ? 'checked' : ''}><span></span></label>
    </div>` : `
    <div class="row pick ${c.name === s.channel ? 'on' : ''}" data-pick="${c.name}">
      <div><div class="name">${c.name}</div>
           <div class="meta">${c.status.last_error ? '<span class="err">error</span>' : c.status.paused ? 'paused, not on screen' : 'data ' + ago(c.status.updated_at)}</div></div>
      <div class="radio"></div>
    </div>`).join('');
  if (!dirtyBright) { $('bright').value = s.brightness.configured; }
  $('blabel').textContent = `${Math.round(s.brightness.configured/255*100)}%`;
  $('beff').textContent = s.brightness.effective !== s.brightness.configured ? `quiet hours: ${Math.round(s.brightness.effective/255*100)}% now` : '';
  if (document.activeElement.tagName !== 'INPUT') {
    $('qstart').value = s.brightness.quiet.start; $('qend').value = s.brightness.quiet.end; $('qlevel').value = s.brightness.quiet.level;
    $('lat').value = s.location.lat; $('lon').value = s.location.lon; $('radius').value = s.location.radius_nm;
  }
  $('status').innerHTML = s.channels.map(c => `
    <div class="row"><div><div class="name">${c.name}</div>
      <div class="meta">${Object.entries(c.status).filter(([k]) => !['last_error','updated_at'].includes(k)).map(([k,v]) => `${k} ${v}`).join(' · ') || ''}</div>
      <div class="meta">${c.status.last_error ? '<span class="err">' + c.status.last_error + '</span>' : (c.status.paused ? 'paused (not on screen) · ' : '') + 'last fetch ' + ago(c.status.updated_at)}</div></div></div>`).join('')
    + `<div class="row"><div class="meta">settings: ${s.settings_path}${s.settings_error ? ' <span class="err">' + s.settings_error + '</span>' : ''} · ${s.frames} frames</div></div>`;
}

$('modeseg').addEventListener('click', (e) => {
  const b = e.target.closest('button[data-mode]'); if (b) api('/api/mode', {mode: b.dataset.mode}).then(() => toast(b.dataset.mode === 'auto' ? 'auto cycle on' : 'showing one panel'));
});
$('channels').addEventListener('click', (e) => {
  const p = e.target.closest('.pick'); if (p) api('/api/channel', {channel: p.dataset.pick}).then(() => toast('showing ' + p.dataset.pick));
});
$('channels').addEventListener('change', (e) => {
  const t = e.target.closest('input[data-cycle]'); if (!t) return;
  const channels = [...document.querySelectorAll('input[data-cycle]')].filter(i => i.checked).map(i => i.dataset.cycle);
  api('/api/cycle', {channels});
});
$('dwell').oninput = () => { $('dwelllabel').textContent = `${$('dwell').value} s`; };
$('dwell').onchange = () => api('/api/cycle', {dwell_seconds: +$('dwell').value}).then(() => toast(`${$('dwell').value} s per panel`));
$('alerts').onchange = () => api('/api/cycle', {alerts: $('alerts').checked});
$('release').onclick = () => api('/api/show', {channel: null});
$('bright').oninput = () => { dirtyBright = true; $('blabel').textContent = `${Math.round($('bright').value/255*100)}%`; };
$('bright').onchange = () => api('/api/brightness', {level: +$('bright').value}).then(() => { dirtyBright = false; toast('brightness saved'); });
$('savequiet').onclick = () => api('/api/brightness', {quiet: {start: $('qstart').value, end: $('qend').value, level: +$('qlevel').value}}).then(() => toast('quiet hours saved'));
$('saveloc').onclick = () => api('/api/location', {lat: +$('lat').value, lon: +$('lon').value, radius_nm: +$('radius').value}).then(() => toast('location saved'));

async function refresh() { try { state = await api('/api/state'); render(); } catch (e) {} }
setInterval(refresh, 2000); refresh();
setInterval(() => { $('preview').src = '/preview.png?' + Date.now(); }, 1000);
</script>
</body></html>
"""
