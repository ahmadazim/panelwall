# panelwall

A 256×64 LED matrix (8× P5 64×32 panels, 4 wide × 2 tall) driven by a Raspberry Pi 4
through a Colorlight 5A‑75B receiver card. Shows what's overhead (from free ADS‑B data),
a radar scope, a hero card for the closest aircraft, and the MBTA Red Line. Controlled
from your phone.

```
channels/   render a 256x64 frame            flightwall, flights, radar, silhouette, mbta, greenb/c/d, green, sports, forecast, prayers, meadow, testpattern
scheduler   picks a channel (priority + rotation + hold), wipes between them, quiet hours
sinks/      show the frame: SimulatorSink (Mac/PNG) or ColorlightSink (raw Ethernet)
data/       shared ADS-B feed, MBTA / ESPN / Open-Meteo clients, airline / aircraft-type / airport lookups
glyphs      weather glyphs (sun cloud partly rain snow storm fog) + team badge, shared with design/mockups2.py
sprites     procedural side-profile aircraft sprites, ~130 ICAO types
settings    what the phone UI can change; persisted to ~/.panelwall/settings.json
web         the control server (standard library http.server, no build step)
```

## Channels

| name | shows | priority |
|---|---|---|
| `flightwall` | **the FlightWall Widescreen replica** (default): one aircraft at a time, logo + airline / route / type, airport names, Alt/Spd/Trk/Vr; cycles the nearest 5 every 5 s; "..." or clocks when the sky is empty | 10 with aircraft, else 2 |
| `flights` | list of up to 5 aircraft overhead (the earlier list view) | 10 with aircraft, else 1 |
| `radar` | 64×64 radar scope (rings, sweep, altitude-colored blips) + list of 4 | 10 with aircraft, else 1 |
| `silhouette` | the closest aircraft as a hero card: sprite in airline colors, ORIGIN → DEST with progress dot, alt/spd/phase | 20 when exactly one aircraft is in range; 25 for 8 s whenever a not-yet-shown aircraft becomes the closest (at most every 45 s); else 0 |
| `mbta` | Red Line strip with live trains and next arrivals at Harvard | 5 (idle content) |
| `greenb` | Green Line B strip, home Washington Street, next trains both ways, plus the 65 bus at the stops outside the station | 5 |
| `greenc`, `greend` | Green Line C and D strips (home Kenmore by default; `PW_GREEN_HOME_C` / `PW_GREEN_HOME_D` to change) | 5 |
| `green` | all three Green branches on one screen (termini labelled, trains moving, home in amber) with Washington Street's next trains and the 65 bus | 5 |
| `sports` | "BOSTON TONIGHT": featured game card (live > next > last final) + one row per other tracked team, from ESPN's public scoreboard JSON (unofficial, keyless) | 25 for 15 s after a tracked team scores, 12 live, 4 game today, else 0 |
| `prayers` | today's athan and iqama times from your fiveprayers.org display page, next-prayer countdown, sunrise and Jumu'ah | 20 from 10 min before to 3 min after each athan / iqama, else 4 |
| `meadow` | screensaver: an orange tabby and Kuromi wander a looping parallax meadow. The sky follows the real time and weather from the shared forecast feed: sun on an east-left to west-right arc, dawn/dusk glow on the sun's side, moon and stars at night, clouds, rain, snow, lightning, fog | 2 (idle) |
| `forecast` | Open-Meteo (keyless): WEEK view (7 days, glyphs, hi/lo, precip %) and HOURLY view (next 12 h temperature line) alternating every 20 s | 3, or 8 for 60 s when the current weather turns to precipitation |
| `testpattern` | panel numbers 1–8, RGB bars, origin marker | bring-up only (`test`) |

**What shows when.** By default the wall shows **one panel you pick** on the phone (manual
mode) and stays there; out of the box that is `flightwall`. Switch to **Auto cycle** and it round-robins over the panels you tick,
staying `dwell` seconds on each (default 20) and skipping panels with nothing to show. With
"Alerts interrupt" on, a panel spiking to priority 20+ (a Boston score, a new closest aircraft)
cuts in for as long as the spike lasts, never more often than every 8 s. Switches are a
300 ms bottom-up wipe. The priorities in the table only matter in auto mode.

## Develop on the Mac (no hardware)

