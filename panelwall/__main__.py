"""CLI.

  python -m panelwall run   --sink sim                 # develop on the Mac (+ control UI on :8080)
  python -m panelwall run   --sink colorlight          # on the Pi (sudo; control UI on :80)
  python -m panelwall run   --channels flights,mbta    # restrict which channels load
  python -m panelwall test  --sink colorlight          # bring-up test pattern
  python -m panelwall probe                            # dump live API JSON
  python -m panelwall demo-<name>                      # fixture data, no network (flights, radar, silhouette, mbta)
  python -m panelwall sheet                            # every channel -> design/channels_sheet.png
  python -m panelwall sprites                          # every aircraft sprite -> design/sprites_sheet.png
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import CONFIG


def _sink(args):
    from .sinks import make_sink

    if args.sink == "colorlight":
        return make_sink("colorlight", iface=args.iface, brightness=CONFIG.display.brightness)
    return make_sink("sim", png_path=args.png, window=None if not args.no_window else False)


DEFAULT_CHANNELS = ["flightwall", "flights", "radar", "silhouette", "mbta", "sports", "forecast", "prayers"]
AIRCRAFT_CHANNELS = {"flightwall", "flights", "radar", "silhouette"}


def build_channels(names: list[str]):
    """Live channels. Aircraft channels share ONE AircraftFeed (one adsb.lol poller)."""
    from . import channels as ch

    feed = None
    if AIRCRAFT_CHANNELS & set(names):
        from .data.feed import AircraftFeed
        feed = AircraftFeed()
    out = []
    for name in names:
        if name == "flightwall":
            out.append(ch.FlightWallChannel(feed=feed))
        elif name == "flights":
            out.append(ch.FlightsChannel(feed=feed))
        elif name == "radar":
            out.append(ch.RadarChannel(feed=feed))
        elif name == "silhouette":
            out.append(ch.SilhouetteChannel(feed=feed))
        elif name == "mbta":
            out.append(ch.MbtaChannel())
        elif name == "sports":
            out.append(ch.SportsChannel())
        elif name == "forecast":
            out.append(ch.ForecastChannel())
        elif name == "prayers":
            out.append(ch.PrayersChannel())
        elif name == "testpattern":
            out.append(ch.TestPatternChannel())
        else:
            raise SystemExit(f"unknown channel {name!r}; choose from {DEFAULT_CHANNELS + ['testpattern']}")
    if feed is not None:   # exactly one channel closes the shared feed on shutdown
        sharers = [c for c in out if getattr(c, "feed", None) is feed]
        for c in sharers:
            c._owns_feed = c is sharers[0]
    return out


def cmd_run(args):
    from .scheduler import Scheduler
    from .settings import Settings

    settings = Settings()          # ~/.panelwall/settings.json overrides config.py defaults
    if settings.load_error:
        print(f"[settings] {settings.load_error} (using defaults)", flush=True)
    names = [n.strip() for n in args.channels.split(",") if n.strip()]
    loc = CONFIG.location
    print(f"[run] channels: {', '.join(names)}", flush=True)
    if AIRCRAFT_CHANNELS & set(names):
        print(f"[run] aircraft within {loc.radius_nm:g} nm of {loc.lat:.4f},{loc.lon:.4f} via {CONFIG.data.adsb_base}, "
              f"polling every {CONFIG.data.poll_seconds:g}s", flush=True)
    if "mbta" in names:
        m = CONFIG.mbta
        print(f"[run] MBTA {m.route} line, home {m.home_stop}, {m.branch} branch, key {'set' if m.api_key else 'not set (fine)'}", flush=True)
    sched = Scheduler(build_channels(names), _sink(args), args.fps, settings=settings)
    if not args.no_web:
        from .web import ControlServer
        try:
            web = ControlServer(sched, settings, port=args.port).start()
            print(f"[web] control UI at {web.url()}  (open on your phone; Share > Add to Home Screen)", flush=True)
        except OSError as e:
            print(f"[web] disabled: {e}", flush=True)
    sched.run(args.seconds)


FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def fixture_aircraft(around=None, path: str = "bos_point.json"):
    """Aircraft from a readsb-shaped fixture (+ `_routes` sidecar), re-centred on `around` (lat, lon).

    The fixtures are Boston traffic; when the configured location is elsewhere the
    positions are shifted so the radar scope still shows them in range.
    """
    from .data.adsb import parse_aircraft

    fx = json.loads((FIXTURES / path).read_text())
    lat0, lon0 = 42.3601, -71.0589
    lat, lon = around or (lat0, lon0)
    raw = []
    for a in fx["ac"]:
        a = dict(a)
        a["lat"], a["lon"] = a["lat"] - lat0 + lat, a["lon"] - lon0 + lon
        raw.append(a)
    acs = [parse_aircraft(a, lat, lon) for a in raw]
    for a, route in zip(acs, fx.get("_routes", [])):
        a.origin, a.destination = route
    acs.sort(key=lambda a: a.distance_nm or 1e9)
    return acs


def fixture_feed(n: int | None = None, path: str = "bos_point.json"):
    """A static AircraftFeed with the fixture traffic (first n aircraft if given)."""
    from .data.feed import AircraftFeed

    loc = CONFIG.location
    acs = fixture_aircraft((loc.lat, loc.lon), path)
    return AircraftFeed(static=acs if n is None else acs[:n])


def fixture_channel(name: str, **kw):
    """Build one channel driven by fixture data (no network)."""
    from . import channels as ch

    if name == "flights":
        return ch.FlightsChannel(feed=fixture_feed())
    if name == "flightwall":
        case = kw.get("case") or "a"
        return ch.FlightWallChannel(feed=fixture_feed(path=f"flightwall_{case}.json"))
    if name == "radar":
        return ch.RadarChannel(feed=fixture_feed())
    if name == "silhouette":
        return ch.SilhouetteChannel(feed=fixture_feed(1))   # one aircraft -> the hero card shows
    if name == "mbta":
        from .data.mbta import MbtaFeed
        return ch.MbtaChannel(feed=MbtaFeed(static=json.loads((FIXTURES / "mbta_red.json").read_text())))
    if name == "sports":
        from .data.espn import SportsFeed
        return ch.SportsChannel(feed=SportsFeed(static=json.loads((FIXTURES / "espn_scoreboards.json").read_text())))
    if name == "prayers":
        from datetime import datetime
        return ch.PrayersChannel(static_html=(FIXTURES / "fiveprayers.html").read_text(),
                                 now=datetime.fromisoformat("2026-09-17T15:40:00-04:00"))
    if name == "forecast":
        from .data.openmeteo import ForecastFeed
        return ch.ForecastChannel(feed=ForecastFeed(static=json.loads((FIXTURES / "openmeteo.json").read_text())), view=kw.get("view"))
    if name == "testpattern":
        return ch.TestPatternChannel()
    raise ValueError(f"no fixture demo for {name!r}")


DEMO_CHANNELS = ["flightwall", "flights", "radar", "silhouette", "mbta", "sports", "forecast", "prayers", "testpattern"]


def cmd_demo(args):
    from .scheduler import Scheduler

    kw = {"view": args.view} if getattr(args, "view", None) else {}
    if getattr(args, "case", None):
        kw["case"] = args.case
    Scheduler([fixture_channel(args.channel, **kw)], _sink(args), args.fps).run(args.seconds)


DESIGN = Path(__file__).resolve().parent.parent / "design"


def render_channel_frame(name: str, warm_seconds: float = 1.3, **kw):
    """One representative frame of a fixture channel (numpy HxWx3)."""
    from .framebuffer import Frame

    ch = fixture_channel(name, **kw)
    for _ in range(int(warm_seconds / 0.05)):   # let sweeps/animations move off their zero state
        ch.tick(0.05)
    f = Frame()
    ch.render(f)
    ch.close()
    return f.to_array()


def cmd_sheet(args):
    from PIL import Image, ImageDraw, ImageFont
    from . import fonts
    from .sinks.simulator import led_image

    scale, pad, label_h = 4, 16, 26
    font = ImageFont.truetype(fonts.SMALL.path, 16)
    tiles = []
    for n in DEMO_CHANNELS:
        if n == "flightwall":
            for case in "abcd":
                tiles.append((f"flightwall (case {case})", led_image(render_channel_frame(n, case=case), scale)))
        elif n == "forecast":
            for v in ("week", "hourly"):
                tiles.append((f"forecast ({v})", led_image(render_channel_frame(n, view=v), scale)))
        else:
            tiles.append((n, led_image(render_channel_frame(n), scale)))
    tw, th = tiles[0][1].size
    sheet = Image.new("RGB", (tw + 2 * pad, len(tiles) * (th + label_h + pad) + pad), (20, 20, 22))
    d = ImageDraw.Draw(sheet)
    y = pad
    for n, tile in tiles:
        d.text((pad, y), f"{n.upper()}   (256 x 64, fixture data)", font=font, fill=(220, 220, 220))
        y += label_h
        sheet.paste(tile, (pad, y))
        y += th + pad
    out = DESIGN / "channels_sheet.png"
    sheet.save(out)
    print(f"wrote {out}  {sheet.size[0]}x{sheet.size[1]}")


def cmd_logos(args):
    """Regenerate assets/logos/*.png and render them at 6x to design/logos_sheet.png."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("build_logos", Path(__file__).resolve().parent.parent / "tools" / "build_logos.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.build()
    out = DESIGN / "logos_sheet.png"
    mod.sheet(6).save(out)
    print(f"wrote {len(mod.LOGOS)} logos to {mod.OUT} and {out}")


def cmd_sprites(args):
    from .sprites import render_sheet

    out = DESIGN / "sprites_sheet.png"
    render_sheet().save(out)
    print(f"wrote {out}")


def cmd_test(args):
    from .channels import TestPatternChannel
    from .scheduler import Scheduler

    Scheduler([TestPatternChannel()], _sink(args), args.fps).run(args.seconds)


def cmd_probe_sports(args):
    """Print the ESPN scoreboard URL and raw JSON (head) for each tracked league."""
    from datetime import datetime, timedelta
    from .data.espn import EspnClient, parse_scoreboard

    c = EspnClient()
    today = datetime.now().astimezone().date()
    start, end = datetime.combine(today - timedelta(days=1), datetime.min.time()), datetime.combine(today + timedelta(days=CONFIG.sports.days_ahead), datetime.min.time())
    leagues = sorted({t[0] for t in CONFIG.sports.teams})
    for lg in leagues:
        print("GET", c.url(lg, start, end))
        doc = c.scoreboard(lg, start, end)
        if doc is None:
            print("  ", c.last_error)
            continue
        raw = json.dumps(doc)
        print(f"  {len(raw)} bytes, {len(doc.get('events', []))} events. Raw head:\n  {raw[:args.n]}")
        for g in parse_scoreboard(doc, lg):
            print(f"  {g.start:%m-%d %H:%MZ} {g.state:4} {g.away.abbreviation:>4} {g.away.score!s:>3} @ {g.home.abbreviation:<4} {g.home.score!s:>3}  {g.short_detail!r}  {g.situation or ''}")


def cmd_probe_forecast(args):
    """Print the Open-Meteo URL and the raw JSON head, then the parsed summary."""
    from .data.openmeteo import OpenMeteoClient, parse_forecast, wmo, compass

    c = OpenMeteoClient()
    loc = CONFIG.location
    print("GET", c.url(loc.lat, loc.lon))
    doc = c.fetch(loc.lat, loc.lon)
    if doc is None:
        print(" ", c.last_error)
        return
    raw = json.dumps(doc)
    print(f"  {len(raw)} bytes. Raw head:\n  {raw[:args.n]}")
    fc = parse_forecast(doc)
    print(f"\n  now {fc.time}: {fc.temp}F feels {fc.feels}F hum {fc.humidity}% code {fc.code} {wmo(fc.code)} wind {fc.wind_kn}kn {compass(fc.wind_dir)} uv {fc.uv}")
    for d in fc.daily:
        print(f"  {d.date:%a %m-%d} code {d.code:>2} {wmo(d.code)[1]:14} hi {d.hi} lo {d.lo} precip {d.precip}% rise {d.sunrise:%H:%M} set {d.sunset:%H:%M}")
    print(f"  hourly: {len(fc.hourly)} entries from {fc.hourly[0].time if fc.hourly else None}")


def cmd_probe_prayers(args):
    """Fetch the fiveprayers.org page, show what we parsed from it and today's computed times."""
    from datetime import date, timedelta
    from zoneinfo import ZoneInfo
    from .data.prayers import PrayersClient, parse_page, day_times

    c = PrayersClient()
    print("GET", c.url)
    html = c.fetch_html()
    if html is None:
        print(" ", c.last_error)
        return
    cfg = parse_page(html)
    print(f"  {len(html)} bytes. title={cfg.title!r} location={cfg.location!r} method={cfg.method} clclt={cfg.clclt}")
    print(f"  lat/lon {cfg.lat:.4f},{cfg.lon:.4f} elev {cfg.elev:g}  fajr {cfg.fajr_angle:g} deg  isha {cfg.isha_angle:g} deg / {cfg.isha_minutes:g} min  asr factor {cfg.asr_factor:g}")
    print(f"  iqama offsets (fajr,dhuhr,asr,maghrib,isha,jumuah) {cfg.iqama_offsets}; fixed iqama {cfg.fixed_iqama}; jumuah {cfg.jumuah}")
    tz = ZoneInfo(CONFIG.prayers.timezone)
    for d in (date.today(), date.today() + timedelta(days=1)):
        pd = day_times(cfg, d, tz)
        print(f"  {d}: " + "  ".join(f"{n} {t:%-I:%M%p}" for n, t in pd.athan.items())
              + "  | iqama " + "  ".join(f"{n} {t:%-I:%M%p}" for n, t in pd.iqama.items())
              + (f"  | jumuah {pd.jumuah:%-I:%M%p}" if pd.jumuah else ""))


def cmd_probe(args):
    from .data.adsb import AdsbClient, ApiError

    c = AdsbClient()
    loc = CONFIG.location
    if args.routes:
        from .data.adsb import parse_adsbdb_route
        for cs in args.routes:
            print("GET", f"{c.routes_base}/v0/callsign/{cs}")
            try:
                status, body = c.route_raw(cs)
                print(f"HTTP {status}, {len(body)} bytes: {body[:600]}")
                print("  parsed:", parse_adsbdb_route(json.loads(body)))
            except ApiError as e:
                print(" ", e)
        return
    raw = c.fetch_raw(loc.lat, loc.lon, loc.radius_nm)
    acs = raw.get("ac", [])
    print(f"{len(acs)} aircraft within {loc.radius_nm} nm of {loc.lat},{loc.lon}")
    for a in acs[: args.n]:
        print(json.dumps(a, indent=1)[:1200])
        print("-" * 60)
    parsed = c.nearby(loc.lat, loc.lon, loc.radius_nm)
    print("\nparsed:")
    for a in parsed[: args.n]:
        print(f"  {a.flight:9} {a.route:8} {a.type_name:12} alt={a.altitude} spd={a.speed} trk={a.track} vr={a.vrate} d={a.distance_nm and round(a.distance_nm,1)}nm")
    if c.last_error:
        print("last_error:", c.last_error)


def main(argv=None):
    p = argparse.ArgumentParser(prog="panelwall")
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("--sink", choices=["sim", "colorlight"], default="sim")
        sp.add_argument("--iface", default=CONFIG.colorlight.iface)
        sp.add_argument("--fps", type=float, default=CONFIG.display.fps)
        sp.add_argument("--seconds", type=float, default=None, help="run for N seconds then exit")
        sp.add_argument("--png", default="sim.png", help="simulator output path when no window")
        sp.add_argument("--no-window", action="store_true", help="simulator: force PNG output")

    sp = sub.add_parser("run", help="live data; starts the phone control UI")
    common(sp)
    sp.add_argument("--channels", default=",".join(DEFAULT_CHANNELS), help="comma list of channels to load")
    sp.add_argument("--port", type=int, default=None, help="control UI port (default: 80, then 8080)")
    sp.add_argument("--no-web", action="store_true", help="don't start the control UI")
    sp.set_defaults(fn=cmd_run)
    sp = sub.add_parser("test", help="panel bring-up test pattern")
    common(sp)
    sp.set_defaults(fn=cmd_test)
    sp = sub.add_parser("demo", help="fixture-driven flights channel (alias of demo-flights)")
    common(sp)
    sp.set_defaults(fn=cmd_demo, channel="flights")
    for name in DEMO_CHANNELS:
        sp = sub.add_parser(f"demo-{name}", help=f"fixture-driven {name} channel, no network")
        common(sp)
        if name == "forecast":
            sp.add_argument("--view", choices=["week", "hourly"], default=None, help="pin one view (default: alternate)")
        if name == "flightwall":
            sp.add_argument("--case", choices=["a", "b", "c", "d"], default="a",
                            help="a: 3 flights with routes, b: private no route, c: 7 flights (+2 more), d: empty sky")
        sp.set_defaults(fn=cmd_demo, channel=name)
    sub.add_parser("sheet", help="render every channel's fixture demo to design/channels_sheet.png").set_defaults(fn=cmd_sheet)
    sub.add_parser("logos", help="regenerate the airline logo tiles and design/logos_sheet.png (6x)").set_defaults(fn=cmd_logos)
    sub.add_parser("sprites", help="render every aircraft sprite to design/sprites_sheet.png").set_defaults(fn=cmd_sprites)
    sp = sub.add_parser("probe-sports", help="raw ESPN scoreboard JSON for the tracked leagues")
    sp.add_argument("-n", type=int, default=600, help="bytes of raw JSON to print per league")
    sp.set_defaults(fn=cmd_probe_sports)
    sub.add_parser("probe-prayers", help="fetch the fiveprayers.org page and print the parsed config + times").set_defaults(fn=cmd_probe_prayers)
    sp = sub.add_parser("probe-forecast", help="raw Open-Meteo JSON for CONFIG.location")
    sp.add_argument("-n", type=int, default=600, help="bytes of raw JSON to print")
    sp.set_defaults(fn=cmd_probe_forecast)
    sp = sub.add_parser("probe")
    sp.add_argument("-n", type=int, default=3)
    sp.add_argument("--routes", nargs="+", metavar="CALLSIGN",
                    help="skip the aircraft query; look these callsigns up on the route API and print the raw reply")
    sp.set_defaults(fn=cmd_probe)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
