from PIL import Image, ImageDraw, ImageFont
import math, os

W, H = 256, 64
FD = os.path.join(os.path.dirname(__file__), "fonts")
PS8 = ImageFont.truetype(os.path.join(FD, "PressStart2P.ttf"), 8)
PS16 = ImageFont.truetype(os.path.join(FD, "PressStart2P.ttf"), 16)
SK8 = ImageFont.truetype(os.path.join(FD, "Silkscreen.ttf"), 8)
SK16 = ImageFont.truetype(os.path.join(FD, "Silkscreen.ttf"), 16)

AMBER = (255, 176, 0)
WHITE = (235, 235, 235)
GREY = (90, 90, 90)
DIM = (45, 45, 45)
GREEN = (40, 220, 90)
RED = (240, 60, 60)
CYAN = (60, 200, 255)
BLUE = (40, 110, 255)
MAGENTA = (255, 70, 200)


def canvas():
    im = Image.new("RGB", (W, H), (0, 0, 0))
    return im, ImageDraw.Draw(im)


def text(d, xy, s, font=SK8, fill=WHITE):
    d.text(xy, s, font=font, fill=fill)


def tw(s, font=SK8):
    return int(font.getlength(s))


def led(im, scale=6, gap=1, bg=(12, 12, 12)):
    """Simulate P5 LED look: each pixel -> round dot in a dark grid."""
    out = Image.new("RGB", (W * scale, H * scale), bg)
    d = ImageDraw.Draw(out)
    px = im.load()
    r = (scale - gap) / 2
    for y in range(H):
        for x in range(W):
            c = px[x, y]
            if c == (0, 0, 0):
                c = (24, 24, 24)
            cx, cy = x * scale + scale / 2, y * scale + scale / 2
            d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=c)
    return out


# ---------------------------------------------------------------- A. Logan departures
def departures():
    im, d = canvas()
    d.rectangle([0, 0, W, 8], fill=(30, 30, 30))
    text(d, (2, 1), "BOS DEPARTURES", SK8, AMBER)
    text(d, (W - tw("14:32", SK8) - 2, 1), "14:32", SK8, AMBER)
    rows = [
        ("14:35", "B6 1287", "LOS ANGELES", "BOARDING", GREEN),
        ("14:40", "DL 2314", "ATLANTA", "ON TIME", WHITE),
        ("14:45", "AA 1124", "CHARLOTTE", "DELAYED", RED),
        ("14:50", "UA 458", "CHICAGO", "ON TIME", WHITE),
        ("14:55", "B6 1633", "FT LAUDERDALE", "GATE C12", WHITE),
        ("15:05", "EI 138", "DUBLIN", "ON TIME", WHITE),
    ]
    y = 10
    for t, fl, dest, st, col in rows:
        text(d, (2, y), t, SK8, AMBER)
        text(d, (34, y), fl, SK8, WHITE)
        text(d, (84, y), dest, SK8, WHITE)
        text(d, (W - tw(st, SK8) - 2, y), st, SK8, col)
        y += 9
    return im


