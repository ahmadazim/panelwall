"""ESPN public site API (undocumented, keyless, stable for years) - the sports board's data.

Endpoints (all verified live 3 Nov 2026; fixtures/espn_board.json is a trimmed capture):
  /{sport}/{league}/teams/{abbr}/schedule   -> a team's whole season: results + upcoming (small, 1 request)
  /{sport}/{league}/scoreboard              -> TODAY's games with live `situation` (bases/outs, down & distance);
                                              NFL returns the whole current week
  /soccer/uefa.champions/scoreboard?dates=YYYYMM -> a month of Champions League fixtures/results
  /racing/f1/scoreboard?dates=YYYY          -> the season's races; the "Race" competition's competitors are
                                              drivers in finishing order (`order`, `athlete.shortName`)
  /tennis/{atp|wta}/scoreboard              -> current tournaments; matches under groupings[].competitions
                                              (round.displayName, competitors[].athlete, winner, linescores)
NOTE the `dates=YYYYMMDD-YYYYMMDD` RANGE form that worked in September now returns 400 on every
league ("Failed to get events endpoint") - that is what broke the board. Single days and
`dates=YYYYMM` still work. Responses may be gzip-encoded.

Parsing is per-event defensive: a malformed event is skipped, never the whole reply.
"""

from __future__ import annotations

import gzip
import json
import unicodedata
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from ..config import CONFIG
from .polling import Backoff, DemandPoller, retry_after_seconds

SPORT_OF = {"mlb": "baseball", "nfl": "football", "nba": "basketball", "nhl": "hockey",
            "wnba": "basketball", "mls": "soccer", "ncaaf": "football", "ncaab": "basketball",
            "ucl": "soccer"}
LEAGUE_PATH = {"ucl": "uefa.champions"}        # league id in the URL when it differs from our short name
REGULATION_PERIODS = {"mlb": 9, "nfl": 4, "nba": 4, "nhl": 3, "ucl": 2}
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
    logo: str = ""       # ESPN crest URL (data/logos.py turns it into an LED tile)
    record: str = ""     # "5-3" (overall), when ESPN sends it
    leaders: list = field(default_factory=list)   # [(category, "J. Tatum", "27.0")] - NBA: per-team leaders


@dataclass
class Goal:
    home: bool           # scored FOR the home side (own goals already credited correctly by ESPN's team id)
    scorer: str          # "A. Batrakov"
    minute: str          # "45'+3'"
    penalty: bool = False
    own_goal: bool = False


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
    goals: list = field(default_factory=list)       # [Goal] - soccer
    red_cards: list = field(default_factory=list)   # [(home: bool, player)]
    leaders: list = field(default_factory=list)     # [(category, "J. Love", "288 YDS 3 TD")] - NFL

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
    if isinstance(v, dict):                       # schedule endpoint: {"value": 3.0, "displayValue": "3"}
        v = v.get("value", v.get("displayValue"))
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _parse_team(c: dict) -> Team:
    t = c["team"]
    name = t.get("displayName") or t.get("name") or t["abbreviation"]
    nick = t.get("name") or name.split()[-1]
    logo = t.get("logo") or ""
    if not logo and isinstance(t.get("logos"), list) and t["logos"]:
        logo = (t["logos"][0] or {}).get("href") or ""
    rec = ""
    recs = c.get("records") if isinstance(c.get("records"), list) else []
    rec_alt = c.get("record")
    if isinstance(rec_alt, str):                                       # some feeds send record as a plain "5-2"
        rec_alt = [{"type": "total", "displayValue": rec_alt}]
    for r in recs + (rec_alt if isinstance(rec_alt, list) else []):    # scoreboard: records[].summary; schedule: record[].displayValue
        if isinstance(r, dict) and (r.get("type") in (None, "total") or r.get("name") in ("overall", "All Splits")):
            rec = str(r.get("summary") or r.get("displayValue") or "")
            break
    tl = []
    for cat in (c.get("leaders") if isinstance(c.get("leaders"), list) else []):
        try:
            top = (cat.get("leaders") or [{}])[0]
            ath = top.get("athlete") or {}
            tl.append((str(cat.get("name") or ""), str(ath.get("shortName") or ath.get("displayName") or ""), str(top.get("displayValue") or "")))
        except (TypeError, AttributeError, IndexError):
            continue
    return Team(abbreviation=str(t["abbreviation"]).upper(), name=name, nickname=nick,
                color=t.get("color") or "", alt_color=t.get("alternateColor") or "",
                score=_int(c.get("score")), home=c.get("homeAway") == "home", id=str(t.get("id", "")),
                logo=logo, record=rec, leaders=tl)


