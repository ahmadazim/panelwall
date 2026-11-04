"""Re-capture fixtures/espn_board.json (and fixtures/logos/) from the live ESPN API.

    python tools/capture_espn_fixture.py

Trims every response to the keys panelwall reads so the fixture stays small, keeps soccer goal
details / NFL leaders / team records and crest URLs, and processes each crest into the 22 px LED
tile the cards use, so `demo-sports`, the sheet and the tests show real crests with no network.
"""

from __future__ import annotations

import datetime
import gzip
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from panelwall.data.logos import cache_name, process  # noqa: E402

BASE = "https://site.api.espn.com/apis/site/v2/sports/"
TILE = 22


def get(path: str) -> dict:
    req = urllib.request.Request(BASE + path, headers={"User-Agent": "panelwall/0.1", "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req, timeout=25) as r:
        raw = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
        return json.loads(raw)


def status(o: dict) -> dict:
    s = o.get("status") or {}
    return {"clock": s.get("clock"), "displayClock": s.get("displayClock"), "period": s.get("period"),
            "type": {k: (s.get("type") or {}).get(k) for k in ("id", "name", "state", "completed", "detail", "shortDetail")}}


def slim_team(t: dict) -> dict:
    team = t.get("team") or {}
    out = {"id": t.get("id"), "homeAway": t.get("homeAway"), "winner": t.get("winner"), "order": t.get("order"), "type": t.get("type"),
           "team": {k: team.get(k) for k in ("id", "location", "name", "abbreviation", "displayName", "shortDisplayName", "color", "alternateColor", "logo")}}
    if not out["team"].get("logo") and team.get("logos"):
        out["team"]["logo"] = (team["logos"][0] or {}).get("href")
    sc = t.get("score")
    out["score"] = sc if not isinstance(sc, dict) else {"value": sc.get("value"), "displayValue": sc.get("displayValue")}
    if t.get("records"):
        out["records"] = [{k: r.get(k) for k in ("name", "type", "summary")} for r in t["records"][:1]]
    if isinstance(t.get("record"), list):
        out["record"] = [{k: r.get(k) for k in ("type", "displayValue")} for r in t["record"][:1] if isinstance(r, dict)]
    elif isinstance(t.get("record"), str):
        out["record"] = t["record"]
    if isinstance(t.get("leaders"), list):
        out["leaders"] = [{"name": cat.get("name"), "leaders": [{"displayValue": (cat.get("leaders") or [{}])[0].get("displayValue"),
                           "athlete": {k: ((cat.get("leaders") or [{}])[0].get("athlete") or {}).get(k) for k in ("shortName", "displayName")}}]}
                          for cat in t["leaders"][:3]]
    if t.get("athlete"):
        out["athlete"] = {k: t["athlete"].get(k) for k in ("displayName", "shortName", "fullName")}
    if t.get("linescores"):
        out["linescores"] = [{"value": ls.get("value")} for ls in t["linescores"]]
    return out


def slim_comp(c: dict) -> dict:
    cc = {"id": c.get("id"), "date": c.get("date"), "type": {k: (c.get("type") or {}).get(k) for k in ("abbreviation", "text")},
          "competitors": [slim_team(t) for t in c.get("competitors", [])]}
    if "status" in c:
        cc["status"] = status(c)
    if c.get("situation"):
        cc["situation"] = {k: v for k, v in c["situation"].items()
                           if k in ("balls", "strikes", "outs", "onFirst", "onSecond", "onThird", "downDistanceText", "possession")}
    if c.get("details"):
        cc["details"] = [{"type": d.get("type"), "clock": {"displayValue": (d.get("clock") or {}).get("displayValue")},
                          "team": {"id": (d.get("team") or {}).get("id")}, "scoringPlay": d.get("scoringPlay"),
                          "redCard": d.get("redCard"), "penaltyKick": d.get("penaltyKick"), "ownGoal": d.get("ownGoal"),
                          "athletesInvolved": [{k: a.get(k) for k in ("displayName", "shortName")} for a in d.get("athletesInvolved", [])[:1]]}
                         for d in c["details"] if d.get("scoringPlay") or d.get("redCard")]
    if isinstance(c.get("leaders"), list):
        cc["leaders"] = [{"name": cat.get("name"), "leaders": [{"displayValue": (cat.get("leaders") or [{}])[0].get("displayValue"),
                          "athlete": {k: ((cat.get("leaders") or [{}])[0].get("athlete") or {}).get(k) for k in ("shortName", "displayName")}}]}
                         for cat in c["leaders"][:3]]
    if c.get("round"):
        cc["round"] = c["round"] if not isinstance(c["round"], dict) else {k: c["round"].get(k) for k in ("displayName", "number")}
    return cc


def slim_event(e: dict) -> dict:
    out = {"id": e.get("id"), "date": e.get("date"), "endDate": e.get("endDate"), "name": e.get("name"),
           "shortName": e.get("shortName"), "competitions": [slim_comp(c) for c in e.get("competitions", [])]}
    if "status" in e:
        out["status"] = status(e)
    if e.get("circuit"):
        out["circuit"] = {"fullName": e["circuit"].get("fullName"), "address": e["circuit"].get("address")}
    return out


def main() -> None:
    now = datetime.datetime.now().astimezone().replace(microsecond=0)
    fx = {"_comment": f"Captured live from site.api.espn.com on {now.isoformat()} by tools/capture_espn_fixture.py, "
                      "trimmed to the keys panelwall reads (crest URLs, records, soccer goals/red cards, NFL leaders kept).",
          "_now": now.isoformat(), "schedules": {}, "scoreboards": {}}
    for sport, league, abbr in (("baseball", "mlb", "bos"), ("football", "nfl", "ne"), ("basketball", "nba", "bos"), ("hockey", "nhl", "bos")):
        d = get(f"{sport}/{league}/teams/{abbr}/schedule")
        evs = d["events"]
        idx = next((i for i, e in enumerate(evs) if e["date"] >= now.strftime("%Y-%m-%dT%H:%MZ")), len(evs))
        team = d.get("team") or {}
        fx["schedules"][f"{league}:{abbr.upper()}"] = {
            "team": {k: team.get(k) for k in ("abbreviation", "displayName", "name", "color", "alternateColor", "logo",
                                              "recordSummary", "standingSummary")},
            "events": [slim_event(e) for e in evs[max(0, idx - 6):idx + 6]]}
        fx["scoreboards"][league] = {"events": [slim_event(e) for e in get(f"{sport}/{league}/scoreboard").get("events", [])[:6]]}
    nba = get("basketball/nba/scoreboard")
    fx["nba_day"] = {"events": [slim_event(e) for e in nba.get("events", [])]}
    nfl = get("football/nfl/scoreboard")
    fx["nfl_week"] = {"week": {"number": (nfl.get("week") or {}).get("number")}, "events": [slim_event(e) for e in nfl["events"]]}
    ucl = get("soccer/uefa.champions/scoreboard?dates=" + now.strftime("%Y%m"))
    evs = sorted(ucl["events"], key=lambda e: e["date"])
    keepd = set(sorted({e["date"][:10] for e in evs})[:4])
    fx["ucl"] = {"events": [slim_event(e) for e in evs if e["date"][:10] in keepd]}
    f1 = get("racing/f1/scoreboard?dates=" + now.strftime("%Y"))
    evs = sorted(f1["events"], key=lambda e: e["date"])
    idx = next((i for i, e in enumerate(evs) if (e.get("status") or {}).get("type", {}).get("state") == "pre"), len(evs))
    keep = evs[max(0, idx - 2):idx + 2]
    for e in keep:
        for c in e.get("competitions", []):
            c["competitors"] = sorted(c.get("competitors", []), key=lambda x: x.get("order", 99))[:6]
    fx["f1"] = {"events": [slim_event(e) for e in keep]}

    def known(c):
        return all(((x.get("athlete") or {}).get("displayName") or "TBD").upper() != "TBD" for x in c.get("competitors", []))

    def rn(c):
        r = c.get("round")
        return (r.get("number") if isinstance(r, dict) else 0) or 0

    fx["tennis"] = {}
    for tour in ("atp", "wta"):
        evs = []
        for e in get(f"tennis/{tour}/scoreboard")["events"][:3]:
            ee = {k: e.get(k) for k in ("id", "date", "endDate", "name", "shortName")}
            ee["status"] = status(e)
            ee["groupings"] = []
            for g in e.get("groupings", [])[:1]:
                comps = [c for c in g.get("competitions", []) if known(c)]
                post = sorted([c for c in comps if (c.get("status") or {}).get("type", {}).get("state") == "post"],
                              key=lambda c: (rn(c), c.get("date", "")), reverse=True)[:6]
                other = sorted([c for c in comps if (c.get("status") or {}).get("type", {}).get("state") != "post"],
                               key=lambda c: c.get("date", ""))[:4]
                ee["groupings"].append({"grouping": {k: g["grouping"].get(k) for k in ("displayName", "slug")},
                                        "competitions": [slim_comp(c) for c in post + other]})
            evs.append(ee)
        fx["tennis"][tour] = {"events": evs}
    out = ROOT / "fixtures" / "espn_board.json"
    out.write_text(json.dumps(fx, indent=1))
    # crests used by the fixture -> processed tiles
    urls = set()

    def walk(o):
        if isinstance(o, dict):
            if isinstance(o.get("logo"), str) and o["logo"].startswith("http"):
                urls.add(o["logo"])
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk({k: fx[k] for k in ("ucl", "nfl_week", "nba_day", "scoreboards", "schedules")})
    logo_dir = ROOT / "fixtures" / "logos"
    logo_dir.mkdir(parents=True, exist_ok=True)
    ok = 0
    for u in sorted(urls):
        try:
            req = urllib.request.Request(u, headers={"User-Agent": "panelwall/0.1"})
            with urllib.request.urlopen(req, timeout=15) as r:
                process(r.read(), TILE).save(logo_dir / cache_name(u, TILE))
            ok += 1
        except Exception as ex:
            print("  logo failed", u, ex)
    print(f"wrote {out} ({out.stat().st_size} bytes) and {ok}/{len(urls)} crest tiles to {logo_dir}")


if __name__ == "__main__":
    main()