# ---------------------------------------------------------------- B. Aircraft silhouette
def plane_sprite(d, ox, oy, body=(230, 230, 230), stripe=(0, 90, 200), engines=2, winglets=True):
    # side profile, nose left, ~96 x 30
    # fuselage
    d.rounded_rectangle([ox + 6, oy + 12, ox + 90, oy + 20], radius=4, fill=body)
    # nose
    d.polygon([(ox + 6, oy + 12), (ox, oy + 17), (ox + 6, oy + 20)], fill=body)
    # cockpit window
    d.line([(ox + 8, oy + 14), (ox + 11, oy + 14)], fill=(40, 60, 90))
    # tail fin
    d.polygon([(ox + 74, oy + 12), (ox + 84, oy + 1), (ox + 92, oy + 1), (ox + 90, oy + 12)], fill=stripe)
    # horizontal stabilizer
    d.polygon([(ox + 80, oy + 16), (ox + 96, oy + 13), (ox + 96, oy + 15), (ox + 88, oy + 18)], fill=body)
    # wing (swept, going toward viewer/down)
    d.polygon([(ox + 34, oy + 18), (ox + 52, oy + 18), (ox + 62, oy + 29), (ox + 56, oy + 29)], fill=(200, 200, 200))
    if winglets:
        d.line([(ox + 60, oy + 29), (ox + 62, oy + 25)], fill=stripe)
    # engines
    if engines >= 1:
        d.rounded_rectangle([ox + 40, oy + 21, ox + 54, oy + 26], radius=2, fill=(160, 160, 160))
        d.rectangle([ox + 40, oy + 22, ox + 41, oy + 25], fill=(60, 60, 60))
    # windows
    for x in range(ox + 16, ox + 72, 3):
        d.point((x, oy + 15), fill=(50, 70, 110))
    # cheatline stripe
    d.line([(ox + 12, oy + 19), (ox + 76, oy + 19)], fill=stripe)


def silhouette():
    im, d = canvas()
    plane_sprite(d, 4, 14, stripe=(0, 90, 200))
    # ground / motion lines
    for x in range(0, 100, 6):
        d.line([(x, 56), (x + 3, 56)], fill=DIM)
    text(d, (4, 2), "AIRBUS A321NEO", SK8, CYAN)
    # right info block
    x0 = 108
    text(d, (x0, 2), "JETBLUE 1287", PS8, WHITE)
    text(d, (x0, 14), "BOS", PS16, AMBER)
    d.line([(x0 + 52, 22), (x0 + 84, 22)], fill=GREY)
    d.polygon([(x0 + 84, 22), (x0 + 80, 19), (x0 + 80, 25)], fill=GREY)
    d.ellipse([x0 + 58, 19, x0 + 64, 25], fill=WHITE)  # plane position on route
    text(d, (x0 + 92, 14), "LAX", PS16, AMBER)
    text(d, (x0, 36), "ALT  4,250 FT", SK8, WHITE)
    text(d, (x0, 45), "SPD  242 KTS", SK8, WHITE)
    text(d, (x0, 54), "CLIMBING", SK8, GREEN)
    text(d, (x0 + 84, 36), "HDG 247", SK8, GREY)
    text(d, (x0 + 84, 45), "REG N2044J", SK8, GREY)
    text(d, (x0 + 84, 54), "RWY 27", SK8, GREY)
    return im


# ---------------------------------------------------------------- C. Radar scope
def radar():
    im, d = canvas()
    cx, cy, R = 32, 32, 30
    for r in (10, 20, 30):
        d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(0, 60, 30))
    d.line([(cx - R, cy), (cx + R, cy)], fill=(0, 45, 20))
    d.line([(cx, cy - R), (cx, cy + R)], fill=(0, 45, 20))
    # sweep
    for i in range(0, 40):
        a = math.radians(300 - i * 1.5)
        g = int(120 * (1 - i / 40))
        d.line([(cx, cy), (cx + R * math.cos(a), cy - R * math.sin(a))], fill=(0, g, int(g * 0.4)))
    d.point((cx, cy), fill=WHITE)  # you
    blips = [(cx + 14, cy - 9, 40), (cx - 8, cy + 16, 220), (cx + 22, cy + 12, 300), (cx - 20, cy - 6, 100)]
    cols = [AMBER, GREEN, GREEN, CYAN]
    for (bx, by, hd), c in zip(blips, cols):
        d.rectangle([bx - 1, by - 1, bx + 1, by + 1], fill=c)
        a = math.radians(90 - hd)
        d.line([(bx, by), (bx + 4 * math.cos(a), by - 4 * math.sin(a))], fill=c)
    text(d, (2, 1), "10NM", SK8, (0, 110, 50))
    # list
    x0 = 70
    text(d, (x0, 1), "OVERHEAD NOW", SK8, GREY)
    text(d, (W - tw("BOS", SK8) - 2, 1), "BOS", SK8, GREY)
    rows = [
        ("B6 1287", "BOS>LAX", "A321", "4250", AMBER),
        ("DL 2314", "BOS>ATL", "B739", "6100", GREEN),
        ("N741CG", "PVT", "PC12", "2800", GREEN),
        ("UAL 458", "BOS>ORD", "B738", "8900", CYAN),
    ]
    y = 12
    for fl, rt, ty, alt, c in rows:
        d.rectangle([x0, y + 1, x0 + 2, y + 5], fill=c)
        text(d, (x0 + 6, y), fl, SK8, WHITE)
        text(d, (x0 + 56, y), rt, SK8, WHITE)
        text(d, (x0 + 108, y), ty, SK8, GREY)
        text(d, (W - tw(alt, SK8) - 2, y), alt, SK8, GREY)
        y += 12
    return im


