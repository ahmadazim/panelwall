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


def cmd_demo(args):
    from .channels import FlightsChannel
    from .data.adsb import parse_aircraft
    from .scheduler import Scheduler
    from pathlib import Path

    fx = json.loads((Path(__file__).resolve().parent.parent / "fixtures" / "bos_point.json").read_text())
    loc = CONFIG.location
    acs = [parse_aircraft(a, loc.lat, loc.lon) for a in fx["ac"]]
    for a, route in zip(acs, fx.get("_routes", [])):
        a.origin, a.destination = route
    acs.sort(key=lambda a: a.distance_nm or 1e9)
    Scheduler([FlightsChannel(static=acs)], _sink(args), args.fps).run(args.seconds)


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

    for name, fn in (("run", cmd_run), ("demo", cmd_demo), ("test", cmd_test)):
        sp = sub.add_parser(name)
        common(sp)
        sp.set_defaults(fn=fn)
    sp = sub.add_parser("probe")
    sp.add_argument("-n", type=int, default=3)
    sp.add_argument("--routes", nargs="+", metavar="CALLSIGN",
                    help="skip the aircraft query; POST these callsigns to routeset and print the raw reply")
    sp.set_defaults(fn=cmd_probe)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
