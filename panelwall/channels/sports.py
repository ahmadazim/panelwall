"""SportsChannel: a rotating sports board - Boston teams first, then the wider sports world.

Pages (CONFIG.sports.sections, default boston,nfl,ucl,f1,tennis), page_seconds each:
  live    - only while a tracked Boston game is on: the featured game card (badges, LARGE scores,
            bases/outs or down & distance) + the other tracked teams. Shown every other page.
  boston  - the week: the last results and next games of every tracked team, one row each
            ("SUN [badge] PATS      W 20-3", "THU [badge] CELTS  7:30P VS NY").
  nfl     - this week's NFL scores, two columns of six (away score / home score / status).
  ucl     - Champions League: the matchday closest to now (live > today > most recent > next).
  f1      - last race's top 6 and the next race with its date and countdown.
  tennis  - ATP + WTA: the latest matches with known players from the current tournaments.
Pages with no data are skipped. All text via Frame.text*, SMALL font (rows y+4..y+8 lit).

priority(): 25 for 15 s after a tracked team scores, 12 while a tracked game is live,
4 whenever the board has anything to show, else 0.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta

from .. import fonts
from ..config import CONFIG
from ..data.espn import (DAYS, Game, SportsFeed, Team, format_status, game_row, week_status, live_detail, match_row, pick_game,
                         round_short, _clock_text)
from ..framebuffer import Frame, W, AMBER, WHITE, GREY, DIM, GREEN, RED
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
    """'K. Antonelli' / 'Max Verstappen' -> 'ANTONELLI' / 'VERSTAPPEN'."""
    return n.replace(".", " ").split()[-1].upper() if n.strip() else "?"


def _tournament_tag(name: str) -> str:
    n = name.upper()
    for junk in ("ROLEX ", "PRUDENTIAL ", "TENNIS ", " OPEN", " MASTERS", " CHAMPIONSHIPS", " INTERNATIONAL", "AMERICAN ", "BNP PARIBAS "):
        n = n.replace(junk, " ")
    return " ".join(n.split())[:9] or name.upper()[:9]


class SportsChannel(Channel):
    name = "sports"

    def __init__(self, feed: SportsFeed | None = None, static: dict | None = None, page: str | None = None):
        self.feed = feed or SportsFeed(static=static)
        self._owns_feed = feed is None
        self.feed.register(self)
        self.t = 0.0
        self.fixed_page = page          # demos / tests: pin one page

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
        if time.time() < self.feed.event_until:
            return 25
        if self.feed.any_live():
            return 12
        return 4 if self.pages() else 0

    # ---- pages ---------------------------------------------------------------
    def pages(self) -> list[str]:
        f, out = self.feed, []
        for sec in f.sections:
            if sec == "boston" and self._week_rows():
                out.append("boston")
            elif sec == "nfl" and f.nfl_week:
                out.append("nfl")
            elif sec == "ucl" and self._ucl_day():
                out.append("ucl")
            elif sec == "f1" and f.races:
                out.append("f1")
            elif sec == "tennis" and self._tennis_rows():
                out.append("tennis")
        if f.any_live():                                  # the live card every other slot
            woven = []
            for p in out:
                woven += ["live", p]
            out = woven or ["live"]
        return out

    def page(self) -> str | None:
        if self.fixed_page:
            return self.fixed_page
        if self.feed.event_game and time.time() < self.feed.event_until:
            return "live"
        pages = self.pages()
        if not pages:
            return None
        return pages[int(self.t // CONFIG.sports.page_seconds) % len(pages)]

    # ---- drawing -------------------------------------------------------------
    def _header(self, frame: Frame, left: str, sub: str, color=AMBER) -> None:
        now = self.feed.now()
        frame.text(2, 0, left, fonts.SMALL, color)
        if sub:
            frame.text(2 + fonts.width(left + " ") + 2, 0, sub, fonts.SMALL, GREY, max_w=W - 40 - fonts.width(left) - 8)
        clock = now.strftime("%H:%M") if int(self.t) % 2 == 0 else now.strftime("%H %M")
        frame.text_right(W - 2, 0, clock, fonts.SMALL, AMBER)

    def render(self, frame: Frame) -> None:
        page = self.page()
        if page is None:
            self._header(frame, CONFIG.sports.city.upper(), "SPORTS")
            err = self.feed.last_error
            frame.text_center(W // 2, 26, "NO DATA" if err else "LOADING...", fonts.MEDIUM, RED if err else GREY)
            if err:
                frame.text_center(W // 2, 38, err.upper()[:40], fonts.SMALL, RED)
            return
        getattr(self, f"_page_{page}")(frame)

    # ---- live Boston game (the original card) -------------------------------------------
    def _page_live(self, frame: Frame) -> None:
        now = self.feed.now()
        games = self.feed.games
        live = [g for g in games if g.live]
        featured = live[0] if live else pick_game(games, now)
        if self.feed.event_game and time.time() < self.feed.event_until:
            featured = next((g for g in games if g.id == self.feed.event_game), featured)
        when = "TONIGHT" if now.hour >= 17 or now.hour < 4 else "TODAY"
        self._header(frame, CONFIG.sports.city.upper(), when)
        if featured is None:
            return
        self._render_card(frame, featured, now)
        self._render_list(frame, featured, now)

    # ---- the Boston week -------------------------------------------------------------
    def _week_rows(self) -> list[tuple[Game, str, str]]:
        """(game, tracked abbr, label): last 3 results + next 3 games, within -7..+10 days, by date."""
        f = self.feed
        now = f.now()
        rows = []
        for lg, ab, label in f.teams:
            for g in f.team_games(lg, ab):
                if timedelta(days=-7) <= g.start - now <= timedelta(days=10):
                    rows.append((g, ab, label))
        past = [r for r in rows if r[0].state != "pre"]
        future = [r for r in rows if r[0].state == "pre"]
        past = sorted(past, key=lambda r: r[0].start)[-3:]
        future = sorted(future, key=lambda r: r[0].start)[: 6 - len(past)]
        return sorted(past + future, key=lambda r: r[0].start)

    def _page_boston(self, frame: Frame) -> None:
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

    # ---- two-column scoreboards (NFL, UCL) ------------------------------------------------
    def _score_cell(self, frame: Frame, x0: int, y: int, g: Game, now: datetime) -> None:
        a, h = g.away, g.home
        post, pre = g.state == "post", g.state == "pre"
        sa, sh = a.score or 0, h.score or 0
        ca = WHITE if not post or sa >= sh else GREY
        ch = WHITE if not post or sh >= sa else GREY
        frame.text(x0, y, a.abbreviation[:4], fonts.SMALL, ca)
        if not pre:
            frame.text_right(x0 + 40, y, str(sa), fonts.SMALL, ca)
        frame.text(x0 + 46, y, h.abbreviation[:4], fonts.SMALL, ch)
        if not pre:
            frame.text_right(x0 + 86, y, str(sh), fonts.SMALL, ch)
        if pre:
            local = g.start.astimezone(now.tzinfo)
            day = "" if local.date() == now.date() else DAYS[local.weekday()] + " "
            frame.text_right(x0 + COL_W - 6, y, f"{day}{_clock_text(local)}", fonts.SMALL, GREY, max_w=COL_W - 6 - 72)
        elif g.state == "in":
            frame.text_right(x0 + COL_W - 6, y, live_detail(g).split(" ")[0][:5], fonts.SMALL, GREEN)
        else:
            frame.text_right(x0 + COL_W - 6, y, "F/OT" if "OT" in g.short_detail.upper() else ("FT" if g.league == "ucl" else "F"), fonts.SMALL, DIM)

    def _grid(self, frame: Frame, games: list[Game], per_page: int = 12) -> None:
        now = self.feed.now()
        pages = max(1, (len(games) + per_page - 1) // per_page)
        sub = int(self.t // (CONFIG.sports.page_seconds / pages)) % pages if pages > 1 else 0
        chunk = games[sub * per_page:(sub + 1) * per_page]
        rows = per_page // 2
        for i, g in enumerate(chunk):
            col, row = divmod(i, rows)
            self._score_cell(frame, 2 + col * COL_W, ROW_Y0 + row * ROW_H, g, now)

    def _nfl_order(self) -> list[Game]:
        # live first, then upcoming by kickoff, then finals by kickoff
        rank = {"in": 0, "pre": 1, "post": 2}
        return sorted(self.feed.nfl_week, key=lambda g: (rank.get(g.state, 3), g.start))

    def _page_nfl(self, frame: Frame) -> None:
        wk = self.feed.nfl_week_number
        self._header(frame, "NFL", f"WEEK {wk}" if wk else "THIS WEEK", (60, 130, 255))
        self._grid(frame, self._nfl_order())

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
        return sorted(by_day[day], key=lambda g: g.start)

    def _page_ucl(self, frame: Frame) -> None:
        games = self._ucl_day()
        now = self.feed.now()
        day = games[0].start.astimezone(now.tzinfo)
        label = "TODAY" if day.date() == now.date() else f"{DAYS[day.weekday()]} {day.month}/{day.day}"
        self._header(frame, "CHAMPIONS LEAGUE", label, UCL_BLUE)
        self._grid(frame, games, per_page=10)

    # ---- F1 ------------------------------------------------------------------------------
    def _page_f1(self, frame: Frame) -> None:
        now = self.feed.now()
        races = self.feed.races
        live = next((r for r in races if r.state == "in"), None)
        done = [r for r in races if r.state == "post" and r.results]
        nxt = next((r for r in races if r.state == "pre"), None)
        shown = live or (done[-1] if done else None)
        self._header(frame, "F1", (shown.short + (" - LIVE" if live else " RESULT")) if shown else "", F1_RED)
        if shown:
            for i, (pos, driver) in enumerate(shown.results[:6]):
                col, row = divmod(i, 3)
                y = ROW_Y0 + row * ROW_H
                x = 2 + col * COL_W
                frame.text(x, y, str(pos), fonts.SMALL, AMBER if pos == 1 else GREY)
                frame.text(x + 12, y, _last_name(driver), fonts.SMALL, WHITE if pos <= 3 else GREY)
        if nxt:
            local = nxt.start.astimezone(now.tzinfo)
            days = (local.date() - now.date()).days
            when = "TODAY" if days == 0 else ("TOMORROW" if days == 1 else f"IN {days} DAYS")
            frame.text(2, 40, "NEXT", fonts.SMALL, DIM)
            frame.text(32, 40, nxt.short, fonts.SMALL, WHITE, max_w=W - 34)
            frame.text(32, 49, f"{DAYS[local.weekday()]} {local.month}/{local.day} {_clock_text(local)}", fonts.SMALL, GREY)
            frame.text_right(W - 2, 49, when, fonts.SMALL, AMBER)

    # ---- tennis ----------------------------------------------------------------------------
    def _tennis_rows(self) -> list:
        """Latest matches with two known players: live first, then the deepest completed rounds."""
        ms = [m for m in self.feed.matches
              if all(p[0] and p[0].upper() not in ("TBD", "?", "BYE") for p in m.players)]
        live = [m for m in ms if m.state == "in"]
        done = sorted([m for m in ms if m.state == "post"], key=lambda m: (m.round_no, m.start), reverse=True)
        nxt = sorted([m for m in ms if m.state == "pre"], key=lambda m: m.start)
        return (live + done[: 6 - len(live)] + nxt)[:6]

    def _page_tennis(self, frame: Frame) -> None:
        tours = sorted({m.tour for m in self._tennis_rows()})
        self._header(frame, "TENNIS", " / ".join(tours), (220, 220, 60))
        for i, m in enumerate(self._tennis_rows()):
            y = ROW_Y0 + i * ROW_H
            frame.text(2, y, _tournament_tag(m.tournament), fonts.SMALL, GREY, max_w=54)
            frame.text(58, y, round_short(m.round), fonts.SMALL, AMBER if round_short(m.round) == "F" else DIM)
            frame.text(78, y, match_row(m), fonts.SMALL, GREEN if m.state == "in" else WHITE, max_w=W - 80)

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
