"""ElectionChannel: an election-night tracker - live map, balance of power, race calls.

Views (CONFIG.election.view_seconds each):
  senate / governors  x 0-95: the US map (Census outlines, Albers, AK/HI insets). Called states in
                      solid party colour, states where someone leads pulse dimly in that colour,
                      states with no votes yet grey, states with no race near-black. A state called
                      in the last 30 s flashes white.
                      x 100-253: title + races called / contested; a balance bar (Senate: 100 seats
                      incl. seats not up, majority marker; Governors: the 36 races); DEM n / GOP n /
                      n TO WIN; flips; the 3 latest calls (state, winner, FLIP/HOLD) - or the 3
                      closest uncalled races (leader +margin, % in) before any call.
  house               a 435-seat parliament chart (Dem from the left, GOP from the right, uncalled
                      grey) + the same balance panel and "DEM NEEDS n" rows.
  PROJECTED WINNER    for CONFIG.election.banner_seconds after a race is called: the state's
                      silhouette in party colour, state + office, the winner's name big, the vote split.

Data: data/elections.ElectionFeed (NYT results JSON with AP calls; 2 x ~120 KB gzipped per minute
while votes are counted). priority(): 25 during a PROJECTED WINNER banner, 6 while votes are being
counted, 2 with results, else 0.
"""

from __future__ import annotations

import math
import time

import numpy as np

from .. import fonts
from ..config import CONFIG
from ..data.elections import ElectionFeed, Race
from ..framebuffer import Frame, W, H, AMBER, WHITE, GREY, DIM, RED
from ..usmap import hemicycle, render_map, state_pixels, state_silhouette
from .base import Channel

D_COL, R_COL, I_COL = (40, 100, 235), (225, 45, 45), (170, 80, 210)
NO_VOTES, NO_RACE = (62, 64, 74), (22, 22, 28)
PARTY_COL = {"D": D_COL, "R": R_COL, "I": I_COL}
PARTY_NAME = {"D": "DEM", "R": "GOP", "I": "IND"}
MAP_W, MAP_H = 96, 62
PX = 100                    # right panel left edge
BAR_Y0, BAR_Y1 = 11, 17
ROWS = (37, 46, 55)
FLASH_SECONDS = 30.0
OFFICE_TITLE = {"S": "SENATE", "G": "GOVERNORS", "H": "HOUSE"}


def _scale(c, k):
    return tuple(max(0, min(255, int(v * k))) for v in c)