```bash
python3 -m venv .venv && source .venv/bin/activate      # NOT the conda `tf` env
pip install -r requirements.txt                          # numpy, pillow, pygame, pytest
python -m panelwall demo-flightwall --case a|b|c|d       # the replica: routes / private / 7 flights / empty sky
python -m panelwall demo-flights                         # fixture data, live pygame window
python -m panelwall demo-radar | demo-silhouette | demo-mbta | demo-sports
python -m panelwall demo-forecast --view week|hourly     # omit --view to alternate
python -m panelwall demo-meadow --sky rain --hour 19      # force a sky / local hour for review
python -m panelwall probe-sports | probe-forecast        # raw JSON from ESPN / Open-Meteo
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

### FlightWall replica settings

`FlightWallConfig` in `config.py`, all overridable by environment variable:

| variable | default | meaning |
|---|---|---|
| `PW_FW_TITLE` | `airline` | row 1: `airline` ("Southwest Airlines") or `flight` ("WN 1187") |
| `PW_FW_CYCLE` | `5` | seconds per aircraft (the app offers 5 / 3 / 2) |
| `PW_FW_UNITS` | `imperial` | `imperial` (2,700ft / 10.5kft, kts, +640ft/m) or `metric` (824m / 2.0km, kph, +64kph as on the product photo) |
| `PW_FW_IDLE` | `dots` | empty sky: `dots` ("...") or `clock` (up to three `(label, IANA tz)` clocks from `clocks`, 24 h with seconds) |
| `PW_HOME` | `BOS` | home airport |

Font: `fonts.FW` is the X11 misc-fixed **6x10** terminal font (public domain, the copy shipped
in hzeller/rpi-rgb-led-matrix), converted to a Pillow bitmap font by `tools/build_fw_font.py`
with the colon and period patched to single-pixel dots. Compared side by side with the product
photos it matches the letterforms (pointed A, hooked t, 7 px caps on a 6 px advance). Airport
names come from [OurAirports](https://ourairports.com) (public domain), trimmed into
`assets/data/airports.csv`. The 28x28 airline logos in `assets/logos/` are hand-drawn pixel-art
approximations of the real marks for personal, non-commercial use on this one display, generated
by `tools/build_logos.py`; `python -m panelwall logos` renders them at 6x to
`design/logos_sheet.png` for review.

## Environment variables

All optional. The app runs with none of them set.

| variable | default | meaning |
|---|---|---|
| `PW_LAT`, `PW_LON` | Doylestown PA (edit `config.py` for Boston) | where the display is |
| `PW_RADIUS_NM` | `50` | how far around you to look (8 is right for an apartment near BOS) |
| `PW_ADSB_BASE` | `https://api.adsb.lol` | readsb-style aircraft API; `https://api.airplanes.live` has the same shape |
| `PW_POLL_SECONDS` | `15` | aircraft poll interval. adsb.lol sent 429s at 5 s; the client backs off automatically on 429 |
| `PW_ROUTES_BASE` | `https://api.adsbdb.com` | origin/destination lookups per callsign (2 per poll, cached 1 h). Set to `""` to disable |
| `PW_MBTA_POLL` | `30` | MBTA poll interval (2 requests per poll) |
| `PW_IFACE` | `eth0` | interface cabled to the Colorlight |
| `PW_SETTINGS` | `~/.panelwall/settings.json` | where phone-UI settings persist |
| `MBTA_API_KEY` | unset | **optional.** Free key from api-v3.mbta.com raises the rate limit from 20 to 1000 req/min; we use 8/min. Nothing is disabled without it. |
| `PW_MBTA_ROUTE` | `Red` | MBTA route id |
| `PW_MBTA_STOP` | `place-harsq` (Harvard) | home station, a parent-station id |
| `PW_MBTA_BRANCH` | `Braintree` | `Braintree` or `Ashmont`; the Red Line forks after JFK/UMass |
| `PW_MBTA_BASE` | `https://api-v3.mbta.com` | |
| `PW_GREEN_HOME_B` | `place-wascm` (Washington Street) | home station for the B panel |
| `PW_GREEN_HOME_C`, `PW_GREEN_HOME_D` | `place-kencl` (Kenmore) | home station for the C and D panels |
| `PW_TEAMS` | `mlb:BOS:SOX,nfl:NE:PATS,nba:BOS:CELTS,nhl:BOS:B'S` | tracked teams as `league:ESPN-abbreviation:label`; labels <= 5 chars fit next to any status |
| `PW_CITY` | `BOSTON` | header of the sports channel |
| `PW_TZ` | `America/New_York` | timezone for Open-Meteo timestamps and prayer-time calculation |
| `PW_PRAYERS_URL` | your fiveprayers.org display page | the page has no API: it is fetched every 6 h for its parameters and fixed iqama times, and the athan times are computed locally with the same algorithm its JavaScript uses (verified against it) |

Both the sports and forecast sources are keyless. ESPN's scoreboard JSON is **unofficial**:
undocumented, stable for years, but it could change or disappear without notice. Parsing
is per-event defensive, so a shape change degrades to "NO GAMES" rather than a crash.

Values saved from the phone UI (location, radius, brightness, quiet hours, enabled
channels) override these at startup.

**Polling is demand-driven.** A feed only polls while a panel that uses it can be shown:
the pinned panel in manual mode, the ticked panels in auto mode. Everything else is paused
(the phone UI says "paused, not on screen") and resumes within 2 s of being selected.
Defaults: aircraft 15 s, MBTA 30 s, ESPN 60 s during a game / 10 min otherwise, forecast
30 min. Every client backs off on HTTP 429 (Retry-After if sent, else 15 s doubling to
5 min). Never run two `run` instances at once; they share your IP's quota.

## Control it from your phone

`run` starts a control server on port 80 (falls back to 8080 when not root) bound to all
interfaces, and prints its URL, e.g. `http://192.168.1.161:8080`. On the Pi as root it is
just `http://panelwall.local`.

Open that URL in Safari on your phone (same Wi‑Fi), tap **Share → Add to Home Screen**. It
installs as a full-screen app with a panelwall icon. The page shows a live preview of the
display, lets you pick the one panel to show or set up an auto cycle (which panels, how long
on each, whether alerts may interrupt), set brightness and quiet hours, move the
location/radius, and lists each channel's last data fetch and last error.

API, for scripting:

```
GET  /api/state                          everything the UI shows
POST /api/channel    {"channel": "radar"}                        pin one panel (manual mode)
POST /api/mode       {"mode": "manual" | "auto"}
POST /api/cycle      {"channels": ["flights","mbta"], "dwell_seconds": 20, "alerts": true}   (any subset of keys)
POST /api/show       {"channel": "radar", "seconds": 60}     temporary override; {"channel": null} releases
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
