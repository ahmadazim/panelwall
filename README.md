# panelwall

A 256×64 LED matrix (8× P5 64×32 panels, 4 wide × 2 tall) driven by a Raspberry Pi 4
through a Colorlight 5A‑75B receiver card. First channel: a FlightWall‑style list of
aircraft overhead, from free ADS‑B data.

```
channels/   render a 256x64 frame            (flights, testpattern, ...)
scheduler   picks the highest-priority channel, runs the loop at N fps
sinks/      show the frame: SimulatorSink (Mac/PNG) or ColorlightSink (raw Ethernet)
data/       ADS-B client + airline / aircraft-type lookups
```

## Develop on the Mac (no hardware)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt          # numpy, pillow, pygame (pygame optional but nice)
python -m panelwall demo                 # fixture data, live window
python -m panelwall run                  # live ADS-B data around CONFIG.location
python -m panelwall test                 # panel-numbering test pattern
python -m panelwall probe                # dump raw API JSON to verify field shapes
python -m pytest -q                      # byte-level protocol tests + data parsing
```

Without pygame (or with `--no-window`) the simulator writes `sim.png` every 10 frames —
open it in VS Code / Preview and it refreshes as the file changes.

Set your apartment's coordinates in `panelwall/config.py` (`LocationConfig`) or via
`PW_LAT` / `PW_LON` / `PW_RADIUS_NM` environment variables.

## Run on the Pi

```bash
git clone <this repo> ~/panelwall && cd ~/panelwall
sudo apt install -y python3-numpy python3-pil          # system packages; no venv needed
python3 -m panelwall probe                             # confirm the API works from the Pi

# Raw sockets need CAP_NET_RAW. Either run with sudo, or grant it once:
sudo setcap cap_net_raw+ep $(readlink -f $(which python3))

python3 -m panelwall test --sink colorlight            # bring-up: panel numbers 1..8
python3 -m panelwall run  --sink colorlight            # the real thing
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

Subclass `channels.base.Channel`, implement `render(frame)` (and `priority()` if it should
only show sometimes), add it to the list in `__main__.cmd_run`. Do network I/O in a
background thread and only read a snapshot in `render()`.
