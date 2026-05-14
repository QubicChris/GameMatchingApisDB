"""
Sofasport Matching Script
Queries the DB for a specific country and date, loads a Sofasport
schedule JSON, matches games and prints results.

Usage:
    python match_sofa.py --date 2026-04-29 --country Brazil --sofa-file events_schedule_category5.json
"""
import argparse
import json
import os
import datetime
from rapidfuzz import fuzz
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "mysql+pymysql://user:password@localhost:3306/pregames")
engine = create_engine(DATABASE_URL)

# Matching thresholds
SCORE_MATCH_THRESHOLD  = 55   # minimum fuzzy score when score tiebreaking
FUZZY_MATCH_THRESHOLD  = 55   # minimum fuzzy score for name-only match
TIME_WINDOW_MINUTES    = 30   # ± minutes around kickoff time


def load_db_games(country: str, date: str) -> list[dict]:
    """Load all games from the DB for a given country and date."""
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT
                g.id,
                g.home_team,
                g.away_team,
                g.league,
                g.country,
                g.date_time_starts_utc,
                g.sofa_event_id,
                MAX(cg.score_home) AS score_home,
                MAX(cg.score_away) AS score_away
            FROM games g
            LEFT JOIN company_games cg ON cg.game_id = g.id
            WHERE DATE(g.date_time_starts_utc) = :date
              AND g.country = :country
            GROUP BY g.id, g.home_team, g.away_team, g.league,
                     g.country, g.date_time_starts_utc, g.sofa_event_id
            ORDER BY g.date_time_starts_utc
        """), {"date": date, "country": country}).fetchall()
    return [dict(r._mapping) for r in rows]


CATEGORY_MAP = {
    "Afghanistan": 1084, "Albania": 69, "Algeria": 304, "Angola": 500,
    "Argentina": 48, "Armenia": 296, "Australia": 34, "Austria": 43,
    "Azerbaijan": 297, "Bahrain": 351, "Belarus": 73, "Belgium": 33,
    "Bolivia": 379, "Bosnia": 332, "Brazil": 13, "Bulgaria": 78,
    "Chile": 49, "China": 17, "Colombia": 274, "Costa Rica": 113,
    "Croatia": 14, "Cyprus": 102, "Czech Republic": 41, "Denmark": 8,
    "Ecuador": 165, "Egypt": 305, "England": 1, "Estonia": 157,
    "Europe": 1465, "Finland": 19, "France": 7, "Georgia": 270,
    "Germany": 30, "Ghana": 443, "Greece": 67, "Honduras": 437,
    "Hong Kong": 339, "Hungary": 29, "Iceland": 10, "India": 352,
    "Indonesia": 368, "Iran": 388, "Ireland": 51, "Israel": 66,
    "Italy": 31, "Jamaica": 475, "Japan": 52, "Jordan": 340,
    "Kazakhstan": 148, "Kenya": 453, "Kosovo": 317, "Kuwait": 341,
    "Latvia": 163, "Lebanon": 350, "Lithuania": 160, "Luxembourg": 110,
    "Malaysia": 85, "Malta": 111, "Mexico": 56, "Moldova": 75,
    "Montenegro": 333, "Morocco": 311, "Netherlands": 35, "New Zealand": 190,
    "Nicaragua": 469, "Nigeria": 444, "North & Central America": 1469,
    "North Macedonia": 159, "Northern Ireland": 127, "Norway": 5,
    "Oman": 354, "Panama": 468, "Paraguay": 58, "Peru": 20,
    "Philippines": 847, "Poland": 47, "Portugal": 44, "Qatar": 353,
    "Romania": 77, "Russia": 21, "Saudi Arabia": 310, "Scotland": 22,
    "Serbia": 152, "Singapore": 45, "Slovakia": 40, "Slovenia": 76,
    "South America": 1470, "South Korea": 55, "Spain": 32, "Sweden": 9,
    "Switzerland": 42, "Tanzania": 507, "Thailand": 485, "Tunisia": 312,
    "Turkey": 46, "USA": 26, "Uganda": 1022, "Ukraine": 86,
    "Uruguay": 57, "Uzbekistan": 385, "Venezuela": 264, "Wales": 129,
    "Zambia": 540,
}

RAPIDAPI_KEY  = os.getenv("RAPIDAPI_KEY", "")
RAPIDAPI_HOST = "sofasport.p.rapidapi.com"


def fetch_sofa_events(country: str, date: str) -> list[dict]:
    """
    Fetch events from Sofasport API for a given country and date.
    Looks up the category_id from CATEGORY_MAP using the country name.
    Returns a flat list of event dicts ready for matching.
    """
    import urllib.request
    import urllib.parse

    if not RAPIDAPI_KEY:
        raise ValueError("RAPIDAPI_KEY not set in .env")

    category_id = CATEGORY_MAP.get(country)
    if not category_id:
        raise ValueError(f"No Sofasport category_id found for country: {country!r}")

    url = f"https://{RAPIDAPI_HOST}/v1/events/schedule/category"
    params = urllib.parse.urlencode({"category_id": category_id, "date": date})
    full_url = f"{url}?{params}"

    headers = {
        "x-rapidapi-key":  RAPIDAPI_KEY,
        "x-rapidapi-host": RAPIDAPI_HOST,
    }

    req = urllib.request.Request(full_url, headers=headers, method="GET")
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    events = []
    for e in data.get("data", []):
        events.append({
            "id":         e["id"],
            "home":       e["homeTeam"]["name"],
            "away":       e["awayTeam"]["name"],
            "ts":         e["startTimestamp"],
            "score_home": e.get("homeScore", {}).get("current"),
            "score_away": e.get("awayScore", {}).get("current"),
            "status":     e.get("status", {}).get("description", ""),
            "league":     e["tournament"]["name"],
        })

    return events


def fuzzy_name_score(db_home: str, db_away: str, sofa_event: dict) -> float:
    """Score how well a DB game matches a Sofasport event by team names."""
    h = fuzz.token_sort_ratio(db_home.lower(), sofa_event["home"].lower())
    a = fuzz.token_sort_ratio(db_away.lower(), sofa_event["away"].lower())
    return (h + a) / 2


def match_game(db_game: dict, sofa_events: list[dict]) -> tuple[dict | None, str, float]:
    """
    Try to match a single DB game against all Sofasport events.

    Strategy:
      1. Convert DB date_time_starts_utc to epoch seconds (treating it as UTC)
         and compare against Sofasport startTimestamp (already epoch UTC).
         Window = ±TIME_WINDOW_MINUTES.
      2. If score available: look for exact score match among candidates
         - 1 match  → certain, return it
         - 0 matches → fall through to fuzzy on all time candidates
         - 2+ matches → tiebreak with fuzzy names
      3. Fuzzy name match on remaining candidates

    Returns: (best_sofa_event, method, confidence_score)
    """
    import calendar

    # Convert DB naive datetime to epoch seconds treating it as UTC
    # calendar.timegm avoids the local-timezone trap of datetime.timestamp()
    db_epoch = calendar.timegm(db_game["date_time_starts_utc"].timetuple())

    # ── Step 1: time window filter ────────────────────────────────────────────
    window_secs = TIME_WINDOW_MINUTES * 60
    candidates = [
        e for e in sofa_events
        if abs(e["ts"] - db_epoch) <= window_secs
    ]

    if not candidates:
        return None, "NO_TIME", 0.0

    # ── Step 2: exact score match ─────────────────────────────────────────────
    sh, sa = db_game["score_home"], db_game["score_away"]
    if sh is not None and sa is not None:
        score_matches = [
            e for e in candidates
            if e["score_home"] == sh and e["score_away"] == sa
        ]
        if len(score_matches) == 1:
            # Unique score + time — confirm with a light name check
            # If names are completely different (score coincidence), reject it
            name_score = fuzzy_name_score(db_game["home_team"], db_game["away_team"], score_matches[0])
            if name_score >= SCORE_MATCH_THRESHOLD:
                return score_matches[0], "SCORE", 100.0
            # Names too different — score match is a coincidence, fall through
        if len(score_matches) > 1:
            # Same score, same time — tiebreak with fuzzy names
            best = max(score_matches, key=lambda e: fuzzy_name_score(db_game["home_team"], db_game["away_team"], e))
            score = fuzzy_name_score(db_game["home_team"], db_game["away_team"], best)
            if score >= SCORE_MATCH_THRESHOLD:
                return best, "SCORE+FUZZY", score
            # Names too different — fall through to pure fuzzy

    # ── Step 3: fuzzy name match on all time-window candidates ───────────────
    best = max(candidates, key=lambda e: fuzzy_name_score(db_game["home_team"], db_game["away_team"], e))
    score = fuzzy_name_score(db_game["home_team"], db_game["away_team"], best)
    if score >= FUZZY_MATCH_THRESHOLD:
        return best, "FUZZY", score
    return best, "MISS", score


def run(date: str, country: str, sofa_file: str = None):

    # Load DB games
    db_games = load_db_games(country, date)

    # Load Sofa events — from file if provided, otherwise live API call
    if sofa_file:
        print(f"  Loading Sofasport events from file: {sofa_file}")
        with open(sofa_file) as f:
            data = json.load(f)
        sofa_events = []
        for e in data["data"]:
            sofa_events.append({
                "id":         e["id"],
                "home":       e["homeTeam"]["name"],
                "away":       e["awayTeam"]["name"],
                "ts":         e["startTimestamp"],
                "score_home": e.get("homeScore", {}).get("current"),
                "score_away": e.get("awayScore", {}).get("current"),
                "status":     e.get("status", {}).get("description", ""),
                "league":     e["tournament"]["name"],
            })
    else:
        print(f"  Fetching Sofasport events for {country} on {date}...")
        sofa_events = fetch_sofa_events(country, date)
        print(f"  Fetched {len(sofa_events)} events")

    print()
    print(f"  Sofasport Match — {country} | {date}")
    print(f"  {'='*65}")
    print(f"  DB games        : {len(db_games)}")
    print(f"  Sofa events     : {len(sofa_events)}")
    print()

    # Match each DB game
    matched = missed = 0
    results = []

    for g in db_games:
        sofa, method, confidence = match_game(g, sofa_events)
        results.append((g, sofa, method, confidence))
        if method != "NO_TIME" and method != "MISS":
            matched += 1
        else:
            missed += 1

    # ── Results table ─────────────────────────────────────────────────────────
    print(f"  {'ID':<6} {'Time':>5} {'Score':>5} {'Method':<12} {'Conf':>4}  {'DB Game':<40} {'Sofa Match'}")
    print(f"  {'-'*120}")

    for g, sofa, method, confidence in results:
        time_str = g["date_time_starts_utc"].strftime("%H:%M")
        score    = f"{g['score_home']}-{g['score_away']}" if g["score_home"] is not None else "?-?"
        db_label = f"{g['home_team']} vs {g['away_team']}"

        if sofa and method not in ("NO_TIME", "MISS"):
            sofa_label = f"{sofa['home']} vs {sofa['away']} (id={sofa['id']})"
        else:
            sofa_label = "— NO MATCH —"

        status = "✓" if method not in ("NO_TIME", "MISS") else "✗"
        print(f"  {status} {g['id']:<5} {time_str:>5} {score:>5} {method:<12} {confidence:>4.0f}  {db_label:<40} {sofa_label}")

    # ── Score discrepancies ───────────────────────────────────────────────────
    discrepancies = [
        (g, sofa) for g, sofa, method, _ in results
        if sofa and method not in ("NO_TIME", "MISS")
        and g["score_home"] is not None
        and (g["score_home"] != sofa["score_home"] or g["score_away"] != sofa["score_away"])
    ]
    if discrepancies:
        print()
        print(f"  ⚠ Score discrepancies ({len(discrepancies)}):")
        for g, sofa in discrepancies:
            print(f"    [{g['id']}] {g['home_team']} vs {g['away_team']}")
            print(f"      DB score   : {g['score_home']}-{g['score_away']}")
            print(f"      Sofa score : {sofa['score_home']}-{sofa['score_away']}")

    # ── Summary ───────────────────────────────────────────────────────────────
    print()
    print(f"  {'='*65}")
    print(f"  Matched : {matched}/{len(db_games)}")
    print(f"  Missed  : {missed}/{len(db_games)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Match DB games against Sofasport schedule")
    parser.add_argument("--date",      required=True,  help="Date (YYYY-MM-DD)")
    parser.add_argument("--country",   required=True,  help="Country name as stored in DB")
    parser.add_argument("--sofa-file", required=False, help="Optional: path to local Sofasport JSON (skips API call)")
    args = parser.parse_args()
    run(args.date, args.country, sofa_file=args.sofa_file)