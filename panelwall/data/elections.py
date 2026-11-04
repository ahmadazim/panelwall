"""Live US election results from the New York Times' public results files (AP race calls).

    GET https://static01.nyt.com/elections-assets/pages/data/{date}/results-{senate|governor}.json

Unofficial (the JSON behind nytimes.com's results pages), keyless, gzip ~120 KB each. Verified
live on election night 3 Nov 2026. What we read:
  races[]                race_call_status ('called' | 'too_early' | ...), office_id ('S' | 'G'),
                         outcome.won [candidate ids], outcome.gained (a flip), outcome.winner_accepted_at,
                         candidate_metadata{id: first/last name, party.nyt_id 'DEM'|'GOP'|...},
                         reporting_units[0]: state_postal, name, eevp (% of expected vote in),
                                             candidates[{nyt_id, votes.total, leader}]
  partyControlData       results[0].offices{S, H}: party_balance{DEM, GOP, OTH}{seats, no_election,
                         flip_count}, to_win, num_races_called, open_seats   (the governor file
                         carries both S and H, so the 9 MB House file is never needed)
CNN's politics.api.cnn.io/results/national-races/2026-SG.json was also live but has no chamber
control, so NYT is the single source. A dead or changed feed degrades to "no data".
"""

from __future__ import annotations

import gzip
import json
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from ..config import CONFIG
from .polling import Backoff, DemandPoller, retry_after_seconds

PARTY = {"DEM": "D", "GOP": "R", "REP": "R"}          # anything else -> "I"


def party_letter(p: str | None) -> str:
    return PARTY.get((p or "").upper(), "I" if p else "")


@dataclass
class Candidate:
    name: str            # last name
    party: str           # D | R | I
    votes: int
    pct: float           # share of the votes counted


@dataclass
class Race:
    id: str
    office: str          # S | G
    state: str           # postal
    state_name: str
    called: bool
    winner: Candidate | None
    leader: Candidate | None
    runner_up: Candidate | None
    reporting: float     # % of expected vote counted
    flip: bool
    called_at: str = ""

    @property
    def party(self) -> str:
        """Party colouring the state: winner if called, else the leader once votes are in, else ''."""
        if self.winner:
            return self.winner.party
        if self.leader and self.leader.votes > 0:
            return self.leader.party
        return ""


@dataclass
class Chamber:
    office: str          # S | H
    seats: dict          # D/R/I -> seats won so far INCLUDING seats not up
    holdover: dict       # D/R/I -> seats not up for election
    flips: dict          # D/R/I -> seats gained
    to_win: int
    total: int
    called: int
    contested: int


@dataclass
class Results:
    races: dict = field(default_factory=dict)       # (office, state) -> Race
    chambers: dict = field(default_factory=dict)    # S | H -> Chamber


# ---- parsing ------------------------------------------------------------------------------------
def parse_races(doc: dict) -> list[Race]:
    out = []
    for r in (doc or {}).get("races") or []:
        try:
            unit = (r.get("reporting_units") or [{}])[0]
            meta = r.get("candidate_metadata") or {}
            total = sum(int((c.get("votes") or {}).get("total") or 0) for c in unit.get("candidates") or [])

            def cand(cid, votes):
                m = meta.get(cid) or {}
                return Candidate(name=str(m.get("last_name") or cid.split("-")[0].title()),
                                 party=party_letter((m.get("party") or {}).get("nyt_id")),
                                 votes=votes, pct=round(100.0 * votes / total, 1) if total else 0.0)

            ranked = sorted(unit.get("candidates") or [], key=lambda c: -int((c.get("votes") or {}).get("total") or 0))
            cands = [cand(c["nyt_id"], int((c.get("votes") or {}).get("total") or 0)) for c in ranked]
            outcome = r.get("outcome") or {}
            won = outcome.get("won") or []
            called = r.get("race_call_status") == "called" and bool(won)
            winner = next((c for c, raw in zip(cands, ranked) if raw["nyt_id"] in won), None) if called else None
            if called and winner is None:
                winner = cand(won[0], 0)
            out.append(Race(id=str(r.get("nyt_id") or ""), office=str(r.get("office_id") or ""),
                            state=str(unit.get("state_postal") or ""), state_name=str(unit.get("name") or ""),
                            called=called, winner=winner, leader=cands[0] if cands else None,
                            runner_up=cands[1] if len(cands) > 1 else None, reporting=float(unit.get("eevp") or 0.0),
                            flip=bool(outcome.get("gained")), called_at=str((outcome.get("winner_accepted_at") or [""])[0] or "")))
        except (KeyError, TypeError, ValueError, IndexError, AttributeError):
            continue
    return out


