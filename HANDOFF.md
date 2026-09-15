# panelwall — Project Handoff

Read this whole file before doing anything. It is the complete state of the project as of
**Tuesday, 15 Sep 2026**. Nothing here is speculative unless marked *UNVERIFIED*.

---

## 0. Who you are working with, and how to work with him

**Ahmad** (ahmadazim). Strong software engineer and systems thinker; **has never done hardware
before this project.** He does not know electronics vocabulary. When a hardware concept comes up,
explain it the way you would to a senior backend engineer: by analogy to software/systems
concepts, without jargon, without condescension.

Rules he has stated explicitly, and that you must follow:

1. **Check your answers before returning them. Do not guess.** He was burned earlier by
   confident-but-wrong inferences (see §9). If you are inferring rather than observing, say so.
   If you can verify with a command or a file, do that first.
2. He knows his own equipment. Don't re-explain things already established here.
3. Be concise. He reads fast and dislikes padding.
4. When something is a design *choice* rather than a fact, give him a recommendation with the
   reasoning, not a menu.

He works from a **MacBook Pro** (zsh; has miniconda with a `tf` env that is NOT the project venv;
`~/.ssh/config` exists). The Raspberry Pi is on his desk, reachable over SSH (§3).

---

## 1. What we are building

A **wall-mounted LED matrix display** for his apartment living room in **Boston** (he lives
near Logan / BOS). Initial goal: **replicate TheFlightWall "Widescreen"**
(https://theflightwall.com/products/flightwall-widescreen-flight-tracking-led-display) —
a 1280 × 320 mm display that lists aircraft currently overhead: airline, flight number, route,
aircraft type, altitude, speed, heading, vertical rate; up to 5 flights at once; refreshes
every ~30 s. He wants to *learn to build hardware* by cloning it; later he may diverge
(ideas explored: Logan departures board, aircraft silhouette sprites, radar scope, Spotify
now-playing, MBTA Red Line, tide/weather ambient). **For now: FlightWall replica only.**
Not for sale; personal project.

He is currently in **Doylestown, PA (zip 18902)** where the hardware is being delivered and
where he will do the build. He **travels on Mon 21 Sep**; the build window is Thu 17 – Sun 20.

---

## 2. Hardware — complete inventory

### 2a. Display geometry (the number that everything else derives from)

8 × indoor P5 panels, each **64 × 32 px, 320 × 160 mm**, arranged **4 wide × 2 tall**
→ display is **256 × 64 px, 1280 × 320 mm** — identical dimensions to the FlightWall Widescreen.
5 mm pixel pitch. The whole software stack assumes W=256, H=64.

### 2b. Already owned

- **CanaKit Raspberry Pi 4 Starter PRO Kit (4 GB RAM)**: Pi 4B 4GB, USB-C 3.5 A PSU with
  inline PiSwitch, 32 GB Samsung EVO+ microSD, USB microSD reader, micro-HDMI→HDMI cable,
  case with fan, heatsinks. **Only the Pi and its PSU/SD are used long-term**; the case
  comes off when the Pi is mounted on the panel backs.
- MacBook Pro, a monitor/TV + USB keyboard (used once for Pi debugging).

### 2c. Ordered from WiredWatts (wiredwatts.com, Alpharetta GA) — arrives **Thu 17 Sep**

| Part | SKU | Qty | Purpose |
|---|---|---|---|
| Full Color 64x32 P5 Panel Indoor Rated 2 Pack | pnp5i2pk | 4 | the 8 panels. Each pack includes 2 short HUB75 ribbon jumpers + 1 dual-head power cord (powers 2 panels) |
| Meanwell LRS-350-5 (5 V, 300 W / 60 A) | ps5v350wm | 1 | panel power. Open-frame PSU: exposed mains screw terminals L/N/⏚ — must be covered before wall-mounting |
| Panel Power Distribution board | hanpaneldistro | 1 | 1 input (screw terminals) → 8 fused outputs (4 × 7 A fuses), 30 A total, 144 mm mounting holes |
| AC Power Cord 3 Core 18 AWG | ac-power-cord | 1 | bare-wire cord → Meanwell L/N/⏚ |
| 10 AWG Black THHN wire | 10awgblk | 3 ft | Meanwell −V → distro board − |
| 10 AWG Red THHN wire | 10awgred | 3 ft | Meanwell +V → distro board + |
| Center Mounting Strip, 2 panels tall | pmsc2 | 3 | joins the 3 interior column seams (4 columns − 1) |
| Side Mounting Strips, 2 tall (L+R pair) | pmss2 | 1 | outer edges |
| Colorlight and Computer Mount | pmcolorlight | 1 | holds Colorlight card + bare Pi on panel backs; sized for 5A-75B (143 × 93 mm) |
| Panel Power Supply Back Mount | pmpsuback | 1 | holds the Meanwell on panel backs |
| 24 Inch Panel Wire (HUB75 ribbon) | panelwire24 | 2 | Colorlight port → first panel of each row |
| 15 Inch Panel Wire | panelwire15 | 2 | spares |
| Dual Head Panel Power Wire | panelpower | 1 | **powers the Colorlight card** from a spare distro output (same 4-pin connector as the panels) |

Subtotal $236.98 + $19.30 shipping.

### 2d. Ordered from Wally's Lights (wallyslights.com) — ETA **Fri 18 – Sat 19 Sep**

- **Colorlight 5A-75B, Version 8** receiver card, $24.99. 8 × HUB75 outputs, 1 × Gigabit
  Ethernet input, 5 V power input (4-pin, same as panels), FPGA-based. WiredWatts was out of
  stock; this is the identical commodity card. Whether a power lead is included is unknown
  (hence the $1 Dual Head Panel Power Wire above).

### 2e. Still to buy locally (hardware store / Micro Center)

Ethernet patch cable (1–3 ft), wire stripper/cutter, small flathead + Phillips screwdrivers,
**multimeter** (strongly recommended: verify 5.0 V and polarity at the distro board before
plugging in panels), power strip for behind the display. Wall-hanging hardware TBD after
assembly (frame ≈ 50 in wide, ~15 lb).

### 2f. Architecture decision: Colorlight, not a Pi HAT — do not reopen this

Two ways to drive HUB75 panels from a Pi:
- **HAT/bonnet** (Adafruit, WiredWatts "Panel Pi Hat"): level shifter on the Pi's GPIO; the Pi
  CPU bit-bangs the panel scanout via `rpi-rgb-led-matrix`. Eats a core, flicker-sensitive to
  OS jitter, single-chain bonnets give poor refresh at 8 panels.
- **Colorlight 5A-75B** (chosen): standalone FPGA card. Pi sends **whole frames as raw
  layer-2 Ethernet packets**; the card holds the frame and refreshes the panels itself. Pi CPU
  is free; refresh is flawless. Cost: a one-time card configuration in **LEDVision (Windows-only)**
  and a small custom frame sender (already written, §5).

Ahmad chose Colorlight deliberately after a full discussion. HUB75 is the *connector/protocol on
the panels* — both approaches use it; it is not a third option.

### 2g. Physical topology (how it will be wired)

```
wall outlet ──AC cord──▶ Meanwell LRS-350-5 ──10AWG red/black──▶ Panel Power Distribution board
                                                                   ├─ dual-head cord ─▶ panels 1,2
                                                                   ├─ dual-head cord ─▶ panels 3,4
                                                                   ├─ dual-head cord ─▶ panels 5,6
                                                                   ├─ dual-head cord ─▶ panels 7,8
                                                                   └─ dual-head wire ─▶ Colorlight 5V in

wall outlet ──CanaKit USB-C PSU──▶ Raspberry Pi 4 (Wi-Fi = internet)
Raspberry Pi eth0 ──Ethernet cable (direct, NO switch)──▶ Colorlight 5A-75B RJ45
Colorlight port 1 ──24" ribbon──▶ top row panel 1 IN ──short jumper──▶ panel 2 ──▶ 3 ──▶ 4
Colorlight port 2 ──24" ribbon──▶ bottom row panel 5 IN ──▶ 6 ──▶ 7 ──▶ 8
```

Power plane (5 V, thick wires) and data plane (HUB75 ribbons / Ethernet) are completely
separate. The Pi does **not** power the panels or the card.

Power budget: panels ≈ 2.4 A each at full white on a Colorlight → ~19 A worst case; PSU is 60 A.

---

## 3. Raspberry Pi — current state (DONE, verified)

- OS: **Raspberry Pi OS (full desktop image, 64-bit, Trixie-era with cloud-init customisation)**
  flashed with Raspberry Pi Imager. Desktop was later disabled via `raspi-config` → boot to
  console, no auto-login. (Lite was intended; full was flashed; it doesn't matter.)
- hostname **`panelwall`**, user **`ahmadazim`**, password auth.
- Wi-Fi: connected to **`Fios-S7jgK`** (Verizon Fios router). Imager's preconfigured profile had
  a typo'd SSID (`Fios_S7jgk`) and never connected; Ahmad connected manually from the desktop.
  The typo'd profile `netplan-wlan0-Fios_S7jgk` may or may not have been deleted.
- SSH: **active**. From the Mac: `ssh panelwall` works via this `~/.ssh/config` block:
  ```
  Host panelwall
      HostName panelwall.local
      User ahmadazim
      PreferredAuthentications password
      PubkeyAuthentication no
  ```
  If `panelwall.local` stops resolving (Fios mDNS is flaky), use the IP from `hostname -I` on the
  Pi and put `HostName <ip>` in that block.
- Packages: `python3-numpy`, `python3-pil` present (`import numpy, PIL` → ok). `git`,
  `tcpdump`, `ethtool`, `python3-venv` were in the install list; assume present.
- **eth0 NetworkManager profile `colorlight`** created:
  `ipv4.method manual, 192.168.99.1/24, ipv4.never-default yes, ipv6 disabled, autoconnect yes`.
  Purpose: bring eth0 UP at boot with no DHCP wait; the Colorlight speaks no IP at all, the
  address is irrelevant. eth0 currently shows `NO-CARRIER ... state DOWN` (nothing plugged in) —
  expected.
- A default `netplan-eth0` DHCP profile also exists. Ahmad was told to run
  `sudo nmcli con mod netplan-eth0 connection.autoconnect no` — **verify this was done**
  (`nmcli con show netplan-eth0 | grep autoconnect`), otherwise it may grab eth0 when the cable
  is plugged in.
- Raw sockets need `CAP_NET_RAW`: run with `sudo`, or once:
  `sudo setcap cap_net_raw+ep $(readlink -f $(which python3))`.
- Ping to google.com works (IPv6 answered). No monitor/keyboard attached anymore.

---

## 4. Software — the `panelwall` package (this repo)

Python 3.11+, deps: numpy, pillow (+ pygame on the Mac for the live window; pytest).
Tested on the Mac via `.venv`; **Ahmad sometimes runs from his conda `tf` env by mistake** —
if a module is "missing", that's why.

```
panelwall/
  __main__.py          CLI: run | demo | test | probe
  config.py            DisplayConfig(256x64, fps 20, brightness 0xBF)
                       LocationConfig(lat, lon, radius_nm) — env PW_LAT / PW_LON / PW_RADIUS_NM
                       ColorlightConfig(iface='eth0')  DataConfig(adsb_base, poll 5 s, route cache 1 h)
  framebuffer.py       Frame = PIL RGB 256x64 + drawing helpers; _TextCache (see perf note)
  fonts.py             SMALL = Silkscreen 8px (5px caps, ~6px advance, ~42 chars/line)
                       MEDIUM = Press Start 2P 8px (8x8)   LARGE = Press Start 2P 16px
  scheduler.py         each frame: tick all channels, pick max priority(), render, sink.show()
  channels/
    base.py            Channel: tick(dt), priority() (<=0 = don't show), render(frame), close()
    flights.py         FlightsChannel — the FlightWall replica (layout below)
    testpattern.py     panel numbers 1–8 + RGB bars + origin marker + moving dot; for bring-up
  sinks/
    base.py            Sink.show(np.ndarray HxWx3 uint8 RGB)
    simulator.py       pygame window (Mac) or PNG every 10 frames; prints its mode at startup
    colorlight.py      ColorlightSink + pure packet builders (protocol in §5)
  data/
    adsb.py            AdsbClient (adsb.lol), Aircraft dataclass, parse_aircraft, parse_route
    airlines.py        ICAO operator → (IATA, name): JBU→(B6, JETBLUE). ~60 carriers
    aircraft_types.py  ICAO type → ≤10-char name: A21N→A321NEO. ~170 types incl. GA
assets/fonts/          PressStart2P.ttf, Silkscreen.ttf (OFL)
fixtures/bos_point.json  hand-built readsb-shaped Boston traffic + `_routes` sidecar (test only)
tests/                 test_colorlight.py (byte-level), test_data.py — 10 tests, all pass
```

Run `python -m pytest -q` (or the ad-hoc runner if pytest is missing).

### FlightsChannel layout (256 × 64)

```
y=1   OVERHEAD  n AIRCRAFT                                        HH:MM   (colon blinks 1 Hz)
y=10  FLIGHT    ROUTE    TYPE(≤10)      ALT      SPD   hdg-arrow  vrate
y=21  ...                                                       (rows 11 px, max 5)
x:    2         50       96        →200(right) →234(right) 240      250
```
Row 0 (closest aircraft) is highlighted: flight in AMBER, rest WHITE; other rows GREY.
Ground aircraft (`alt_baro == "ground"`) are filtered out. Sorted by distance.
Empty state: "NO AIRCRAFT OVERHEAD / WITHIN n NM" or red "NO DATA - CHECK NETWORK".
The header separator line was removed (looked like a glitch on the dot grid) — don't re-add.

### Performance note (important on the Pi)

Pillow re-rasterizes text through FreeType on every `draw.text` (~1.4 ms each). The first
version took 30 ms/frame; **`_TextCache` in framebuffer.py** caches rendered (string, font,
color) tiles → **0.76 ms/frame** warm, including packetization. Always draw text through
`Frame.text/text_right/text_center`, never `frame.draw.text` directly.

---

## 5. Colorlight 5A-75B protocol (implemented in `sinks/colorlight.py`, unit-tested)

Source of truth: two independent reverse-engineerings that agree — Harald Kubota's write-up
(hkubota.wordpress.com, Jan 2022) and the `colorlight.rs` crate (github.com/asamonik/colorlight.rs).
**Not yet exercised against real hardware** — that's step 3 of bring-up (§7).

- Raw layer-2 Ethernet, no IP. dst MAC `11:22:33:44:55:66`, src `22:22:33:44:55:66`.
- **Row packet**, ethertype `0x5500` (rows 0–255) / `0x5501` (256–511):
  payload `[row&0xFF][x_off hi][x_off lo][count hi][count lo][0x08][0x88]` + pixels as **B,G,R**.
  Max 497 px/packet (MTU). Our rows are 256 px → one packet per row, 775-byte payload.
- **Display packet**, ethertype `0x0107`, 98-byte payload, all zero except
  `[21]=brightness 0–255, [22]=0x05, [24..26]=R,G,B gain (0xFF)`. Sent **after** all rows;
  tells the card to show the frame.
- Optional brightness packet `0x0A00|level`, 63-byte payload `[level, level, 0xFF, 0...]`. Not used.
- Per frame: 64 row packets + 1 display packet = 65 packets, ~50 KB. At 20 fps ≈ 1 MB/s.
- Card detection (`0x0700` request / `0x0805` reply) exists but is not implemented; not needed.
- `frame_to_packets(frame, brightness)` is a pure function → easy to `tcpdump` and diff.

The card's **logical canvas (256×64) and the mapping to 8 physical panels across 2 ports is
configured in LEDVision and stored on the card**, not in our code. Our code just addresses
rows 0–63 × 256 px.

---

## 6. Data source — adsb.lol (free, no key). Verified vs. unverified

**VERIFIED (live, from Doylestown, 14 Sep):** `GET https://api.adsb.lol/v2/point/{lat}/{lon}/{radius_nm}`
returns `{"ac":[...]}` with readsb fields exactly as parsed: `hex, flight, r, t, alt_baro
(int or "ground"), gs, track, baro_rate, lat, lon, seen, dst, dir, category, ...`.
`probe` output parsed correctly (a C172 at 5.7 nm). Poll every 5 s.

**UNVERIFIED — open issue:** `POST {base}/api/0/routeset` with
`{"planes":[{"callsign":"JBU1287","lat":..,"lng":..}]}` is expected to return a list of
`{callsign, airport_codes:"KBOS-KLAX", _airport_codes_iata:"BOS-LAX", plausible, ...}`.
The one live attempt (a private N-number) returned HTTP 200 with an **empty body** →
JSONDecodeError. Code now treats an empty body as `[]`. **Next step:** run
`python -m panelwall probe --routes AAL2570 JBU1287` (use callsigns currently airborne) and
read the raw status/body it prints; adjust `parse_route()` in `data/adsb.py` if the shape
differs. Until then the ROUTE column shows `---`. Nothing else depends on it.

Alternative point API with the same shape if adsb.lol misbehaves: `https://api.airplanes.live/v2/point/...`
(set `PW_ADSB_BASE`). It has no routeset.

Location: Ahmad set `PW_LAT/PW_LON` (or edited config) to Doylestown `40.389, -75.127` for
testing; use `PW_RADIUS_NM=30` there (reaches PHL traffic). Final install: his Boston
coordinates, radius ~8 nm.

Both `/v2/point` and `/api/0/routeset` are **unreachable from Anthropic's sandbox** (proxy 403);
test on the Mac or the Pi, never assume from the sandbox.

---

## 7. Bring-up procedure (when hardware arrives) — follow this order

**Day 1 (Thu, panels arrive; card may not have):**
1. Panels face-down, 4×2, all HUB75 arrows the same direction. Bolt center strips (3) across the
   interior seams, side strips on the outer edges. Screws included.
2. Bolt on PSU mount, Colorlight/computer mount, distro board (2 × M3 included).
3. AC cord → Meanwell L / N / ⏚. 10 AWG red +V→distro +, black −V→distro −. **Do this
   unplugged.** Plug in, **multimeter: expect 5.0 V (Meanwell has a trim pot), correct polarity
   at the distro terminals.** Unplug.
4. Dual-head power cords → panels (4 cords, 8 panels) and → Colorlight power in.
5. Data: port 1 → 24" ribbon → top-row first panel IN; jumpers along the row. Port 2 → bottom row.

**Day 2 (card + Windows machine):**
6. **LEDVision** (Colorlight's Windows config tool, v8.x): Windows PC with a *physical* Ethernet
   port cabled directly to the card (no switch; a VM needs a USB-Ethernet adapter passed
   through). Load WiredWatts' indoor-P5 settings (https://www.wiredwatts.com/colorlight-setup-for-indoor-p5-panels),
   set 8 panels 64×32, 4 wide × 2 tall, ports 1–2 as cabled, send to the card, **save to card
   (persistent)**. Show LEDVision's own test pattern. This proves panels + cabling + card
   config with none of our code involved. Windows is never needed again after this.
7. Cable Pi eth0 → card. `ip link show eth0` should say `state UP`. Verify `netplan-eth0` is not
   grabbing the interface (`nmcli dev status`).
8. `sudo python3 -m panelwall test --sink colorlight` → panels numbered **1–8 left→right,
   top→bottom**, RGB bars red/green/blue in that order, white origin pixel top-left, moving dot
   along the bottom. Wrong order/mirroring → fix in LEDVision. Wrong colors → LEDVision color
   order. Nothing at all → `tcpdump -i eth0 -e ether proto 0x0107` to confirm packets leave.
9. `sudo python3 -m panelwall run --sink colorlight`.
10. Later: systemd unit to run at boot; brightness schedule; wall mounting.

Debug philosophy: the card gives **no error messages** — dark panels mean config, cabling, or
protocol. Step 6 isolates the first two; step 8 isolates the third.

---

## 8. Immediate next steps (in order)

1. Ahmad to run `probe --routes <airline callsigns>` on the Mac and paste the raw reply → fix
   `parse_route` if needed.
2. Verify `netplan-eth0` autoconnect is off on the Pi.
3. Get the code onto the Pi (`scp -r` or git); `python3 -m panelwall probe` there to confirm the
   Pi reaches adsb.lol; `python3 -m panelwall test --no-window --seconds 2` renders a PNG as a
   smoke test.
4. Prep Windows: download LEDVision 8.x, read the WiredWatts P5 guide, download the 5A-75B manual
   (linked from wallyslights.com/products/colorlight-5a-75b).
5. Buy tools (§2e).
6. Hardware bring-up per §7 from Thursday.
7. After it works: systemd service, brightness/night schedule, then design iteration
   (silhouette sprites, departures board, etc.). Six pixel-accurate mockups from the
   design brainstorm are in `design/led_layout_ideas.png`, generated by `design/led_mockups.py`.

---

## 9. Mistakes already made — don't repeat them

- Assumed a dark green ACT LED meant the Pi wasn't booting. On a Pi 4 the green LED goes quiet
  once the OS is idle. Ahmad plugged in a monitor and it had booted fine all along.
- Assumed the OS image deletes `recovery.bin` after first boot. This image doesn't.
- Assumed Imager writes `firstrun.sh`. Current images use cloud-init (`user-data`,
  `network-config`, `meta-data` on the boot partition).
- Initially read Wally's Lights' Colorlight page as "sold out" via a fetch tool; the live page
  showed "Add to cart". Verify stock in a real browser, not a text scrape.
- Made the simulator's PNG fallback silent, so `run` looked hung. Fixed; keep startup messages.
- Pillow text without caching → 30 ms/frame. Fixed with `_TextCache`.
- A 1-px separator line adjacent to glyph bottoms reads as a bug on an LED grid. Use spacing.
- Column collisions: 10-char type + 5-digit altitude. Column positions in `flights.py` are
  tuned; if you add text, re-render with `demo --no-window` and **look at the PNG**.

Terminology he had to have clarified (don't re-derive, just be consistent): HUB75 = the panel
connector/protocol (like HDMI on a monitor). Colorlight = standalone card that drives HUB75 from
Ethernet (like a set-top box). HAT = adapter that lets the Pi drive HUB75 itself (like a USB-C→HDMI
dongle). Fork/spade crimps = optional clean wire terminations for screw terminals. Ribbon
extensions = longer HUB75 cables for controller→first-panel hops.

---

## 10. Reference links

- FlightWall Widescreen: https://theflightwall.com/products/flightwall-widescreen-flight-tracking-led-display
- WiredWatts P5 2-pack: https://www.wiredwatts.com/products/pnp5i2pk
- WiredWatts Colorlight P5 setup guide: https://www.wiredwatts.com/colorlight-setup-for-indoor-p5-panels
- WiredWatts mounts: /pmcolorlight, /pmpsuback, /pmsc2, /pmss2, /hanpaneldistro, /panelpower
- Wally's Colorlight 5A-75B v8 (manual link on page): https://wallyslights.com/products/colorlight-5a-75b
- Protocol: https://hkubota.wordpress.com/2022/01/31/winter-project-colorlight-5a-75b-protocol/ ,
  https://github.com/asamonik/colorlight.rs , https://github.com/haraldkubota/colorlight
- adsb.lol API: https://api.adsb.lol/docs (interactive), https://github.com/adsblol/api
- Existing flight-tracker projects for ideas (HAT-based, not directly usable):
  https://github.com/ColinWaddell/FlightTracker , https://github.com/Weslex/rpi-led-flight-tracker
