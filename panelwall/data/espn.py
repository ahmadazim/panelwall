"""ESPN public scoreboard JSON (undocumented, keyless, stable for years).

  GET {base}/{sport}/{league}/scoreboard?dates=YYYYMMDD-YYYYMMDD&limit=300
      -> {"events": [{"id", "date" (ISO, Z), "status": {"type": {"state": "pre"|"in"|"post",
                      "shortDetail": "Top 9th" | "Final" | "Final/OT" | "9/15 - 8:05 PM EDT",
                      "name": "STATUS_SCHEDULED"|...}, "period": int, "displayClock": "4:12"},
                      "competitions": [{"competitors": [{"homeAway", "score": "7",
                          "team": {"abbreviation", "displayName", "name", "color", "alternateColor"}}],
                          "situation": {"onFirst","onSecond","onThird","outs","downDistanceText","possession"}}]}]}

Verified live 15 Sep 2026 for mlb/nfl/nba/nhl (fixtures/espn_scoreboards.json is a
trimmed capture). Notes: NHL alternateColor can be null; `possession` is a team id
string; an empty User-Agent is refused (403); a 403 was once seen transiently and is
treated like any other error (kept data, retry next poll).

Parsing is per-event defensive: a malformed event is skipped, never the whole reply.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from ..config import CONFIG
from .polling import Backoff, DemandPoller, retry_after_seconds

SPORT_OF = {"mlb": "baseball", "nfl": "football", "nba": "basketball", "nhl": "hockey",
            "wnba": "basketball", "mls": "soccer", "ncaaf": "football", "ncaab": "basketball"}
REGULATION_PERIODS = {"mlb": 9, "nfl": 4, "nba": 4, "nhl": 3}
MAX_STATUS = 13
DAYS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")


@dataclass
class Team:
    abbreviation: str
    name: str            # "Boston Red Sox"
    nickname: str        # "Red Sox"
    color: str           # hex, no '#', may be ""
    alt_color: str
    score: int | None
    home: bool
    id: str = ""


@dataclass
class Game:
    league: str
    id: str
    start: datetime               # tz-aware UTC
    state: str                    # pre | in | post
    short_detail: str
    status_name: str              # STATUS_SCHEDULED, STATUS_FINAL, STATUS_POSTPONED, ...
    period: int
    clock: str
    home: Team
    away: Team
    situation: dict = field(default_factory=dict)

    def team(self, abbreviation: str) -> Team | None:
        for t in (self.home, self.away):
            if t.abbreviation == abbreviation:
                return t
        return None

    def opponent(self, abbreviation: str) -> Team:
        return self.away if self.home.abbreviation == abbreviation else self.home

    @property
    def live(self) -> bool:
        return self.state == "in"

    @property
    def cancelled(self) -> bool:
        return any(k in self.status_name for k in ("POSTPONED", "CANCELED", "CANCELLED", "SUSPENDED"))


# ---- parsing ---------------------------------------------------------------------------
def _int(v) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _parse_team(c: dict) -> Team:
    t = c["team"]
    name = t.get("displayName") or t.get("name") or t["abbreviation"]
    nick = t.get("name") or name.split()[-1]
    return Team(abbreviation=str(t["abbreviation"]).upper(), name=name, nickname=nick,
                color=t.get("color") or "", alt_color=t.get("alternateColor") or "",
                score=_int(c.get("score")), home=c.get("homeAway") == "home", id=str(t.get("id", "")))


def parse_event(e: dict, league: str) -> Game | None:
    """One scoreboard event -> Game, or None if anything essential is missing."""
    try:
        comp = e["competitions"][0]
        teams = [_parse_team(c) for c in comp["competitors"]]
        home = next(t for t in teams if t.home)
        away = next(t for t in teams if not t.home)
        st = e["status"]
        stype = st["type"]
        start = datetime.fromisoformat(e["date"].replace("Z", "+00:00"))
        sit = comp.get("situation") or {}
        situation = {k: sit.get(k) for k in ("onFirst", "onSecond", "onThird", "outs", "downDistanceText", "possession")
                     if sit.get(k) is not None}
        if "possession" in situation:   # team id -> abbreviation
            situation["possession"] = next((t.abbreviation for t in teams if t.id == str(situation["possession"])), None)
        return Game(league=league, id=str(e.get("id", "")), start=start, state=str(stype.get("state", "pre")),
                    short_detail=str(stype.get("shortDetail") or ""), status_name=str(stype.get("name") or ""),
                    period=_int(st.get("period")) or 0, clock=str(st.get("displayClock") or ""),
                    home=home, away=away, situation=situation)
    except (KeyError, IndexError, TypeError, ValueError, StopIteration):
        return None


def parse_scoreboard(doc: dict, league: str) -> list[Game]:
    games = []
    for e in (doc or {}).get("events", []) or []:
        g = parse_event(e, league)
        if g is not None:
            games.append(g)
    games.sort(key=lambda g: g.start)
    return games


# ---- status strings (<= 13 chars) ------------------------------------------------------
def _clock_text(dt_local: datetime) -> str:
    h = dt_local.hour % 12 or 12
    ap = "A" if dt_local.hour < 12 else "P"
    return f"{h}{ap}" if dt_local.minute == 0 else f"{h}:{dt_local.minute:02d}{ap}"


def live_detail(g: Game) -> str:
    """'TOP 9TH' (mlb), 'Q3 4:12' / 'OT 2:00' (nfl, nba), 'P2 12:30' / 'OT 4:00' (nhl)."""
    reg = REGULATION_PERIODS.get(g.league, 4)
    if g.league == "mlb":
        return g.short_detail.upper()[:MAX_STATUS] or f"INN {g.period}"
    if g.period > reg:
        label = "OT" if g.period == reg + 1 else f"{g.period - reg}OT"
    else:
        label = ("P" if g.league == "nhl" else "Q") + str(g.period)
    return f"{label} {g.clock}".strip()


def format_status(g: Game, us_abbr: str, now: datetime) -> str:
    """Compact status for the right-hand list. Always <= 13 characters.
       pre : 'SUN 1P @MIA', 'TUE 7P VS TOR', '8:05P @TEX' (today: no day)
       in  : '7-6 TOP 9TH', '98-95 Q3 4:12'
       post: 'W 112-98', 'L 2-3 OT', 'PPD'"""
    us = g.team(us_abbr)
    them = g.opponent(us_abbr)
    if us is None:
        return g.short_detail.upper()[:MAX_STATUS]
    tz = now.tzinfo
    local = g.start.astimezone(tz)
    day = "" if local.date() == now.astimezone(tz).date() else DAYS[local.weekday()]
    if g.cancelled:
        return f"{day} PPD".strip()
    if g.state == "pre":
        t = _clock_text(local)
        opp = them.abbreviation
        seps = (" VS ", " ") if us.home else (" @", "@")
        for d in (day, ""):                    # shorten: drop 'VS' / the space before '@', then the day
            for sep in seps:
                s = f"{d} {t}{sep}{opp}".strip()
                if len(s) <= MAX_STATUS:
                    return s
        return s[:MAX_STATUS]
    a, b = us.score if us.score is not None else 0, them.score if them.score is not None else 0
    if g.state == "in":
        detail = live_detail(g)
        for d in (detail, detail.split(" ")[0], ""):   # shorten: drop the clock, then the period
            s = f"{a}-{b} {d}".strip()
            if len(s) <= MAX_STATUS:
                return s
        return s[:MAX_STATUS]
    result = "W" if a > b else "L" if a < b else "T"
    ot = " OT" if ("OT" in g.short_detail.upper() or g.period > REGULATION_PERIODS.get(g.league, 99)) else ""
    return f"{result} {a}-{b}{ot}"[:MAX_STATUS]


def pick_game(games: list[Game], now: datetime) -> Game | None:
    """Live game, else next upcoming, else most recent final."""
    live = [g for g in games if g.live]
    if live:
        return live[0]
    upcoming = [g for g in games if g.state == "pre" and not g.cancelled and g.start >= now - timedelta(hours=6)]
    if upcoming:
        return min(upcoming, key=lambda g: g.start)
    done = [g for g in games if g.state == "post"]
    if done:
        return max(done, key=lambda g: g.start)
    return games[0] if games else None


# ---- client + feed -------------------------------------------------------------------
class EspnClient:
    def __init__(self, base: str | None = None, timeout: float | None = None):
        self.base = (base or CONFIG.sports.base).rstrip("/")
        self.timeout = timeout or CONFIG.data.http_timeout
        self.last_error: str | None = None
        self.backoff = Backoff()

    def url(self, league: str, start: datetime | None = None, end: datetime | None = None) -> str:
        sport = SPORT_OF.get(league, league)
        u = f"{self.base}/{sport}/{league}/scoreboard"
        if start is not None and end is not None:
            u += f"?dates={start:%Y%m%d}-{end:%Y%m%d}&limit=300"
        return u

    def scoreboard(self, league: str, start: datetime | None = None, end: datetime | None = None) -> dict | None:
        req = urllib.request.Request(self.url(league, start, end),
                                     headers={"User-Agent": "panelwall/0.1", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                doc = json.loads(r.read().decode("utf-8", "replace"))
            self.last_error = None
            self.backoff.reset()
            return doc
        except urllib.error.HTTPError as e:
            if e.code in (429, 403):      # ESPN answers 403 transiently when it is unhappy
                wait = self.backoff.note(retry_after_seconds(e.headers))
                self.last_error = f"HTTP {e.code} from ESPN; retrying in {int(wait)} s"
            else:
                self.last_error = f"HTTP {e.code} {league} scoreboard"
        except Exception as e:
            self.last_error = f"{type(e).__name__}: {e}"
        return None


class SportsFeed(DemandPoller):
    """Background poller for every tracked league. Snapshot: `games` = tracked games
    (any competitor is one of CONFIG.sports.teams), sorted by start. `event_until`
    is set 15 s into the future when a tracked team's score changes."""

    EVENT_SECONDS = 15.0

    def __init__(self, client: EspnClient | None = None, static: dict | None = None, teams: list | None = None):
        self.client = client or EspnClient()
        self.teams = [tuple(t) for t in (teams or CONFIG.sports.teams)]
        self.games: list[Game] = []
        self.updated_at = 0.0
        self.event_until = 0.0
        self.event_game: str | None = None
        self._scores: dict[tuple[str, str], int] = {}
        self._fixed_now: datetime | None = None
        self._init_demand()
        self._thread = None
        if static is not None:
            self._fixed_now = datetime.fromisoformat(static["_now"]) if static.get("_now") else None
            docs = {lg: static.get(lg) for lg in self.leagues()}
            self._ingest(docs)
            self.updated_at = time.time()
        else:
            self._thread = threading.Thread(target=self._poll_loop, daemon=True, name="espn-poll")
            self._thread.start()

    def leagues(self) -> list[str]:
        seen = []
        for lg, _, _ in self.teams:
            if lg not in seen:
                seen.append(lg)
        return seen

    def now(self) -> datetime:
        return self._fixed_now or datetime.now().astimezone()

    @property
    def last_error(self) -> str | None:
        return self.client.last_error

    def label(self, league: str, abbr: str) -> str:
        for lg, ab, label in self.teams:
            if lg == league and ab == abbr:
                return label
        return abbr

    def tracked_abbr(self, g: Game) -> str | None:
        for lg, ab, _ in self.teams:
            if lg == g.league and g.team(ab) is not None:
                return ab
        return None

    def _ingest(self, docs: dict[str, dict | None]) -> None:
        kept = [g for g in self.games if docs.get(g.league) is None]
        new = []
        for lg, doc in docs.items():
            if doc is None:
                continue
            for g in parse_scoreboard(doc, lg):
                if self.tracked_abbr(g) is not None:
                    new.append(g)
        games = sorted(kept + new, key=lambda g: g.start)
        # score-change detection for tracked teams (only meaningful for live games)
        t = time.time()
        for g in new:
            ab = self.tracked_abbr(g)
            us = g.team(ab) if ab else None
            if us is None or us.score is None:
                continue
            key = (g.league, g.id)
            prev = self._scores.get(key)
            if prev is not None and us.score != prev and g.live:
                self.event_until = t + self.EVENT_SECONDS
                self.event_game = g.id
            self._scores[key] = us.score
        self.games = games

    def any_live(self) -> bool:
        return any(g.live for g in self.games)

    def _poll_loop(self):
        cfg = CONFIG.sports
        self._wait_wanted()
        while not self._stop.is_set():
            today = datetime.now().astimezone().date()
            start = datetime.combine(today - timedelta(days=1), datetime.min.time())
            end = datetime.combine(today + timedelta(days=cfg.days_ahead), datetime.min.time())
            docs = {}
            for lg in self.leagues():
                docs[lg] = self.client.scoreboard(lg, start, end) if self.client.backoff.remaining() == 0 else None
            if any(d is not None for d in docs.values()):
                self._ingest(docs)
                self.updated_at = time.time()
            interval = cfg.poll_live_seconds if self.any_live() else cfg.poll_idle_seconds
            self._sleep_or_pause(max(interval, self.client.backoff.remaining()))

    def status(self) -> dict:
        return {"updated_at": self.updated_at or None, "last_error": self.last_error, "paused": self.paused,
                "games": len(self.games), "live": self.any_live()}

    def close(self):
        self._stop.set()
