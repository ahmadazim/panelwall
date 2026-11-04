"""Sports panels: a cycling sports wall plus one panel per sport, all from one shared SportsFeed.

Panels (each selectable on the phone): sports (the wall: every section, max 3 slides each),
boston, nfl, ucl, f1, tennis (that sport only, every slide). The feed polls only the sources
an on-screen panel needs.

Slides:
  live    - while a tracked Boston game is on: the original game card (LARGE scores, bases/outs,
            down & distance); it returns after every section on the wall
  boston  - the week: last results and next games per tracked team, one row each
  nfl/ucl - two games per screen (128 px cards): team crests (ESPN logos, downscaled for LEDs),
            big score or kickoff time, live minute / quarter, then
              soccer: goal scorers with minutes per side (P = penalty, OG = own goal), red cards
              NFL:    down & distance when live, then passing / rushing / receiving leaders
  f1      - podium (P2 | P1 | P3 steps with names and team colour) + next race countdown, and the
            winner's car in team livery lapping the bottom of the wall
  tennis  - two TV-style scorebugs: tournament + round, names in MEDIUM, set boxes, winner's ball

priority(): 25 for 15 s after a Boston score, 12 while a Boston game is live (boston/sports panels
only), 4 with anything to show, else 0.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta

from .. import fonts
from ..config import CONFIG
from ..data.espn import (DAYS, Game, SportsFeed, Team, format_status, live_detail, pick_game, week_status, _clock_text)
from ..framebuffer import Frame, W, AMBER, WHITE, GREY, DIM, GREEN, RED
from ..data.logos import LOGOS
from ..f1art import CAR_H, CAR_W, car_sprite, livery, tla
from ..framebuffer import H
from ..glyphs import team_mark, hex_color
from .base import Channel

X_SCORE = 92
X_CARD_R = 126
X_LIST = 132
X_LABEL = 143
ROW_AWAY, ROW_HOME = 11, 29
Y_STATUS, Y_DETAIL = 46, 55
ROW_Y0, ROW_H = 9, 9            # list pages: 6 rows at y = 9, 18, 27, 36, 45, 54
COL_W = 128                     # two-column pages
UCL_BLUE = (70, 120, 255)
F1_RED = (230, 40, 40)


def _badge(frame: Frame, x: int, y: int, t: Team | None) -> None:
    if t is None:
        team_mark(frame.draw, x, y, (70, 70, 70), (110, 110, 110))
    else:
        team_mark(frame.draw, x, y, hex_color(t.color), hex_color(t.alt_color, None) if t.alt_color else None)


def fit_name(t: Team, max_w: int) -> str:
    nick = t.nickname.upper()
    return nick if fonts.width(nick) <= max_w else t.abbreviation


def _last_name(n: str) -> str:
    """'K. Antonelli' / 'Max Verstappen' / 'J. Cook III' / 'D. Doué' -> 'ANTONELLI' / 'VERSTAPPEN' / 'COOK' / 'DOUE'.
    ASCII only: the LED fonts draw accents in the row above."""
    import unicodedata
    n = "".join(ch for ch in unicodedata.normalize("NFKD", n) if not unicodedata.combining(ch))
    parts = [p for p in n.replace(".", " ").split() if p.upper() not in ("JR", "SR", "II", "III", "IV", "V")]
    return parts[-1].upper() if parts else "?"


def _tournament_tag(name: str) -> str:
    n = name.upper()
    for junk in ("ROLEX ", "PRUDENTIAL ", "TENNIS ", " OPEN", " MASTERS", " CHAMPIONSHIPS", " INTERNATIONAL", "AMERICAN ", "BNP PARIBAS "):
        n = n.replace(junk, " ")
    return " ".join(n.split())[:9] or name.upper()[:9]


SECTIONS = ("boston", "nfl", "ucl", "f1", "tennis")
CARD_W = 128
CREST = 22
WALL_MAX_SLIDES = 3            # per section in the cycling wall; the dedicated panels show everything
PAIR_SECONDS = 7.0


def _compact_leader(cat: str, name: str, value: str) -> str:
    """('passingYards', 'J. Love', '30/41, 288 YDS, 3 TD, 1 INT') -> 'PASS LOVE 288Y 3TD'."""
    import re
    tag = {"passingYards": "PASS", "rushingYards": "RUSH", "receivingYards": "REC"}.get(cat, cat[:4].upper())
    yds = re.search(r"(\d+)\s*YDS", value.upper())
    td = re.search(r"(\d+)\s*TD", value.upper())
    bits = [tag, _last_name(name)]
    if yds:
        bits.append(f"{yds.group(1)}Y")
    if td:
        bits.append(f"{td.group(1)}TD")
    return " ".join(bits)


def _goal_text(goal, max_w: int) -> str:
    minute = goal.minute.replace("'+", "+")
    tag = minute + ("P" if goal.penalty else "") + (" OG" if goal.own_goal else "")
    name = _last_name(goal.scorer)
    while name and fonts.width(f"{name} {tag}") > max_w:
        name = name[:-1]
    return f"{name} {tag}".strip()


class SportsChannel(Channel):
    """One SportsFeed, several panels: name='sports' cycles every section (the wall); name in SECTIONS
    shows only that sport. All panels share the feed; it polls only what an on-screen panel needs."""

    name = "sports"

    def __init__(self, feed: SportsFeed | None = None, static: dict | None = None, page: str | None = None,
                 name: str = "sports"):
        self.name = name
        self.feed = feed or SportsFeed(static=static)
        self._owns_feed = feed is None
        self.feed.register(self)
        self.t = 0.0
        self.fixed_page = page          # demos / tests: pin one section
        if page:
            self.sections = [page if page != "live" else "boston"]
        elif name in SECTIONS:
            self.sections = [name]
        else:
            self.sections = list(self.feed.sections)

    def status(self) -> dict:
        s = self.feed.status()
        s["event"] = time.time() < self.feed.event_until
        return s

    def close(self):
        if self._owns_feed:
            self.feed.close()

    def tick(self, dt: float) -> None:
        self.t += dt

    # ---- scheduling ----------------------------------------------------------
    def priority(self) -> int:
        boston = "boston" in self.sections
        if boston and time.time() < self.feed.event_until:
            return 25
        if boston and self.feed.any_live():
            return 12
        return 4 if self.slides() else 0

    # ---- slides: (section, draw function, argument, seconds) ------------------------------
    def _section_slides(self, sec: str) -> list[tuple]:
        f = self.feed
        if sec == "live":
            return [("live", self._slide_live, g, 10.0) for g in f.games if g.live]
        if sec == "boston":
            return [("boston", self._slide_week, None, 10.0)] if self._week_rows() else []
        if sec == "nfl":
            return [("nfl", self._slide_pair, p, PAIR_SECONDS) for p in _pairs(self._nfl_order())]
        if sec == "ucl":
            return [("ucl", self._slide_pair, p, PAIR_SECONDS) for p in _pairs(self._ucl_day())]
        if sec == "f1":
            return [("f1", self._slide_f1, None, 12.0)] if f.races else []
        if sec == "tennis":
            return [("tennis", self._slide_tennis, p, PAIR_SECONDS) for p in _pairs(self._tennis_rows())]
        return []

    def slides(self) -> list[tuple]:
        if self.fixed_page:
            return self._section_slides(self.fixed_page)
        wall = self.name == "sports"
        out = []
        live = self._section_slides("live") if "boston" in self.sections else []
        for sec in self.sections:
            ss = self._section_slides(sec)
            if wall:
                ss = ss[:WALL_MAX_SLIDES]
            out += ss
            if live and ss:
                out += live                  # the live Boston game comes back after every section
        return out or live

    def pages(self) -> list[str]:
        """Section names in the order they appear (kept for the phone UI / tests)."""
        seen = []
        for sec, *_ in self.slides():
            if sec not in seen:
                seen.append(sec)
        return seen

    def current_slide(self):
        if self.feed.event_game and time.time() < self.feed.event_until and "boston" in self.sections:
            g = next((g for g in self.feed.games if g.id == self.feed.event_game), None)
            if g is not None:
                return ("live", self._slide_live, g, 15.0)
        slides = self.slides()
        if not slides:
            return None
        total = sum(sl[3] for sl in slides)
        pos = self.t % total
        for sl in slides:
            if pos < sl[3]:
                return sl
            pos -= sl[3]
        return slides[-1]

    def page(self) -> str | None:
        sl = self.current_slide()
        return sl[0] if sl else None

    # ---- drawing ------------------------------------------------------------------------
    def _header(self, frame: Frame, left: str, sub: str, color=AMBER) -> None:
        now = self.feed.now()
        frame.text(2, 0, left, fonts.SMALL, color)
        if sub:
            frame.text(2 + fonts.width(left + " ") + 2, 0, sub, fonts.SMALL, GREY, max_w=W - 40 - fonts.width(left) - 8)
        clock = now.strftime("%H:%M") if int(self.t) % 2 == 0 else now.strftime("%H %M")
        frame.text_right(W - 2, 0, clock, fonts.SMALL, AMBER)

    def render(self, frame: Frame) -> None:
        sl = self.current_slide()
        if sl is None:
            title = {"nfl": "NFL", "ucl": "CHAMPIONS LEAGUE", "f1": "F1", "tennis": "TENNIS"}.get(self.name, CONFIG.sports.city.upper())
            self._header(frame, title, "")
            err = self.feed.last_error
            frame.text_center(W // 2, 26, "NO DATA" if err else ("NOTHING ON" if self.feed.updated_at else "LOADING..."),
                              fonts.MEDIUM, RED if err else GREY)
            if err:
                frame.text_center(W // 2, 38, err.upper()[:40], fonts.SMALL, RED)
            return
        _, fn, arg, _ = sl
        fn(frame, arg)

    # ---- live Boston game (the original card) -------------------------------------------
    def _slide_live(self, frame: Frame, g: Game | None) -> None:
        now = self.feed.now()
        featured = g or pick_game(self.feed.games, now)
        when = "TONIGHT" if now.hour >= 17 or now.hour < 4 else "TODAY"
        self._header(frame, CONFIG.sports.city.upper(), when)
        if featured is None:
            return
        self._render_card(frame, featured, now)
        self._render_list(frame, featured, now)

    # ---- the Boston week -------------------------------------------------------------
    def _week_rows(self) -> list[tuple[Game, str, str]]:
        """(game, tracked abbr, label): last 3 results + next games, within -7..+10 days, by date."""
        f = self.feed
        now = f.now()
        rows = []
        for lg, ab, label in f.teams:
            for g in f.team_games(lg, ab):
                if timedelta(days=-7) <= g.start - now <= timedelta(days=10):
                    rows.append((g, ab, label))
        past = sorted([r for r in rows if r[0].state != "pre"], key=lambda r: r[0].start)[-3:]
        future = sorted([r for r in rows if r[0].state == "pre"], key=lambda r: r[0].start)[: 6 - len(past)]
        return sorted(past + future, key=lambda r: r[0].start)

    def _slide_week(self, frame: Frame, _=None) -> None:
        now = self.feed.now()
        self._header(frame, CONFIG.sports.city.upper(), "THIS WEEK")
        for i, (g, ab, label) in enumerate(self._week_rows()):
            y = ROW_Y0 + i * ROW_H
            local = g.start.astimezone(now.tzinfo)
            day = "TODAY" if local.date() == now.date() else DAYS[local.weekday()]
            frame.text(2, y, day, fonts.SMALL, AMBER if day == "TODAY" else GREY)
            _badge(frame, 34, y + 4, g.team(ab))
            frame.text(46, y, label.upper(), fonts.SMALL, WHITE)
            frame.text(86, y, g.league.upper(), fonts.SMALL, DIM)
            st = week_status(g, ab, now)
            col = GREEN if g.live else (WHITE if st.startswith("W ") or g.state == "pre" else GREY)
            frame.text_right(W - 2, y, st, fonts.SMALL, col)

    # ---- match cards: two games per screen --------------------------------------------------
    def _slide_pair(self, frame: Frame, pair: tuple) -> None:
        for i, g in enumerate(pair):
            if g is not None:
                self._match_card(frame, i * CARD_W, g)
        if len(pair) > 1 and pair[1] is not None:
            frame.draw.line([(CARD_W - 1, 2), (CARD_W - 1, H - 3)], fill=(28, 28, 32))

    def _crest(self, frame: Frame, x: int, y: int, t: Team) -> None:
        tile = LOGOS.get(t.logo, CREST)
        if tile is not None:
            frame.img.paste(tile, (x, y), tile)
            return
        col = hex_color(t.color)
        alt = hex_color(t.alt_color, None) if t.alt_color else None
        team_mark(frame.draw, x + 3, y + 3, col, alt, size=16)        # placeholder until the crest arrives

    def _match_card(self, frame: Frame, x0: int, g: Game) -> None:
        now = self.feed.now()
        soccer = g.league == "ucl"
        left, right = (g.home, g.away) if soccer else (g.away, g.home)      # soccer lists home first; US sports away @ home
        self._crest(frame, x0 + 3, 1, left)
        self._crest(frame, x0 + CARD_W - 3 - CREST, 1, right)
        cx = x0 + CARD_W // 2
        post, pre, live = g.state == "post", g.state == "pre", g.state == "in"
        ls, rs = left.score or 0, right.score or 0
        if pre:
            local = g.start.astimezone(now.tzinfo)
            frame.text_center(cx, 4, _clock_text(local), fonts.MEDIUM, WHITE)
            day = "TODAY" if local.date() == now.date() else f"{DAYS[local.weekday()]} {local.month}/{local.day}"
            status, scol = day, GREY
        else:
            score = f"{ls}-{rs}"
            if fonts.width(score, fonts.LARGE) <= CARD_W - 2 * CREST - 14:
                frame.text_center(cx, 4, score, fonts.LARGE, WHITE)
            else:
                frame.text_center(cx, 8, score, fonts.MEDIUM, WHITE)
            if live:
                if soccer:
                    status = (g.short_detail if g.short_detail.upper() in ("HT", "HALFTIME") else g.clock or g.short_detail).upper()
                else:
                    status = live_detail(g)
                scol = GREEN
            else:
                status = "FT" if soccer else ("FINAL OT" if "OT" in g.short_detail.upper() else "FINAL")
                scol = GREY
        lcol = WHITE if not post or ls >= rs else GREY
        rcol = WHITE if not post or rs >= ls else GREY
        frame.text(x0 + 3, 22, left.abbreviation[:4], fonts.SMALL, lcol)
        frame.text_right(x0 + CARD_W - 3, 22, right.abbreviation[:4], fonts.SMALL, rcol)
        frame.text_center(cx, 22, status[:10], fonts.SMALL, scol)
        rows = (31, 39, 47, 55)
        if soccer:
            self._goal_rows(frame, x0, g, left, rows)
        else:
            self._us_rows(frame, x0, g, left, right, rows)

    def _goal_rows(self, frame: Frame, x0: int, g: Game, left: Team, rows: tuple) -> None:
        if g.state == "pre":
            if left.record or g.opponent(left.abbreviation).record:
                frame.text(x0 + 3, rows[0], left.record, fonts.SMALL, DIM)
                frame.text_right(x0 + CARD_W - 3, rows[0], g.opponent(left.abbreviation).record, fonts.SMALL, DIM)
            return
        half = CARD_W // 2 - 4
        lgoals = [x for x in g.goals if x.home == left.home]
        rgoals = [x for x in g.goals if x.home != left.home]
        lreds = [n for home, n in g.red_cards if home == left.home]
        rreds = [n for home, n in g.red_cards if home != left.home]
        for goals, reds, right_side in ((lgoals, lreds, False), (rgoals, rreds, True)):
            lines = [(_goal_text(x, half), WHITE) for x in goals]
            lines += [("\u25a0 " + _last_name(n)[:8], RED) for n in reds]
            if len(lines) > len(rows):
                extra = len(lines) - len(rows) + 1
                lines = lines[: len(rows) - 1] + [(f"+{extra} MORE", GREY)]
            for y, (txt, col) in zip(rows, lines):
                if txt.startswith("\u25a0"):
                    name = txt[2:]
                    if right_side:
                        frame.text_right(x0 + CARD_W - 3, y, name, fonts.SMALL, GREY)
                        bx = x0 + CARD_W - 3 - fonts.width(name) - 5
                    else:
                        frame.text(x0 + 8, y, name, fonts.SMALL, GREY)
                        bx = x0 + 3
                    frame.rect([bx, y + 3, bx + 2, y + 7], fill=RED)       # red card
                elif right_side:
                    frame.text_right(x0 + CARD_W - 3, y, txt, fonts.SMALL, col)
                else:
                    frame.text(x0 + 3, y, txt, fonts.SMALL, col)
        if not g.goals and g.state == "post":
            frame.text_center(x0 + CARD_W // 2, rows[0], "NO GOALS", fonts.SMALL, DIM)

    def _us_rows(self, frame: Frame, x0: int, g: Game, left: Team, right: Team, rows: tuple) -> None:
        cx = x0 + CARD_W // 2
        if g.state == "pre":
            if left.record or right.record:
                frame.text(x0 + 3, rows[0], left.record, fonts.SMALL, DIM)
                frame.text_right(x0 + CARD_W - 3, rows[0], right.record, fonts.SMALL, DIM)
            return
        i = 0
        if g.live and g.situation.get("downDistanceText"):
            frame.text_center(cx, rows[0], g.situation["downDistanceText"].upper()[:20], fonts.SMALL, AMBER, max_w=CARD_W - 6)
            i = 1
        for cat, name, value in g.leaders[: len(rows) - i]:
            frame.text(x0 + 3, rows[i], _compact_leader(cat, name, value), fonts.SMALL, GREY, max_w=CARD_W - 6)
            i += 1

    def _nfl_order(self) -> list[Game]:
        rank = {"in": 0, "pre": 1, "post": 2}                 # live first, then upcoming, then finals
        return sorted(self.feed.nfl_week, key=lambda g: (rank.get(g.state, 3), g.start))

    def _ucl_day(self) -> list[Game]:
        """The matchday closest to now: live > today > most recent completed > next."""
        games = self.feed.ucl
        if not games:
            return []
        now = self.feed.now()
        by_day: dict = {}
        for g in games:
            by_day.setdefault(g.start.astimezone(now.tzinfo).date(), []).append(g)
        today = now.date()
        live_days = [d for d, gs in by_day.items() if any(g.live for g in gs)]
        if live_days:
            day = live_days[0]
        elif today in by_day:
            day = today
        else:
            past = [d for d in by_day if d < today]
            future = [d for d in by_day if d > today]
            day = max(past) if past and (not future or (today - max(past)).days <= (min(future) - today).days) else min(future)
        rank = {"in": 0, "post": 1, "pre": 2}
        return sorted(by_day[day], key=lambda g: (rank.get(g.state, 3), -len(g.goals), g.start))

    # ---- F1: podium + a car lapping the bottom of the wall ------------------------------------
    def _slide_f1(self, frame: Frame, _=None) -> None:
        now = self.feed.now()
        races = self.feed.races
        live = next((r for r in races if r.state == "in"), None)
        done = [r for r in races if r.state == "post" and r.results]
        nxt = next((r for r in races if r.state == "pre"), None)
        shown = live or (done[-1] if done else None)
        self._header(frame, "F1", (shown.short + (" LIVE" if live else "")) if shown else "", F1_RED)
        d = frame.draw
        if shown:
            steps = ((0, 52, 30, (150, 118, 30)), (1, 2, 36, (105, 105, 115)), (2, 102, 40, (118, 72, 38)))  # P1 centre, P2 left, P3 right
            for idx, x, top, col in steps:
                if idx >= len(shown.results):
                    continue
                pos, driver = shown.results[idx]
                d.rectangle([x, top, x + 47, 48], fill=col)
                frame.text_center(x + 24, top + 3, str(pos), fonts.MEDIUM, (20, 20, 20))
                last = _last_name(driver)
                name = last if fonts.width(last) <= 46 else tla(last)
                frame.text_center(x + 24, top - 9, name, fonts.SMALL, AMBER if pos == 1 else WHITE)
                main, _ = livery(last)
                d.rectangle([x + 1, top, x + 46, top + 1], fill=main)              # team colour along the top of the step
        if nxt:
            local = nxt.start.astimezone(now.tzinfo)
            days = (local.date() - now.date()).days
            when = "TODAY" if days == 0 else ("TOMORROW" if days == 1 else f"IN {days} DAYS")
            frame.text(158, 9, "NEXT RACE", fonts.SMALL, DIM)
            frame.text(158, 18, nxt.short, fonts.SMALL, WHITE, max_w=W - 160)
            frame.text(158, 27, f"{DAYS[local.weekday()]} {local.month}/{local.day} {_clock_text(local)}", fonts.SMALL, GREY)
            frame.text(158, 36, when, fonts.SMALL, AMBER)
        # the winner's car laps the bottom strip
        winner = _last_name(shown.results[0][1]) if shown and shown.results else ""
        main, accent = livery(winner)
        lap = 5.0
        x = int(-CAR_W + ((self.t % lap) / lap) * (W + CAR_W))
        car = car_sprite(main, accent, int(self.t * 12) % 4)
        for k in range(1, 4):                                                           # speed lines
            d.line([(x - 4 - k * 6, 56 + k), (x - 1 - k * 6 + 3, 56 + k)], fill=(60, 60, 64))
        frame.img.paste(car, (x, H - CAR_H - 1), car)
        for tx in range(0, W, 8):                                                       # kerb
            d.line([(tx, H - 1), (tx + 3, H - 1)], fill=(150, 30, 30) if (tx // 8) % 2 else (130, 130, 130))

    # ---- tennis: two TV-style scorebugs per screen ----------------------------------------------
    def _tennis_rows(self) -> list:
        """Matches with two known players: live first, then the deepest completed rounds, then next up."""
        ms = [m for m in self.feed.matches if all(p[0] and p[0].upper() not in ("TBD", "?", "BYE") for p in m.players)]
        live = [m for m in ms if m.state == "in"]
        done = sorted([m for m in ms if m.state == "post"], key=lambda m: (m.round_no, m.start), reverse=True)
        nxt = sorted([m for m in ms if m.state == "pre"], key=lambda m: m.start)
        return live + done[:8] + nxt[:4]

    def _slide_tennis(self, frame: Frame, pair: tuple) -> None:
        for i, m in enumerate(pair):
            if m is not None:
                self._scorebug(frame, i * 32, m)

    def _scorebug(self, frame: Frame, y0: int, m) -> None:
        d = frame.draw
        live = m.state == "in"
        head = f"{m.tour} {_tournament_tag(m.tournament)}"
        frame.text(2, y0 - 3, head, fonts.SMALL, GREY)
        frame.text(2 + fonts.width(head + " ") + 2, y0 - 3, m.round.upper()[:16], fonts.SMALL, DIM)
        frame.text_right(W - 2, y0 - 3, "LIVE" if live else ("FINAL" if m.state == "post" else m.short_detail.upper()[:12]),
                         fonts.SMALL, GREEN if live else DIM)
        nsets = max(len(m.players[0][2]), len(m.players[1][2]), 1)
        set_x0 = W - 2 - nsets * 14
        for row, (name, won, sets) in enumerate(m.players):
            y = y0 + 8 + row * 11
            d.rectangle([0, y - 1, W - 1, y + 8], fill=(14, 22, 40))                    # bug background
            if won:
                d.ellipse([2, y + 1, 7, y + 6], fill=(200, 230, 60))                     # the winner's ball
                d.point((4, y + 3), fill=(240, 240, 240))
            frame.text(12, y, _last_name(name)[:13], fonts.MEDIUM, WHITE if won or live else GREY, max_w=set_x0 - 16)
            other = m.players[1 - row][2]
            for k in range(nsets):
                v = sets[k] if k < len(sets) else None
                if v is None:
                    continue
                mine_won_set = k < len(other) and v > other[k]
                cx = set_x0 + k * 14 + 7
                frame.text_center(cx, y, str(v), fonts.MEDIUM, (240, 200, 60) if live and k == nsets - 1 else (WHITE if mine_won_set else GREY))


def _pairs(items: list) -> list[tuple]:
    return [tuple(items[i:i + 2]) if i + 1 < len(items) else (items[i], None) for i in range(0, len(items), 2)]


    def _render_card(self, frame: Frame, g: Game, now: datetime) -> None:
        for y, t in ((ROW_AWAY, g.away), (ROW_HOME, g.home)):
            _badge(frame, 2, y + 4, t)
            score = "" if t.score is None or g.state == "pre" else str(t.score)
            sw = fonts.width(score, fonts.LARGE) if score else 0
            name_max = X_SCORE - sw - 4 - 12
            frame.text(12, y + 3, fit_name(t, name_max), fonts.SMALL, WHITE if g.state != "post" or (t.score or 0) >= (g.opponent(t.abbreviation).score or 0) else GREY)
            if score:
                frame.text_right(X_SCORE, y, score, fonts.LARGE, WHITE)
        if g.live:
            frame.text_right(X_CARD_R, ROW_AWAY, "LIVE", fonts.SMALL, RED)
        frame.text_right(X_CARD_R, ROW_HOME, g.league.upper(), fonts.SMALL, DIM)

        tz = now.tzinfo
        local = g.start.astimezone(tz)
        if g.cancelled:
            frame.text(2, Y_STATUS, "POSTPONED", fonts.SMALL, GREY)
        elif g.state == "pre":
            day = "" if local.date() == now.date() else local.strftime("%a").upper()
            h = local.hour % 12 or 12
            t = f"{h}{'A' if local.hour < 12 else 'P'}" if local.minute == 0 else f"{h}:{local.minute:02d}{'A' if local.hour < 12 else 'P'}"
            frame.text(2, Y_STATUS, f"{day} {t}".strip(), fonts.SMALL, GREY)
            frame.text(2, Y_DETAIL, ("HOME" if g.home.abbreviation == self.feed.tracked_abbr(g) else "AWAY"), fonts.SMALL, DIM)
        elif g.state == "in":
            # MLB: ESPN's 'TOP 9TH'; others: 'Q3 4:12' / 'P2 12:30' (period + clock)
            frame.text(2, Y_STATUS, live_detail(g)[:18], fonts.SMALL, GREEN)
            self._render_detail(frame, g)
        else:
            frame.text(2, Y_STATUS, g.short_detail.upper().replace("/", " ")[:18], fonts.SMALL, GREY)

    def _render_detail(self, frame: Frame, g: Game) -> None:
        d = frame.draw
        sit = g.situation
        if g.league == "mlb":
            # bases: 2B top-centre, 3B left, 1B right; lit amber when occupied
            x0, y0 = 2, Y_DETAIL + 3
            for (dx, dy), key in (((4, 0), "onSecond"), ((0, 3), "onThird"), ((8, 3), "onFirst")):
                on = bool(sit.get(key))
                d.rectangle([x0 + dx, y0 + dy, x0 + dx + 2, y0 + dy + 2], fill=AMBER if on else None, outline=AMBER if on else DIM)
            outs = sit.get("outs")
            if outs is not None:
                frame.text(16, Y_DETAIL, f"{outs} OUT", fonts.SMALL, WHITE)
        elif g.league == "nfl":
            txt = (sit.get("downDistanceText") or "").upper()
            frame.text(2, Y_DETAIL, txt[:14], fonts.SMALL, WHITE)
            poss = sit.get("possession")
            if poss:
                # arrow toward the team with the ball: up = away row, down = home row
                x = X_CARD_R - 3
                up = poss == g.away.abbreviation
                pts = [(x, Y_DETAIL + 4), (x - 3, Y_DETAIL + 8), (x + 3, Y_DETAIL + 8)] if up else \
                      [(x, Y_DETAIL + 8), (x - 3, Y_DETAIL + 4), (x + 3, Y_DETAIL + 4)]
                d.polygon(pts, fill=AMBER)
                frame.text_right(x - 6, Y_DETAIL, poss, fonts.SMALL, AMBER)
        # NBA / NHL: period + clock is already the status line; nothing more to add

    def _render_list(self, frame: Frame, featured: Game, now: datetime) -> None:
        feat_key = (featured.league, self.feed.tracked_abbr(featured))
        rows = [(lg, ab, label) for lg, ab, label in self.feed.teams if (lg, ab) != feat_key]
        step = 14 if len(rows) <= 3 else 12
        for i, (lg, ab, label) in enumerate(rows[:4]):
            y = 12 + i * step
            mine = [g for g in self.feed.games if g.league == lg and g.team(ab) is not None]
            g = pick_game(mine, now)
            team = g.team(ab) if g else None
            _badge(frame, X_LIST, y + 2, team)
            status = format_status(g, ab, now) if g else "NO GAME"
            sw = fonts.width(status)
            max_label = W - 2 - sw - 4 - X_LABEL
            lab = label.upper()
            while lab and fonts.width(lab) > max_label:
                lab = lab[:-1]
            frame.text(X_LABEL, y, lab, fonts.SMALL, WHITE)
            frame.text_right(W - 2, y, status, fonts.SMALL, GREEN if g and g.live else (GREY if g else DIM))
