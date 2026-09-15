# panelwall

A 256×64 LED matrix (8× P5 64×32 panels, 4 wide × 2 tall) driven by a Raspberry Pi 4
through a Colorlight 5A‑75B receiver card. Shows what's overhead (from free ADS‑B data),
a radar scope, a hero card for the closest aircraft, and the MBTA Red Line. Controlled
from your phone.

```
channels/   render a 256x64 frame            flights, radar, silhouette, mbta, testpattern
scheduler   picks a channel (priority + rotation + hold), wipes between them, quiet hours
sinks/      show the frame: SimulatorSink (Mac/PNG) or ColorlightSink (raw Ethernet)
data/       shared ADS-B feed, MBTA client, airline / aircraft-type / airport lookups
sprites     procedural side-profile aircraft sprites, ~130 ICAO types
settings    what the phone UI can change; persisted to ~/.panelwall/settings.json
web         the control server (standard library http.server, no build step)
```

## Channels

| name | shows | priority |
|---|---|---|
| `flights` | FlightWall-style list of up to 5 aircraft overhead | 10 with aircraft, else 1 |
| `radar` | 64×64 radar scope (rings, sweep, altitude-colored blips) + list of 4 | 10 with aircraft, else 1 |
| `silhouette` | the closest aircraft as a hero card: sprite in airline colors, ORIGIN → DEST with progress dot, alt/spd/phase | 20 when exactly one aircraft is in range; 25 for 8 s whenever a not-yet-shown aircraft becomes the closest (at most every 45 s); else 0 |
| `mbta` | Red Line strip with live trains and next arrivals at Harvard | 5 (idle content) |
| `testpattern` | panel numbers 1–8, RGB bars, origin marker | bring-up only (`test`) |

Scheduler rules: a channel forced from the phone wins; a strictly higher priority preempts
immediately unless that channel left the screen less than 8 s ago; equal priorities rotate
every 20 s; priority 0 hides a channel at once. Switches are a 300 ms bottom-up wipe.

## Develop on the Mac (no hardware)

```bash
python3 -m venv .venv && source .venv/bin/activate      # NOT the conda `tf` env
pip install -r requirements.txt                          # numpy, pillow, pygame, pytest
python -m panelwall demo-flights                         # fixture data, live pygame window
python -m panelwall demo-radar | demo-silhouette | demo-mbta
python -m panelwall run                                  # live data + control UI on :8080
python -m panelwall run --channels flights,mbta          # load only some channels
python -m panelwall sheet                                # all channels -> design/channels_sheet.png
python -m panelwall sprites                              # all sprites  -> design/sprites_sheet.png
python -m panelwall probe                                # raw ADS-B JSON
python -m pytest -q
```

Without pygame (or with `--no-window`) the simulator writes `sim.png` every 10 frames.
After changing a layout, run `python -m panelwall demo-<name> --no-window --seconds 1`
and look at `sim.png`; text collisions are only visible that way.

## Environment variables

All optional. The app runs with none of them set.

| variable | default | meaning |
|---|---|---|
| `PW_LAT`, `PW_LON` | Doylestown PA (edit `config.py` for Boston) | where the display is |
| `PW_RADIUS_NM` | `50` | how far around you to look (8 is right for an apartment near BOS) |
| `PW_ADSB_BASE` | `https://api.adsb.lol` | readsb-style aircraft API; `https://api.airplanes.live` has the same shape |
| `PW_POLL_SECONDS` | `10` | aircraft poll interval. adsb.lol sent 429s at 5 s; the client backs off automatically on 429 |
| `PW_ROUTES_BASE` | `https://api.adsbdb.com` | origin/destination lookups per callsign (3 per poll, cached 1 h). Set to `""` to disable |
| `PW_IFACE` | `eth0` | interface cabled to the Colorlight |
| `PW_SETTINGS` | `~/.panelwall/settings.json` | where phone-UI settings persist |
| `MBTA_API_KEY` | unset | **optional.** Free key from api-v3.mbta.com raises the rate limit from 20 to 1000 req/min; we use 8/min. Nothing is disabled without it. |
| `PW_MBTA_ROUTE` | `Red` | MBTA route id |
| `PW_MBTA_STOP` | `place-harsq` (Harvard) | home station, a parent-station id |
| `PW_MBTA_BRANCH` | `Braintree` | `Braintree` or `Ashmont`; the Red Line forks after JFK/UMass |
| `PW_MBTA_BASE` | `https://api-v3.mbta.com` | |