def _details(comp: dict, teams: list) -> tuple[list, list]:
    """Soccer: competitions[0].details -> goals and red cards, in match order."""
    side = {t.id: t.home for t in teams}
    goals, reds = [], []
    for d in comp.get("details") or []:
        try:
            home = side.get(str((d.get("team") or {}).get("id")))
            if home is None:
                continue
            who = (d.get("athletesInvolved") or [{}])[0]
            name = str(who.get("shortName") or who.get("displayName") or "")
            minute = str((d.get("clock") or {}).get("displayValue") or "")
            if d.get("scoringPlay"):
                goals.append(Goal(home=home, scorer=name, minute=minute,
                                  penalty=bool(d.get("penaltyKick")), own_goal=bool(d.get("ownGoal"))))
            elif d.get("redCard"):
                reds.append((home, name))
        except (TypeError, AttributeError, IndexError):
            continue
    return goals, reds


def _leaders(comp: dict) -> list:
    out = []
    for cat in (comp.get("leaders") if isinstance(comp.get("leaders"), list) else []):
        try:
            top = (cat.get("leaders") or [{}])[0]
            ath = top.get("athlete") or {}
            out.append((str(cat.get("name") or cat.get("abbreviation") or ""),
                        str(ath.get("shortName") or ath.get("displayName") or ""), str(top.get("displayValue") or "")))
        except (TypeError, AttributeError, IndexError):
            continue
    return out


def parse_event(e: dict, league: str) -> Game | None:
    """One scoreboard event -> Game, or None if anything essential is missing."""
    try:
        comp = e["competitions"][0]
        teams = [_parse_team(c) for c in comp["competitors"]]
        home = next(t for t in teams if t.home)
        away = next(t for t in teams if not t.home)
        st = e.get("status") or comp.get("status") or {}
        stype = st.get("type") or {}
        start = datetime.fromisoformat(e["date"].replace("Z", "+00:00"))
        sit = comp.get("situation") or {}
        situation = {k: sit.get(k) for k in ("onFirst", "onSecond", "onThird", "outs", "downDistanceText", "possession")
                     if sit.get(k) is not None}
        if "possession" in situation:   # team id -> abbreviation
            situation["possession"] = next((t.abbreviation for t in teams if t.id == str(situation["possession"])), None)
        goals, reds = _details(comp, teams)
        return Game(league=league, id=str(e.get("id", "") or comp.get("id", "")), start=start, state=str(stype.get("state", "pre")),
                    short_detail=str(stype.get("shortDetail") or ""), status_name=str(stype.get("name") or ""),
                    period=_int(st.get("period")) or 0, clock=str(st.get("displayClock") or ""),
                    home=home, away=away, situation=situation, goals=goals, red_cards=reds, leaders=_leaders(comp))
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
    if g.league == "ucl":
        return (g.clock or g.short_detail).upper()[:MAX_STATUS]       # "45'+2'", "HT", "FT"
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
def week_status(g: Game, us_abbr: str, now: datetime) -> str:
    """Status for a row that already shows the day: '7:30P VS MIL' / '7P @PIT' / 'W 3-2 OT' / '98-95 Q3'."""
    if g.state != "pre" or g.cancelled:
        return format_status(g, us_abbr, now)
    us, them = g.team(us_abbr), g.opponent(us_abbr)
    t = _clock_text(g.start.astimezone(now.tzinfo))
    return f"{t} VS {them.abbreviation}" if us is not None and us.home else f"{t} @{them.abbreviation}"