# ---------------------------------------------------------------- D. Now playing
def now_playing():
    im, d = canvas()
    # fake album art 56x56 (pixel gradient + shape)
    for y in range(56):
        for x in range(56):
            r = int(200 - x * 2.5)
            g = int(40 + y * 2.0)
            b = int(120 + (x + y) * 1.2) % 255
            d.point((4 + x, 4 + y), fill=(max(r, 0), min(g, 255), b))
    d.ellipse([18, 18, 46, 46], fill=(20, 20, 40))
    d.ellipse([28, 28, 36, 36], fill=(240, 220, 120))
    x0 = 68
    text(d, (x0, 4), "NOW PLAYING", SK8, GREEN)
    text(d, (x0, 14), "Midnight City", PS8, WHITE)
    text(d, (x0, 26), "M83", SK8, GREY)
    # progress
    d.rectangle([x0, 40, W - 6, 42], fill=DIM)
    d.rectangle([x0, 40, x0 + 92, 42], fill=WHITE)
    text(d, (x0, 46), "2:51", SK8, GREY)
    text(d, (W - 6 - tw("4:03", SK8), 46), "4:03", SK8, GREY)
    # EQ bars
    bars = [4, 9, 6, 12, 8, 5, 11, 7, 3, 9, 6, 10]
    bx = 150
    for h in bars:
        d.rectangle([bx, 60 - h, bx + 2, 60], fill=MAGENTA)
        bx += 4
    return im