Values saved from the phone UI (location, radius, brightness, quiet hours, enabled
channels) override these at startup.

## Control it from your phone

`run` starts a control server on port 80 (falls back to 8080 when not root) bound to all
interfaces, and prints its URL, e.g. `http://192.168.1.161:8080`. On the Pi as root it is
just `http://panelwall.local`.

Open that URL in Safari on your phone (same Wi‑Fi), tap **Share → Add to Home Screen**. It
installs as a full-screen app with a panelwall icon. The page shows a live preview of the
display, lets you toggle channels, force one for 60 s, set brightness and quiet hours, and
move the location/radius, and lists each channel's last data fetch and last error.

API, for scripting:

```
GET  /api/state                          everything the UI shows
POST /api/channels   {"enabled": ["flights","mbta"]}
POST /api/show       {"channel": "radar", "seconds": 60}     ({"channel": null} releases)
POST /api/brightness {"level": 191}  and/or  {"quiet": {"start":"23:00","end":"07:00","level":64}}
POST /api/location   {"lat": 42.36, "lon": -71.01, "radius_nm": 8}
GET  /preview.png                        current frame, LED look, 3x
```

## Run on the Pi

```bash
git clone <this repo> ~/panelwall && cd ~/panelwall
sudo apt install -y python3-numpy python3-pil          # system packages; no venv needed
python3 -m panelwall probe                             # confirm the API works from the Pi

# Raw sockets need CAP_NET_RAW. Either run with sudo, or grant it once:
sudo setcap cap_net_raw+ep $(readlink -f $(which python3))

sudo python3 -m panelwall test --sink colorlight            # bring-up: panel numbers 1..8
sudo python3 -m panelwall run  --sink colorlight            # the real thing (+ control UI on :80)
```

## Bring-up order (when the hardware arrives)

1. Configure the Colorlight in LEDVision (Windows) for 8× indoor P5 64×32, 4 wide × 2 tall,
   using WiredWatts' indoor-P5 settings. Send a test pattern *from LEDVision* first.
   That proves panels + cabling + card config with none of this code involved.
2. Cable the Pi's eth0 straight to the card. `ip link show eth0` should say `state UP`.
3. `sudo python3 -m panelwall test --sink colorlight`. You should see panels numbered
   1–8 left-to-right, top-to-bottom, with a red/green/blue bar on each. Wrong order or
   mirrored panels → fix the layout in LEDVision, not here. Wrong colors → the card's
   color-order setting.
4. `sudo python3 -m panelwall run --sink colorlight`.

## Colorlight protocol (for reference)

Raw L2 Ethernet to `11:22:33:44:55:66`. Per frame: one `0x5500` packet per row
(`row, x_offset(2), count(2), 0x08, 0x88, BGR...`), then one `0x0107` display packet
(98 bytes; `[21]` = brightness, `[22]` = 0x05, `[24..26]` = RGB gains). See
`panelwall/sinks/colorlight.py` and `tests/test_colorlight.py`.

## Adding a channel

Subclass `channels.base.Channel`; implement `tick(dt)`, `priority()` (≤ 0 = nothing to
show), `render(frame)`, `close()`, and `status()` (for the phone UI). Draw text only via
`Frame.text / text_right / text_center` (cached; `frame.draw.text` costs ~1.4 ms a call).
Do network I/O in a background thread and only read a snapshot in `render()`. Add a fixture
under `fixtures/`, a `demo-<name>` entry in `__main__.fixture_channel`, and the name to
`DEMO_CHANNELS` so `sheet` includes it. Then render it and look at the PNG.