def game_row(g: Game, now: datetime, width_chars: int = 21) -> tuple[str, str]:
    """Compact one-line form for league lists: ('DEN 10 @KC 31', 'F') / ('LIV @FEN', 'WED 12:45P') /
    ('GAL 2 VFB 0', "45'"). Returns (teams part, status part)."""
    a, h = g.away, g.home
    if g.state == "pre":
        local = g.start.astimezone(now.tzinfo)
        day = "" if local.date() == now.astimezone(now.tzinfo).date() else DAYS[local.weekday()] + " "
        return f"{a.abbreviation} @{h.abbreviation}", f"{day}{_clock_text(local)}"
    sa, sh = a.score if a.score is not None else 0, h.score if h.score is not None else 0
    teams = f"{a.abbreviation} {sa} @{h.abbreviation} {sh}" if g.league != "ucl" else f"{a.abbreviation} {sa}-{sh} {h.abbreviation}"
    if g.state == "in":
        return teams, live_detail(g)
    ot = "/OT" if "OT" in g.short_detail.upper() else ""
    return teams, ("FT" if g.league == "ucl" else "F") + ot


@dataclass
class Race:
    name: str
    short: str                  # "MEXICO CITY GP"
    start: datetime             # race session start, UTC
    state: str                  # pre | in | post
    results: list               # [(position, driver short name)] top N, finishing order
    circuit: str = ""
    country: str = ""           # ESPN circuit.address.country, e.g. "Mexico", "Britain"


def parse_f1(doc: dict) -> list[Race]:
    out = []
    for e in (doc or {}).get("events", []) or []:
        try:
            comps = e.get("competitions") or []
            race = next((c for c in comps if (c.get("type") or {}).get("abbreviation", "").lower() == "race"), comps[-1] if comps else {})
            start = datetime.fromisoformat((race.get("date") or e["date"]).replace("Z", "+00:00"))
            stype = ((e.get("status") or race.get("status") or {}).get("type") or {})
            comps_sorted = sorted(race.get("competitors") or [], key=lambda c: c.get("order") or 99)
            results = [(int(c.get("order") or i + 1), str((c.get("athlete") or {}).get("shortName") or (c.get("athlete") or {}).get("displayName") or "?"))
                       for i, c in enumerate(comps_sorted)]
            name = str(e.get("name") or "")
            short = name.upper()
            for junk in ("MSC CRUISES ", "QATAR AIRWAYS ", "HEINEKEN ", "ARAMCO ", "PIRELLI ", "LENOVO ", "ROLEX ", "FORMULA 1 ",
                         "LOUIS VUITTON ", "CRYPTO.COM ", "AWS ", "STC ", "ETIHAD AIRWAYS ", "SINGAPORE AIRLINES ", "GULF AIR ",
                         "MOËT & CHANDON ", "MOET & CHANDON ", "TAG HEUER "):
                short = short.replace(junk, "")
            short = short.replace("GRAND PRIX", "GP").strip()
            short = "".join(ch for ch in unicodedata.normalize("NFKD", short) if not unicodedata.combining(ch))
            circuit = e.get("circuit") or {}
            out.append(Race(name=name, short=short, start=start, state=str(stype.get("state") or "pre"),
                            results=results, circuit=str(circuit.get("fullName") or ""),
                            country=str((circuit.get("address") or {}).get("country") or "")))
        except (KeyError, TypeError, ValueError, IndexError):
            continue
    out.sort(key=lambda r: r.start)
    return out


@dataclass
class Match:
    tour: str                   # ATP | WTA
    tournament: str
    round: str                  # "Final", "Semifinals", ...
    round_no: int
    start: datetime
    state: str
    short_detail: str
    players: list               # [(short name, winner: bool, [set scores as ints])] - 2 entries


@dataclass
class Tournament:
    tour: str
    name: str
    state: str
    short_detail: str
    start: datetime | None
    end: datetime | None