def parse_control(doc: dict) -> dict:
    out = {}
    for res in ((doc or {}).get("partyControlData") or {}).get("results") or []:
        for oid, o in (res.get("offices") or {}).items():
            try:
                bal = o.get("party_balance") or {}
                seats, hold, flips = {}, {}, {}
                for pid, b in bal.items():
                    k = party_letter(pid) or "I"
                    seats[k] = seats.get(k, 0) + int(b.get("seats") or 0)
                    hold[k] = hold.get(k, 0) + int(b.get("no_election") or 0)
                    flips[k] = flips.get(k, 0) + int(b.get("flip_count") or 0)
                tw = o.get("to_win") or {}
                out[oid] = Chamber(office=oid, seats=seats, holdover=hold, flips=flips,
                                   to_win=int(tw.get("DEM") or tw.get("GOP") or 0), total=int(o.get("total") or 0),
                                   called=int(o.get("num_races_called") or 0), contested=int(o.get("open_seats") or 0))
            except (TypeError, ValueError, AttributeError):
                continue
    return out


# ---- client + feed --------------------------------------------------------------------------------
class ElectionClient:
    def __init__(self, timeout: float | None = None):
        self.timeout = timeout or 20.0
        self.last_error: str | None = None
        self.backoff = Backoff()

    def url(self, office: str) -> str:
        return CONFIG.election.base.format(date=CONFIG.election.date, office=office)

    def fetch(self, office: str) -> dict | None:
        req = urllib.request.Request(self.url(office), headers={"User-Agent": "Mozilla/5.0 panelwall/0.1", "Accept-Encoding": "gzip"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                raw = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
            self.last_error = None
            self.backoff.reset()
            return json.loads(raw)
        except urllib.error.HTTPError as e:
            if e.code in (429, 403, 503):
                wait = self.backoff.note(retry_after_seconds(e.headers))
                self.last_error = f"HTTP {e.code} from NYT results; retrying in {int(wait)} s"
            else:
                self.last_error = f"HTTP {e.code} {office} results"
        except Exception as e:
            self.last_error = f"{type(e).__name__}: {e}"
        return None


class ElectionFeed(DemandPoller):
    """Polls the senate + governor files (60 s while votes are being counted, 15 min otherwise).
    `calls` is newest-first [(epoch seen, Race)] of races that became called while we watched;
    races already called at start-up are history, not news."""

    def __init__(self, client: ElectionClient | None = None, static: dict | None = None):
        self.client = client or ElectionClient()
        self.results = Results()
        self.calls: list[tuple[float, Race]] = []
        self.updated_at = 0.0
        self._seen_called: set | None = None
        self._init_demand()
        self._thread = None
        if static is not None:
            self._ingest(static.get("senate"), static.get("governor"))
            self.updated_at = time.time()
        else:
            self._thread = threading.Thread(target=self._poll_loop, daemon=True, name="election-poll")
            self._thread.start()

    @property
    def last_error(self) -> str | None:
        return self.client.last_error

    def _ingest(self, senate: dict | None, governor: dict | None) -> None:
        races = dict(self.results.races)
        chambers = dict(self.results.chambers)
        for doc in (senate, governor):
            if doc is None:
                continue
            for r in parse_races(doc):
                races[(r.office, r.state)] = r
            chambers.update(parse_control(doc))
        now = time.time()
        called = {k for k, r in races.items() if r.called}
        if self._seen_called is not None:
            fresh = [races[k] for k in called - self._seen_called]
            fresh.sort(key=lambda r: r.called_at)
            for r in fresh:
                self.calls.insert(0, (now, r))
            del self.calls[30:]
        self._seen_called = called
        self.results = Results(races=races, chambers=chambers)

    def counting(self) -> bool:
        return any(not r.called and r.reporting > 0 for r in self.results.races.values())

    def _poll_loop(self):
        self._startup_grace()
        self._wait_wanted()
        while not self._stop.is_set():
            if self.client.backoff.remaining() == 0:
                s, g = self.client.fetch("senate"), self.client.fetch("governor")
                if s is not None or g is not None:
                    self._ingest(s, g)
                    self.updated_at = time.time()
            cfg = CONFIG.election
            wait = cfg.live_seconds if (self.counting() or not self.results.races) else cfg.idle_seconds
            self._sleep_or_pause(max(wait, self.client.backoff.remaining()))

    def status(self) -> dict:
        rs = self.results.races.values()
        return {"updated_at": self.updated_at or None, "last_error": self.last_error, "paused": self.paused,
                "races": len(self.results.races), "called": sum(1 for r in rs if r.called), "new_calls": len(self.calls)}

    def close(self):
        self._stop.set()