class ElectionChannel(Channel):
    name = "election"

    def __init__(self, feed: ElectionFeed | None = None, static: dict | None = None, view: str | None = None):
        self.feed = feed or ElectionFeed(static=static)
        self._owns_feed = feed is None
        self.feed.register(self)
        self.t = 0.0
        self.fixed_view = view

    def status(self) -> dict:
        return self.feed.status()

    def close(self):
        if self._owns_feed:
            self.feed.close()

    def tick(self, dt: float) -> None:
        self.t += dt

    # ---- scheduling ----------------------------------------------------------------------
    def banner(self) -> Race | None:
        if self.feed.calls and time.time() - self.feed.calls[0][0] < CONFIG.election.banner_seconds:
            return self.feed.calls[0][1]
        return None

    def priority(self) -> int:
        if self.banner() is not None:
            return 25
        if self.feed.counting():
            return 6
        return 2 if self.feed.results.races else 0

    def views(self) -> list[str]:
        res = self.feed.results
        out = []
        if any(o == "S" for o, _ in res.races):
            out.append("S")
        if any(o == "G" for o, _ in res.races):
            out.append("G")
        if "H" in res.chambers:
            out.append("H")
        return out

    def view(self) -> str | None:
        if self.fixed_view:
            return self.fixed_view
        if self.banner() is not None:
            return "banner"
        vs = self.views()
        return vs[int(self.t // CONFIG.election.view_seconds) % len(vs)] if vs else None

    # ---- drawing ------------------------------------------------------------------------------
    def render(self, frame: Frame) -> None:
        v = self.view()
        if v is None:
            err = self.feed.last_error
            frame.text_center(W // 2, 22, "ELECTION NIGHT", fonts.MEDIUM, WHITE)
            frame.text_center(W // 2, 36, ("NO DATA - " + err.upper()[:30]) if err else "WAITING FOR RESULTS", fonts.SMALL, RED if err else GREY)
            return
        if v == "banner":
            r = self.banner() or next((r for r in self.feed.results.races.values() if r.called), None)
            if r is not None:
                self._banner(frame, r)
            return
        if v == "H":
            self._house(frame)
        else:
            self._map_view(frame, v)

    # ---- map views -----------------------------------------------------------------------------
    def _state_colors(self, office: str) -> dict:
        pulse = 0.45 + 0.2 * (0.5 + 0.5 * math.sin(self.t * 2.4))
        now = time.time()
        flashing = {r.state for seen, r in self.feed.calls if r.office == office and now - seen < FLASH_SECONDS}
        cols = {}
        for (o, st), r in self.feed.results.races.items():
            if o != office:
                continue
            p = r.party
            if r.called:
                c = PARTY_COL.get(p, I_COL)
                if st in flashing and int(self.t * 4) % 2 == 0:
                    c = (235, 235, 235)
            elif p and r.reporting > 0:
                c = _scale(PARTY_COL.get(p, I_COL), pulse)
            else:
                c = NO_VOTES
            cols[st] = c
        return cols

    def _map_view(self, frame: Frame, office: str) -> None:
        rgb = render_map(self._state_colors(office), MAP_W, MAP_H, default=NO_RACE)
        frame.img.paste(_to_img(rgb), (0, 1))
        races = [r for (o, _), r in self.feed.results.races.items() if o == office]
        called = [r for r in races if r.called]
        frame.text(PX, 0, OFFICE_TITLE[office], fonts.MEDIUM, WHITE)
        frame.text_right(W - 2, 0, f"{len(called)}/{len(races)} CALLED", fonts.SMALL, GREY)
        if office == "S" and "S" in self.feed.results.chambers:
            ch = self.feed.results.chambers["S"]
            self._balance(frame, ch.seats.get("D", 0), ch.seats.get("R", 0), ch.seats.get("I", 0), ch.total, ch.to_win)
            flips = ch.flips
        else:
            d = sum(1 for r in called if r.winner and r.winner.party == "D")
            rr = sum(1 for r in called if r.winner and r.winner.party == "R")
            i = len(called) - d - rr
            self._balance(frame, d, rr, i, len(races), None)
            flips = {p: sum(1 for r in called if r.flip and r.winner and r.winner.party == p) for p in "DRI"}
        self._flips(frame, flips)
        recent = sorted(called, key=lambda r: r.called_at, reverse=True)[:3]
        if recent:
            for y, r in zip(ROWS, recent):
                self._call_row(frame, y, r)
        else:
            close = sorted([r for r in races if not r.called and r.reporting > 0 and r.runner_up],
                           key=lambda r: abs(r.leader.pct - r.runner_up.pct))[:3]
            for y, r in zip(ROWS, close):
                self._close_row(frame, y, r)

    def _balance(self, frame: Frame, d: int, r: int, i: int, total: int, to_win: int | None) -> None:
        x0, x1 = PX, W - 3
        span = x1 - x0 + 1
        dr = frame.draw
        dr.rectangle([x0, BAR_Y0, x1, BAR_Y1], fill=(36, 36, 42))
        if total:
            dw = round(span * d / total)
            iw = round(span * i / total)
            rw = round(span * r / total)
            if dw:
                dr.rectangle([x0, BAR_Y0, x0 + dw - 1, BAR_Y1], fill=D_COL)
            if iw:
                dr.rectangle([x0 + dw, BAR_Y0, x0 + dw + iw - 1, BAR_Y1], fill=I_COL)
            if rw:
                dr.rectangle([x1 - rw + 1, BAR_Y0, x1, BAR_Y1], fill=R_COL)
            if to_win:
                mx = x0 + round(span * (total / 2) / total)
                dr.line([(mx, BAR_Y0 - 1), (mx, BAR_Y1 + 1)], fill=WHITE)
        frame.text(PX, 19, f"DEM {d}", fonts.SMALL, D_COL)
        frame.text_right(W - 2, 19, f"GOP {r}", fonts.SMALL, R_COL)
        mid = f"{to_win} TO WIN" if to_win else (f"IND {i}" if i else "")
        if mid:
            frame.text_center((PX + W) // 2, 19, mid, fonts.SMALL, GREY if to_win else I_COL)

    def _flips(self, frame: Frame, flips: dict) -> None:
        x = PX
        frame.text(x, 28, "FLIPS", fonts.SMALL, GREY)
        x += fonts.width("FLIPS ") + 4
        shown = False
        for p in "DRI":
            n = flips.get(p, 0)
            if n or p in "DR":
                txt = f"{p}+{n}"
                frame.text(x, 28, txt, fonts.SMALL, PARTY_COL[p] if n else _scale(PARTY_COL[p], 0.45))
                x += fonts.width(txt + " ") + 4
                shown = True
        return shown

    def _call_row(self, frame: Frame, y: int, r: Race) -> None:
        p = r.winner.party if r.winner else ""
        col = PARTY_COL.get(p, I_COL)
        frame.rect([PX, y + 4, PX + 2, y + 8], fill=col)
        frame.text(PX + 6, y, r.state, fonts.SMALL, WHITE)
        frame.text(PX + 24, y, (r.winner.name if r.winner else "?").upper()[:13], fonts.SMALL, col, max_w=W - 2 - 36 - PX - 24)
        frame.text_right(W - 2, y, "FLIP" if r.flip else "HOLD", fonts.SMALL, AMBER if r.flip else GREY)

    def _close_row(self, frame: Frame, y: int, r: Race) -> None:
        col = PARTY_COL.get(r.leader.party, I_COL)
        frame.text(PX, y, r.state, fonts.SMALL, WHITE)
        frame.text(PX + 18, y, r.leader.name.upper()[:10], fonts.SMALL, col)
        frame.text_right(W - 34, y, f"+{abs(r.leader.pct - r.runner_up.pct):.1f}", fonts.SMALL, col)
        frame.text_right(W - 2, y, f"{int(r.reporting)}%", fonts.SMALL, GREY)

    # ---- House: a parliament chart ---------------------------------------------------------------
    def _house(self, frame: Frame) -> None:
        ch = self.feed.results.chambers["H"]
        seats = hemicycle(ch.total or 435, 96, 62)
        d, rr, i = ch.seats.get("D", 0), ch.seats.get("R", 0), ch.seats.get("I", 0)
        n = len(seats)
        dr = frame.draw
        for k, (x, y) in enumerate(seats):
            if k < d:
                c = D_COL
            elif k < d + i:
                c = I_COL
            elif k >= n - rr:
                c = R_COL
            else:
                c = NO_VOTES
            dr.point((x, y + 1), fill=c)
        top = min(y for _, y in seats)
        dr.line([(48, top - 3), (48, top - 1)], fill=WHITE)              # majority line
        frame.text_center(48, 50, str(ch.to_win), fonts.MEDIUM, WHITE)
        frame.text(PX, 0, "HOUSE", fonts.MEDIUM, WHITE)
        frame.text_right(W - 2, 0, f"{ch.called}/{ch.contested} CALLED", fonts.SMALL, GREY)
        self._balance(frame, d, rr, i, ch.total, ch.to_win)
        self._flips(frame, ch.flips)
        left = ch.total - d - rr - i
        rows = [(f"DEM NEEDS {max(0, ch.to_win - d)}", D_COL), (f"GOP NEEDS {max(0, ch.to_win - rr)}", R_COL),
                (f"{left} SEATS UNCALLED", GREY)]
        for y, (txt, col) in zip(ROWS, rows):
            frame.text(PX, y, txt, fonts.SMALL, col)

    # ---- PROJECTED WINNER -------------------------------------------------------------------------
    def _banner(self, frame: Frame, r: Race) -> None:
        p = r.winner.party if r.winner else ""
        col = PARTY_COL.get(p, I_COL)
        mask = state_silhouette(r.state, 62, 60)
        if mask is not None:
            glow = 0.75 + 0.25 * (0.5 + 0.5 * math.sin(self.t * 3.0))
            fill = np.array(_scale(col, glow), np.uint8)
            edge = mask & ~(np.roll(mask, 1, 0) & np.roll(mask, -1, 0) & np.roll(mask, 1, 1) & np.roll(mask, -1, 1))
            arr = np.zeros((60, 62, 3), np.uint8)
            arr[mask] = fill
            arr[edge] = _scale(col, 1.35)
            frame.img.paste(_to_img(arr), (1, 2))
        x = 68
        office = {"S": "SENATE", "G": "GOVERNOR"}.get(r.office, r.office)
        frame.text(x, 0, "PROJECTED WINNER", fonts.SMALL, AMBER if int(self.t * 2.5) % 2 == 0 else WHITE)
        frame.text_right(W - 2, 0, office, fonts.SMALL, GREY)
        state = r.state_name.upper()
        f = fonts.MEDIUM if fonts.width(state, fonts.MEDIUM) <= W - 2 - x else fonts.SMALL
        frame.text(x, 10, state, f, WHITE)
        tag = PARTY_NAME.get(p, "IND") + (" GAIN" if r.flip else " HOLD")
        frame.text(x, 19, tag, fonts.SMALL, AMBER if r.flip else GREY)
        name = (r.winner.name if r.winner else "?").upper()
        if fonts.width(name, fonts.LARGE) <= W - 2 - x:
            frame.text(x, 29, name, fonts.LARGE, col)
        else:
            frame.text(x, 32, name, fonts.MEDIUM, col, max_w=W - 2 - x)
        if r.winner and r.leader:
            other = r.runner_up if r.leader.name == r.winner.name else r.leader
            span = W - 2 - x
            ww = round(span * r.winner.pct / 100)
            frame.rect([x, 46, x + span - 1, 48], fill=(36, 36, 42))
            frame.rect([x, 46, x + ww - 1, 48], fill=col)
            a = f"{PARTY_NAME.get(r.winner.party, 'IND')} {r.winner.pct:.1f}%"
            frame.text(x, 51, a, fonts.SMALL, col)
            if other:
                ocol = PARTY_COL.get(other.party, I_COL)
                ow = round(span * other.pct / 100)
                frame.rect([x + span - ow, 46, x + span - 1, 48], fill=_scale(ocol, 0.8))
                b = f"{PARTY_NAME.get(other.party, 'IND')} {other.pct:.1f}%"
                frame.text(x + fonts.width(a + "  ") + 6, 51, b, fonts.SMALL, _scale(ocol, 0.8))
            frame.text_right(W - 2, 51, f"{int(r.reporting)}% IN", fonts.SMALL, GREY)

def _to_img(arr: np.ndarray):
    from PIL import Image
    return Image.fromarray(arr, "RGB")