def parse_tennis(doc: dict, tour: str) -> tuple[list[Tournament], list[Match]]:
    tournaments, matches = [], []
    for e in (doc or {}).get("events", []) or []:
        try:
            stype = ((e.get("status") or {}).get("type") or {})
            t = Tournament(tour=tour.upper(), name=str(e.get("name") or ""), state=str(stype.get("state") or ""),
                           short_detail=str(stype.get("shortDetail") or ""),
                           start=datetime.fromisoformat(e["date"].replace("Z", "+00:00")) if e.get("date") else None,
                           end=datetime.fromisoformat(e["endDate"].replace("Z", "+00:00")) if e.get("endDate") else None)
            tournaments.append(t)
            groups = e.get("groupings") or []
            singles = next((g for g in groups if "singles" in str((g.get("grouping") or {}).get("slug", "")).lower()), groups[0] if groups else {})
            for c in singles.get("competitions") or []:
                try:
                    r = c.get("round") or {}
                    rname = str(r.get("displayName") if isinstance(r, dict) else r or "")
                    rno = int((r.get("number") if isinstance(r, dict) else 0) or 0)
                    cst = ((c.get("status") or {}).get("type") or {})
                    players = []
                    for pc in (c.get("competitors") or [])[:2]:
                        ath = pc.get("athlete") or {}
                        sets = [int(float(ls.get("value"))) for ls in (pc.get("linescores") or []) if ls.get("value") is not None]
                        players.append((str(ath.get("shortName") or ath.get("displayName") or "?"), bool(pc.get("winner")), sets))
                    if len(players) != 2:
                        continue
                    matches.append(Match(tour=tour.upper(), tournament=t.name, round=rname, round_no=rno,
                                         start=datetime.fromisoformat(c["date"].replace("Z", "+00:00")),
                                         state=str(cst.get("state") or ""), short_detail=str(cst.get("shortDetail") or ""), players=players))
                except (KeyError, TypeError, ValueError):
                    continue
        except (KeyError, TypeError, ValueError):
            continue
    matches.sort(key=lambda m: (m.round_no, m.start), reverse=True)
    return tournaments, matches


def match_row(m: Match) -> str:
    """'SINNER d. ZVEREV 6-3 7-6' or, in progress, 'SINNER-ZVEREV 6-3 2-1' """
    (n1, w1, s1), (n2, w2, s2) = m.players
    last = lambda n: n.replace(".", " ").split()[-1].upper()[:10] if n.strip() else "?"  # noqa: E731  'J. Sinner' -> 'SINNER'
    a, b = last(n1), last(n2)
    sets = " ".join(f"{x}-{y}" for x, y in zip(s1, s2))
    if m.state == "post":
        win, lose = (a, b) if w1 or not w2 else (b, a)
        if not w1 and w2:
            sets = " ".join(f"{y}-{x}" for x, y in zip(s1, s2))
        return f"{win} d. {lose} {sets}".strip()
    return f"{a}-{b} {sets}".strip()


def round_short(r: str) -> str:
    r = r.lower()
    if "final" in r and "semi" not in r and "quarter" not in r:
        return "F"
    if "semi" in r:
        return "SF"
    if "quarter" in r:
        return "QF"
    if "round of 16" in r or "4th" in r:
        return "R16"
    if "qualifying" in r:
        return "Q"
    return "".join(w[0] for w in r.split()[:2]).upper() or "R"


