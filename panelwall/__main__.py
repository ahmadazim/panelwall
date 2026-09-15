"""CLI.

  python -m panelwall run   --sink sim                 # develop on the Mac
  python -m panelwall run   --sink colorlight          # on the Pi (sudo)
  python -m panelwall test  --sink colorlight          # bring-up test pattern
  python -m panelwall probe                            # dump live API JSON
  python -m panelwall demo  --sink sim                 # fixture data, no network
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


def cmd_run(args):
    from .channels import FlightsChannel
    from .scheduler import Scheduler

    loc = CONFIG.location
    print(f"[run] aircraft within {loc.radius_nm:g} nm of {loc.lat:.4f},{loc.lon:.4f} via {CONFIG.data.adsb_base}, "
          f"polling every {CONFIG.data.poll_seconds:g}s", flush=True)
    Scheduler([FlightsChannel()], _sink(args), args.fps).run(args.seconds)


FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def fixture_aircraft(around=None):
    """Aircraft from fixtures/bos_point.json, re-centred on `around` (lat, lon) if given.

    The fixture is Boston traffic; when the configured location is elsewhere the
    positions are shifted so the radar scope still shows them in range.
    """
    from .data.adsb import parse_aircraft

    fx = json.loads((FIXTURES / "bos_point.json").read_text())
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


def fixture_feed(n: int | None = None):
    """A static AircraftFeed with the fixture traffic (first n aircraft if given)."""
    from .data.feed import AircraftFeed

    loc = CONFIG.location
    acs = fixture_aircraft((loc.lat, loc.lon))
    return AircraftFeed(static=acs if n is None else acs[:n])


def fixture_channel(name: str):
    """Build one channel driven by fixture data (no network)."""
    from . import channels as ch

    if name == "flights":
        return ch.FlightsChannel(feed=fixture_feed())
    if name == "radar":
        return ch.RadarChannel(feed=fixture_feed())
    if name == "silhouette":
        return ch.SilhouetteChannel(feed=fixture_feed(1))   # one aircraft -> the hero card shows
    if name == "testpattern":
        return ch.TestPatternChannel()
    raise ValueError(f"no fixture demo for {name!r}")


DEMO_CHANNELS = ["flights", "radar", "silhouette", "testpattern"]


def cmd_demo(args):
    from .scheduler import Scheduler

    Scheduler([fixture_channel(args.channel)], _sink(args), args.fps).run(args.seconds)


DESIGN = Path(__file__).resolve().parent.parent / "design"


def cmd_sprites(args):
    from .sprites import render_sheet

    out = DESIGN / "sprites_sheet.png"
    render_sheet().save(out)
    print(f"wrote {out}")


def cmd_test(args):
    from .channels import TestPatternChannel
    from .scheduler import Scheduler

    Scheduler([TestPatternChannel()], _sink(args), args.fps).run(args.seconds)


def cmd_probe(args):
    from .data.adsb import AdsbClient, ApiError

    c = AdsbClient()
    loc = CONFIG.location
    if args.routes:
        planes = [{"callsign": cs, "lat": loc.lat, "lng": loc.lon} for cs in args.routes]
        print("POST", c.base + "/api/0/routeset", json.dumps({"planes": planes}))
        try:
            status, body = c.routeset_raw(planes)
            print(f"HTTP {status}, {len(body)} bytes:\n{body[:3000]}")
        except ApiError as e:
            print(e)
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

    for name, fn in (("run", cmd_run), ("test", cmd_test)):
        sp = sub.add_parser(name)
        common(sp)
        sp.set_defaults(fn=fn)
    sp = sub.add_parser("demo", help="fixture-driven flights channel (alias of demo-flights)")
    common(sp)
    sp.set_defaults(fn=cmd_demo, channel="flights")
    for name in DEMO_CHANNELS:
        sp = sub.add_parser(f"demo-{name}", help=f"fixture-driven {name} channel, no network")
        common(sp)
        sp.set_defaults(fn=cmd_demo, channel=name)
    sub.add_parser("sprites", help="render every aircraft sprite to design/sprites_sheet.png").set_defaults(fn=cmd_sprites)
    sp = sub.add_parser("probe")
    sp.add_argument("-n", type=int, default=3)
    sp.add_argument("--routes", nargs="+", metavar="CALLSIGN",
                    help="skip the aircraft query; POST these callsigns to routeset and print the raw reply")
    sp.set_defaults(fn=cmd_probe)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