# ---------------------------------------------------------------- E. MBTA next trains
def mbta():
    im, d = canvas()
    text(d, (2, 1), "RED LINE", PS8, RED)
    text(d, (W - tw("ALEWIFE  BRAINTREE", SK8) - 2, 1), "ALEWIFE  BRAINTREE", SK8, GREY)
    # line
    y = 22
    d.line([(8, y), (W - 8, y)], fill=RED, width=2)
    stations = ["ALW", "DAV", "PTR", "HVD", "CEN", "KEN", "CHS", "PRK", "DTX", "SST", "BRD", "AND", "JFK"]
    n = len(stations)
    for i, s in enumerate(stations):
        x = 8 + int(i * (W - 16) / (n - 1))
        d.ellipse([x - 2, y - 2, x + 2, y + 2], fill=WHITE if s != "HVD" else AMBER)
        text(d, (x - tw(s, SK8) // 2, y + 5 if i % 2 == 0 else y - 13), s, SK8, GREY if s != "HVD" else AMBER)
    # trains
    for x, dirn in [(60, 1), (150, -1), (210, 1)]:
        d.rectangle([x - 4, y - 5, x + 4, y - 3], fill=WHITE)
        d.polygon([(x + 4 * dirn, y - 5), (x + 7 * dirn, y - 4), (x + 4 * dirn, y - 3)], fill=WHITE)
    d.line([(0, 40), (W, 40)], fill=DIM)
    text(d, (2, 44), "HARVARD  >BRAINTREE", SK8, WHITE)
    text(d, (2, 54), "HARVARD  >ALEWIFE", SK8, WHITE)
    text(d, (W - tw("2  9  15 MIN", SK8) - 2, 44), "2  9  15 MIN", SK8, AMBER)
    text(d, (W - tw("4  11 MIN", SK8) - 2, 54), "4  11 MIN", SK8, AMBER)
    return im


# ---------------------------------------------------------------- F. Ambient: tide / sun / weather
def ambient():
    im, d = canvas()
    # tide curve across 24h
    base = 44
    for x in range(W):
        t = x / W * 24
        yv = base - 14 * math.sin((t - 3) / 12.42 * 2 * math.pi)
        d.point((x, int(yv)), fill=BLUE)
        if x % 32 == 0:
            d.line([(x, 60), (x, 62)], fill=GREY)
    now_x = int(14.5 / 24 * W)
    d.line([(now_x, 26), (now_x, 62)], fill=(60, 60, 90))
    d.ellipse([now_x - 2, base - 14 * math.sin((14.5 - 3) / 12.42 * 2 * math.pi) - 2,
               now_x + 2, base - 14 * math.sin((14.5 - 3) / 12.42 * 2 * math.pi) + 2], fill=WHITE)
    # sun arc
    for x in range(int(6.4 / 24 * W), int(19.1 / 24 * W)):
        t = (x / W * 24 - 6.4) / (19.1 - 6.4)
        d.point((x, int(34 - 9 * math.sin(t * math.pi))), fill=(90, 70, 20))
    d.ellipse([now_x - 3, 34 - 9 * math.sin((14.5 - 6.4) / 12.7 * math.pi) - 3,
               now_x + 3, 34 - 9 * math.sin((14.5 - 6.4) / 12.7 * math.pi) + 3], fill=AMBER)
    text(d, (2, 1), "BOSTON HARBOR", SK8, CYAN)
    text(d, (2, 10), "HIGH TIDE 17:42", SK8, WHITE)
    text(d, (W - tw("72F  CLEAR", PS8) - 2, 1), "72F  CLEAR", PS8, WHITE)
    text(d, (W - tw("SUNSET 19:06  WIND NE 8", SK8) - 2, 10), "SUNSET 19:06  WIND NE 8", SK8, GREY)
    text(d, (2, 54), "0", SK8, GREY)
    text(d, (W - tw("24", SK8) - 2, 54), "24", SK8, GREY)
    return im


MOCKS = [
    ("A", "Logan departures board", departures),
    ("B", "Aircraft silhouette + flight card", silhouette),
    ("C", "Radar scope + overhead list", radar),
    ("D", "Now playing (Spotify)", now_playing),
    ("E", "MBTA Red Line live", mbta),
    ("F", "Ambient: tide, sun, weather", ambient),
]

if __name__ == "__main__":
    out = os.path.join(os.path.dirname(__file__), "out")
    os.makedirs(out, exist_ok=True)
    rendered = []
    for key, name, fn in MOCKS:
        im = fn()
        im.save(os.path.join(out, f"{key}_{fn.__name__}_native.png"))
        big = led(im)
        big.save(os.path.join(out, f"{key}_{fn.__name__}.png"))
        rendered.append((key, name, big))
    # composite sheet
    pad, labelh = 24, 34
    bw, bh = rendered[0][2].size
    sheet = Image.new("RGB", (bw + 2 * pad, len(rendered) * (bh + labelh + pad) + pad), (20, 20, 22))
    sd = ImageDraw.Draw(sheet)
    lf = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 22) if os.path.exists(
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf") else ImageFont.load_default()
    y = pad
    for key, name, big in rendered:
        sd.text((pad, y), f"{key}.  {name}   (256 x 64 px, 1:1 pixel-accurate)", font=lf, fill=(220, 220, 220))
        y += labelh
        sheet.paste(big, (pad, y))
        y += bh + pad
    sheet.save(os.path.join(out, "layout_ideas.png"))
    print("done", sheet.size)