# ---- client + feed -------------------------------------------------------------------
class EspnClient:
    def __init__(self, base: str | None = None, timeout: float | None = None):
        self.base = (base or CONFIG.sports.base).rstrip("/")
        self.timeout = timeout or CONFIG.data.http_timeout
        self.last_error: str | None = None
        self.backoff = Backoff()

    def url(self, path: str, params: dict | None = None) -> str:
        u = f"{self.base}/{path.lstrip('/')}"
        return u + ("?" + urllib.parse.urlencode(params) if params else "")

    def get(self, path: str, params: dict | None = None) -> dict | None:
        req = urllib.request.Request(self.url(path, params), headers={"User-Agent": "panelwall/0.1", "Accept": "application/json",
                                                                       "Accept-Encoding": "gzip"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                raw = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                doc = json.loads(raw.decode("utf-8", "replace"))
            self.last_error = None
            self.backoff.reset()
            return doc
        except urllib.error.HTTPError as e:
            if e.code in (429, 403):      # ESPN answers 403 transiently when it is unhappy
                wait = self.backoff.note(retry_after_seconds(e.headers))
                self.last_error = f"HTTP {e.code} from ESPN; retrying in {int(wait)} s"
            else:
                self.last_error = f"HTTP {e.code} {path}"
        except Exception as e:
            self.last_error = f"{type(e).__name__}: {e}"
        return None

    # the endpoints the feed uses
    def schedule(self, league: str, abbr: str) -> dict | None:
        return self.get(f"{SPORT_OF.get(league, league)}/{LEAGUE_PATH.get(league, league)}/teams/{abbr.lower()}/schedule")

    def scoreboard(self, league: str, dates: str | None = None) -> dict | None:
        return self.get(f"{SPORT_OF.get(league, league)}/{LEAGUE_PATH.get(league, league)}/scoreboard", {"dates": dates} if dates else None)

    def f1(self, year: int) -> dict | None:
        return self.get("racing/f1/scoreboard", {"dates": str(year)})

    def tennis(self, tour: str) -> dict | None:
        return self.get(f"tennis/{tour}/scoreboard")


class SportsFeed(DemandPoller):
    """Background poller for the whole board. Each source has its own cadence (CONFIG.sports):
      schedules  - one /teams/<abbr>/schedule per tracked team, hourly: season results + upcoming
      live       - today's scoreboard for a league while one of its tracked games is on / about to
                   start (situation: bases, outs, down & distance); the live game replaces the
                   schedule's copy
      nfl / ucl / f1 / tennis - league pages, only if enabled in sections
    Snapshot attributes are replaced whole, never mutated, so render() can read them freely.
    `event_until` is set 15 s into the future when a tracked team's score changes."""

    EVENT_SECONDS = 15.0

    def __init__(self, client: EspnClient | None = None, static: dict | None = None, teams: list | None = None,
                 sections: list | None = None):
        self.client = client or EspnClient()
        self.teams = [tuple(t) for t in (teams or CONFIG.sports.teams)]
        self.sections = list(sections or CONFIG.sports.sections)
        self.games: list[Game] = []                   # tracked teams' games (schedule + live merge)
        self.team_colors: dict[tuple, tuple] = {}     # (league, abbr) -> (color, alt)
        self.team_info: dict[tuple, dict] = {}        # (league, abbr) -> {name, logo, record, standing}
        self.nba_day: list[Game] = []
        self.nfl_week: list[Game] = []
        self.nfl_week_number: int | None = None
        self.ucl: list[Game] = []
        self.races: list[Race] = []
        self.tournaments: list[Tournament] = []
        self.matches: list[Match] = []
        self.updated_at = 0.0
        self.event_until = 0.0
        self.event_game: str | None = None
        self._scores: dict[tuple[str, str], int] = {}
        self._fixed_now: datetime | None = None
        self._next: dict[str, float] = {}             # source -> epoch of the next fetch
        self.fetched: set[str] = set()                # sections that have completed at least one fetch
        self._init_demand()
        self._thread = None
        if static is not None:
            self._fixed_now = datetime.fromisoformat(static["_now"]) if static.get("_now") else None
            self._ingest_static(static)
            self.fetched = set(self.sections)
            self.updated_at = time.time()
        else:
            self._thread = threading.Thread(target=self._poll_loop, daemon=True, name="espn-poll")
            self._thread.start()

    # ---- helpers -------------------------------------------------------------------
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

    def any_live(self) -> bool:
        return any(g.live for g in self.games)

    def team_games(self, league: str, abbr: str) -> list[Game]:
        return [g for g in self.games if g.league == league and g.team(abbr) is not None]

    # ---- ingestion -----------------------------------------------------------------
    def _ingest_schedule(self, league: str, abbr: str, doc: dict | None) -> None:
        if doc is None:
            return
        team = doc.get("team") or {}
        if team.get("color"):
            self.team_colors[(league, abbr)] = (team.get("color"), team.get("alternateColor") or "")
        if team:
            self.team_info[(league, abbr)] = {"name": str(team.get("name") or team.get("displayName") or abbr),
                                              "logo": str(team.get("logo") or ""), "record": str(team.get("recordSummary") or ""),
                                              "standing": str(team.get("standingSummary") or "")}
        fresh = [g for g in parse_scoreboard(doc, league) if g.team(abbr) is not None]
        col, alt = self.team_colors.get((league, abbr), ("", ""))
        logo = self.team_info.get((league, abbr), {}).get("logo", "")
        for g in fresh:
            t = g.team(abbr)
            if t is not None and not t.color:
                t.color, t.alt_color = col, alt
            if t is not None and not t.logo:
                t.logo = logo
        keep = [g for g in self.games if not (g.league == league and g.team(abbr) is not None)]
        self.games = sorted(keep + fresh, key=lambda g: g.start)

    def _ingest_live(self, league: str, doc: dict | None) -> None:
        """Today's scoreboard: replace tracked games by id (brings live scores + situation)."""
        if doc is None:
            return
        live = {g.id: g for g in parse_scoreboard(doc, league) if self.tracked_abbr(g) is not None}
        if not live:
            return
        t = time.time()
        for g in live.values():
            ab = self.tracked_abbr(g)
            us = g.team(ab) if ab else None
            if us is not None and us.score is not None:
                key = (g.league, g.id)
                prev = self._scores.get(key)
                if prev is not None and us.score != prev and g.live:
                    self.event_until = t + self.EVENT_SECONDS
                    self.event_game = g.id
                self._scores[key] = us.score
        merged = [live.pop(g.id, g) for g in self.games] + list(live.values())
        self.games = sorted(merged, key=lambda g: g.start)

    def _ingest_static(self, static: dict) -> None:
        for key, doc in (static.get("schedules") or {}).items():
            lg, ab = key.split(":")
            self._ingest_schedule(lg, ab, doc)
        for lg, doc in (static.get("scoreboards") or {}).items():
            self._ingest_live(lg, doc)
        if static.get("nba_day"):
            self.nba_day = parse_scoreboard(static["nba_day"], "nba")
        if static.get("nfl_week"):
            self.nfl_week = parse_scoreboard(static["nfl_week"], "nfl")
            self.nfl_week_number = ((static["nfl_week"].get("week") or {}).get("number"))
        if static.get("ucl"):
            self.ucl = parse_scoreboard(static["ucl"], "ucl")
        if static.get("f1"):
            self.races = parse_f1(static["f1"])
        for tour, doc in (static.get("tennis") or {}).items():
            ts, ms = parse_tennis(doc, tour)
            self.tournaments = [t for t in self.tournaments if t.tour != tour.upper()] + ts
            self.matches = sorted([m for m in self.matches if m.tour != tour.upper()] + ms, key=lambda m: (m.round_no, m.start), reverse=True)

    # ---- polling -------------------------------------------------------------------
    def _due(self, key: str, t: float) -> bool:
        return t >= self._next.get(key, 0.0)

    def _schedule_next(self, key: str, t: float, seconds: float) -> None:
        self._next[key] = t + seconds

    def _near_live_leagues(self) -> set[str]:
        """Leagues with a tracked game in progress or starting within 30 min."""
        now = self.now()
        out = set()
        for g in self.games:
            if g.live or (g.state == "pre" and timedelta(0) <= g.start - now <= timedelta(minutes=30)):
                out.add(g.league)
        return out

    def wanted_sections(self) -> set[str]:
        """Sections some on-screen panel shows (all of them when no panel is registered: demos/tests)."""
        active = [u for u in self.users if getattr(u, "active", False)]
        if not self.users:
            return set(self.sections)
        out = set()
        for u in active:
            out |= set(getattr(u, "sections", self.sections))
        return out & set(self.sections) if out else set()

    def _poll_once(self) -> None:
        cfg = CONFIG.sports
        t = time.time()
        if self.client.backoff.remaining() > 0:
            return
        want = self.wanted_sections()
        if "boston" in want:
            if self._due("schedules", t):
                for lg, ab, _ in self.teams:
                    self._ingest_schedule(lg, ab, self.client.schedule(lg, ab))
                self._schedule_next("schedules", t, cfg.schedule_seconds)
                self.fetched.add("boston")
            near = self._near_live_leagues()
            for lg in near:
                if self._due(f"live:{lg}", t):
                    self._ingest_live(lg, self.client.scoreboard(lg))
                    self._schedule_next(f"live:{lg}", t, cfg.live_seconds)
        if "nfl" in want and self._due("nfl", t):
            doc = self.client.scoreboard("nfl")
            if doc is not None:
                self.nfl_week = parse_scoreboard(doc, "nfl")
                self.nfl_week_number = ((doc.get("week") or {}).get("number"))
            live = any(g.live for g in self.nfl_week)
            self._schedule_next("nfl", t, cfg.live_seconds if live else cfg.nfl_seconds)
            self.fetched.add("nfl")
        if "nba" in want and self._due("nba", t):
            doc = self.client.scoreboard("nba")
            games = parse_scoreboard(doc, "nba") if doc is not None else None
            if games is not None and not games:                       # off day: show yesterday's results
                prev = self.client.scoreboard("nba", (self.now() - timedelta(days=1)).strftime("%Y%m%d"))
                games = parse_scoreboard(prev, "nba") if prev is not None else []
            if games is not None:
                self.nba_day = games
            live = any(g.live for g in self.nba_day)
            self._schedule_next("nba", t, cfg.live_seconds if live else cfg.nfl_seconds)
            self.fetched.add("nba")
        if "ucl" in want and self._due("ucl", t):
            doc = self.client.scoreboard("ucl", self.now().strftime("%Y%m"))
            if doc is not None:
                self.ucl = parse_scoreboard(doc, "ucl")
            live = any(g.live for g in self.ucl)
            self._schedule_next("ucl", t, cfg.live_seconds if live else cfg.ucl_seconds)
            self.fetched.add("ucl")
        if "f1" in want and self._due("f1", t):
            doc = self.client.f1(self.now().year)
            if doc is not None:
                self.races = parse_f1(doc)
            live = any(r.state == "in" for r in self.races)
            self._schedule_next("f1", t, 120.0 if live else cfg.f1_seconds)
            self.fetched.add("f1")
        if "tennis" in want and self._due("tennis", t):
            for tour in ("atp", "wta"):
                doc = self.client.tennis(tour)
                if doc is not None:
                    ts, ms = parse_tennis(doc, tour)
                    self.tournaments = [x for x in self.tournaments if x.tour != tour.upper()] + ts
                    self.matches = sorted([m for m in self.matches if m.tour != tour.upper()] + ms,
                                          key=lambda m: (m.round_no, m.start), reverse=True)
            self._schedule_next("tennis", t, cfg.tennis_seconds)
            self.fetched.add("tennis")
        self.updated_at = time.time()

    def _anything_due(self) -> bool:
        """A section some on-screen panel wants that is due now - e.g. one just picked on the phone."""
        t = time.time()
        keys = {"boston": "schedules"}
        return any(self._due(keys.get(sec, sec), t) for sec in self.wanted_sections())

    def _poll_loop(self):
        self._startup_grace()
        self._wait_wanted()
        while not self._stop.is_set():
            self._poll_once()
            # sleep up to 30 s, but wake within 2 s when a newly selected sport needs its first fetch
            deadline = time.time() + max(30.0, self.client.backoff.remaining())
            while not self._stop.is_set() and time.time() < deadline:
                self._stop.wait(2.0)
                self.paused = not self.wanted()
                if self.client.backoff.remaining() == 0 and self._anything_due():
                    break
            self._wait_wanted()

    def status(self) -> dict:
        return {"updated_at": self.updated_at or None, "last_error": self.last_error, "paused": self.paused,
                "games": len(self.games), "live": self.any_live(), "nfl": len(self.nfl_week), "nba": len(self.nba_day), "ucl": len(self.ucl),
                "f1": len(self.races), "tennis": len(self.matches)}

    def close(self):
        self._stop.set()
