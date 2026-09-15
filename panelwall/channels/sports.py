"""SportsChannel: "BOSTON TONIGHT" - one featured game card + the other tracked teams.

Layout (256x64; SMALL text at y lights rows y+4..y+8, LARGE rows y..y+15):
  y 4-8     CITY  TONIGHT|TODAY                                         HH:MM
  x 0-127   featured card (live game, else next upcoming, else latest final):
    y 11-26   [badge] AWAY NICKNAME            score (LARGE, right-aligned at x=92)   LIVE (red, right)
    y 29-44   [badge] HOME NICKNAME            score                                  league (grey)
    y 50-54   status: pre 'TUE 8:05P' grey | live 'TOP 9TH' (mlb) / 'Q3 4:12' green | post 'FINAL' grey
    y 59-63   detail: MLB bases diamond + outs | NFL down & distance + possession arrow | pre HOME/AWAY
  x 132-255  one row per other tracked team: [badge] LABEL        status (<= 13 chars, right at 254)

Team nicknames are used when they fit next to the score; otherwise the abbreviation
(NBA 3-digit scores leave 30 px, so "CELTICS" -> "BOS").

priority(): 25 for 15 s after a tracked team scores, 12 while a tracked game is
live, 4 when a tracked game is today, else 0.
"""

from __future__ import annotations

import time
from datetime import datetime

from .. import fonts
from ..config import CONFIG
from ..data.espn import Game, SportsFeed, Team, format_status, live_detail, pick_game
from ..framebuffer import Frame, W, AMBER, WHITE, GREY, DIM, GREEN, RED
from ..glyphs import team_mark, hex_color
from .base import Channel

X_SCORE = 92
X_CARD_R = 126
X_LIST = 132
X_LABEL = 143
ROW_AWAY, ROW_HOME = 11, 29
Y_STATUS, Y_DETAIL = 46, 55


def _badge(frame: Frame, x: int, y: int, t: Team | None) -> None:
    if t is None:
        team_mark(frame.draw, x, y, (70, 70, 70), (110, 110, 110))
    else:
        team_mark(frame.draw, x, y, hex_color(t.color), hex_color(t.alt_color, None) if t.alt_color else None)


def fit_name(t: Team, max_w: int) -> str:
    nick = t.nickname.upper()
    return nick if fonts.width(nick) <= max_w else t.abbreviation


class SportsChannel(Channel):
    name = "sports"

    def __init__(self, feed: SportsFeed | None = None, static: dict | None = None):
        self.feed = feed or SportsFeed(static=static)
        self._owns_feed = feed is None
        self.feed.register(self)
        self.t = 0.0

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
        games = self.feed.games
        if not games:
            return 0
        if time.time() < self.feed.event_until:
            return 25
        if any(g.live for g in games):
            return 12
        now = self.feed.now()
        today = now.date()
        if any(g.start.astimezone(now.tzinfo).date() == today for g in games):
            return 4
        return 0

    # ---- drawing -------------------------------------------------------------
    def render(self, frame: Frame) -> None:
        now = self.feed.now()
        frame.text(2, 0, CONFIG.sports.city.upper(), fonts.SMALL, AMBER)
        when = "TONIGHT" if now.hour >= 17 or now.hour < 4 else "TODAY"
        frame.text(2 + fonts.width(CONFIG.sports.city.upper() + " ") + 2, 0, when, fonts.SMALL, GREY)
        clock = now.strftime("%H:%M") if int(self.t) % 2 == 0 else now.strftime("%H %M")
        frame.text_right(W - 2, 0, clock, fonts.SMALL, AMBER)

        games = self.feed.games
        if not games:
            msg = "NO GAMES THIS WEEK" if self.feed.last_error is None else "NO DATA"
            frame.text_center(W // 2, 26, msg, fonts.MEDIUM, GREY if self.feed.last_error is None else RED)
            if self.feed.last_error:
                frame.text_center(W // 2, 38, "CHECK NETWORK", fonts.SMALL, RED)
            return

        featured = pick_game(games, now)
        # prefer a game where the event (score change) just happened
        if self.feed.event_game and time.time() < self.feed.event_until:
            featured = next((g for g in games if g.id == self.feed.event_game), featured)
        self._render_card(frame, featured, now)
        self._render_list(frame, featured, now)

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
