"""
Batch Sofasport Matching
Fetches all countries with unmatched games for a given date,
calls the Sofasport API once per country, fuzzy-matches, and
writes sofa_event_id back to the games table.

Usage:
    python batch_match_sofa.py --date 2026-05-12
    python batch_match_sofa.py --date 2026-05-12 --dry-run       # match but don't write
    python batch_match_sofa.py --date 2026-05-12 --unmatched-only # skip already matched
    python batch_match_sofa.py --date 2026-05-12 --min-confidence 70
"""
import argparse
import calendar
import json
import logging
import os
import time
import urllib.request
import urllib.parse
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from rapidfuzz import fuzz
from sqlalchemy import create_engine, text

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "mysql+pymysql://user:password@localhost:3306/pregames")
engine = create_engine(DATABASE_URL)

RAPIDAPI_KEY  = os.getenv("RAPIDAPI_KEY", "")
RAPIDAPI_HOST = "sofasport.p.rapidapi.com"

# Matching thresholds
SCORE_MATCH_THRESHOLD = 55
FUZZY_MATCH_THRESHOLD = 55
TIME_WINDOW_MINUTES   = 30

# Delay between API calls to avoid rate limiting (seconds)
API_CALL_DELAY = 0.5

# Sofasport odds provider (1 = Bet365)
ODDS_PROVIDER_ID = int(os.getenv("ODDS_PROVIDER_ID", "1"))

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


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def load_db_games(date: str, unmatched_only: bool) -> dict[str, list[dict]]:
    """Load games grouped by country for a given date."""
    sql = """
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
    """
    if unmatched_only:
        sql += " AND g.sofa_event_id IS NULL"
    sql += """
        GROUP BY g.id, g.home_team, g.away_team, g.league,
                 g.country, g.date_time_starts_utc, g.sofa_event_id
        ORDER BY g.date_time_starts_utc
    """
    with engine.connect() as conn:
        rows = conn.execute(text(sql), {"date": date}).fetchall()

    by_country = defaultdict(list)
    for r in rows:
        by_country[r.country].append(dict(r._mapping))
    return by_country


def write_sofa_ids(matches: list[tuple[int, int, dict]], dry_run: bool, all_db_games: list[dict]):
    """
    Write sofa_event_id to games table and upsert sofa_games row.
    matches = [(game_id, sofa_id, sofa_event_dict)]
    """
    if dry_run or not matches:
        return
    with engine.begin() as conn:
        for game_id, sofa_id, sofa_event in matches:
            # Upsert sofa_games row
            conn.execute(text("""
                INSERT INTO sofa_games
                    (sofa_event_id, home_name, away_name, league_name,
                     start_timestamp, score_home, score_away, status)
                VALUES
                    (:sofa_event_id, :home_name, :away_name, :league_name,
                     :start_timestamp, :score_home, :score_away, :status)
                ON DUPLICATE KEY UPDATE
                    home_name       = VALUES(home_name),
                    away_name       = VALUES(away_name),
                    league_name     = VALUES(league_name),
                    start_timestamp = VALUES(start_timestamp),
                    score_home      = VALUES(score_home),
                    score_away      = VALUES(score_away),
                    status          = VALUES(status),
                    fetched_at      = NOW()
            """), {
                "sofa_event_id":  sofa_id,
                "home_name":      sofa_event.get("home"),
                "away_name":      sofa_event.get("away"),
                "league_name":    sofa_event.get("league"),
                "start_timestamp":sofa_event.get("ts"),
                "score_home":     sofa_event.get("score_home"),
                "score_away":     sofa_event.get("score_away"),
                "status":         sofa_event.get("status"),
            })
            # Update games FK
            conn.execute(
                text("UPDATE games SET sofa_event_id = :sofa_id WHERE id = :game_id"),
                {"sofa_id": sofa_id, "game_id": game_id}
            )
            # Upsert Sofasport team aliases using the DB game's canonical names
            home_canonical = next((g["home_team"] for g in all_db_games if g["id"] == game_id), None)
            away_canonical = next((g["away_team"] for g in all_db_games if g["id"] == game_id), None)
            for canonical, sofa_name in [
                (home_canonical, sofa_event.get("home")),
                (away_canonical, sofa_event.get("away")),
            ]:
                if canonical and sofa_name:
                    conn.execute(text("""
                        INSERT INTO team_aliases (canonical_name, company_name, company_team_name)
                        VALUES (:canonical, 'Sofasport', :sofa_name)
                        ON DUPLICATE KEY UPDATE company_team_name = company_team_name
                    """), {"canonical": canonical, "sofa_name": sofa_name})


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

def fetch_sofa_events(country: str, date: str) -> list[dict]:
    category_id = CATEGORY_MAP[country]
    url = f"https://{RAPIDAPI_HOST}/v1/events/schedule/category"
    params = urllib.parse.urlencode({"category_id": category_id, "date": date})
    req = urllib.request.Request(
        f"{url}?{params}",
        headers={"x-rapidapi-key": RAPIDAPI_KEY, "x-rapidapi-host": RAPIDAPI_HOST},
        method="GET"
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    return [
        {
            "id":         e["id"],
            "home":       e["homeTeam"]["name"],
            "away":       e["awayTeam"]["name"],
            "ts":         e["startTimestamp"],
            "score_home": e.get("homeScore", {}).get("current"),
            "score_away": e.get("awayScore", {}).get("current"),
            "status":     e.get("status", {}).get("description", ""),
            "league":     e["tournament"]["name"],
        }
        for e in data.get("data", [])
    ]


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------

def fuzzy_name_score(db_home: str, db_away: str, sofa_event: dict) -> float:
    h = fuzz.token_sort_ratio(db_home.lower(), sofa_event["home"].lower())
    a = fuzz.token_sort_ratio(db_away.lower(), sofa_event["away"].lower())
    return (h + a) / 2


def match_game(db_game: dict, sofa_events: list[dict]) -> tuple[dict | None, str, float]:
    db_epoch = calendar.timegm(db_game["date_time_starts_utc"].timetuple())
    window_secs = TIME_WINDOW_MINUTES * 60

    candidates = [e for e in sofa_events if abs(e["ts"] - db_epoch) <= window_secs]
    if not candidates:
        return None, "NO_TIME", 0.0

    sh, sa = db_game["score_home"], db_game["score_away"]
    if sh is not None and sa is not None:
        score_matches = [e for e in candidates if e["score_home"] == sh and e["score_away"] == sa]
        if len(score_matches) == 1:
            name_score = fuzzy_name_score(db_game["home_team"], db_game["away_team"], score_matches[0])
            if name_score >= SCORE_MATCH_THRESHOLD:
                return score_matches[0], "SCORE", 100.0
        if len(score_matches) > 1:
            best = max(score_matches, key=lambda e: fuzzy_name_score(db_game["home_team"], db_game["away_team"], e))
            score = fuzzy_name_score(db_game["home_team"], db_game["away_team"], best)
            if score >= SCORE_MATCH_THRESHOLD:
                return best, "SCORE+FUZZY", score

    best = max(candidates, key=lambda e: fuzzy_name_score(db_game["home_team"], db_game["away_team"], e))
    score = fuzzy_name_score(db_game["home_team"], db_game["away_team"], best)
    if score >= FUZZY_MATCH_THRESHOLD:
        return best, "FUZZY", score
    return best, "MISS", score


# ---------------------------------------------------------------------------
# Odds + Statistics fetchers
# ---------------------------------------------------------------------------

def fetch_sofa_odds(sofa_event_id: int) -> list[dict]:
    url = f"https://{RAPIDAPI_HOST}/v1/events/odds/all"
    params = urllib.parse.urlencode({
        "event_id": sofa_event_id,
        "provider_id": ODDS_PROVIDER_ID,
        "odds_format": "decimal",
    })
    req = urllib.request.Request(
        f"{url}?{params}",
        headers={"x-rapidapi-key": RAPIDAPI_KEY, "x-rapidapi-host": RAPIDAPI_HOST},
        method="GET"
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8")).get("data", [])


def fetch_sofa_statistics(sofa_event_id: int) -> list[dict]:
    url = f"https://{RAPIDAPI_HOST}/v1/events/statistics"
    params = urllib.parse.urlencode({"event_id": sofa_event_id})
    req = urllib.request.Request(
        f"{url}?{params}",
        headers={"x-rapidapi-key": RAPIDAPI_KEY, "x-rapidapi-host": RAPIDAPI_HOST},
        method="GET"
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8")).get("data", [])


SOFA_CALLS_DIR = Path("sofa_calls")


def save_json(subdir: str, filename: str, data: dict):
    """Save raw API response to sofa_calls/<subdir>/<filename>.json"""
    folder = SOFA_CALLS_DIR / subdir
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / filename
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return path


def store_odds(game_id: int, sofa_event_id: int, raw_odds: list[dict], date: str):
    """Save odds response as JSON under sofa_calls/<date>/odds/."""
    path = save_json(
        subdir=f"{date}/odds",
        filename=f"game_{game_id}_sofa_{sofa_event_id}.json",
        data={"game_id": game_id, "sofa_event_id": sofa_event_id, "fetched_at": datetime.utcnow().isoformat(), "data": raw_odds},
    )
    logger.info(f"      Saved odds → {path}")


# Mapping from Sofasport stat key to flat column names (home/away, and optional totals)
STAT_COLUMN_MAP = {
    "ballPossession":           ("ball_possession_home",       "ball_possession_away",       None, None),
    "expectedGoals":            ("expected_goals_home",        "expected_goals_away",        None, None),
    "totalShotsOnGoal":         ("total_shots_home",           "total_shots_away",           None, None),
    "goalkeeperSaves":          ("goalkeeper_saves_home",      "goalkeeper_saves_away",      None, None),
    "cornerKicks":              ("corner_kicks_home",          "corner_kicks_away",          None, None),
    "fouls":                    ("fouls_home",                 "fouls_away",                 None, None),
    "passes":                   ("passes_home",                "passes_away",                None, None),
    "totalTackle":              ("tackles_home",               "tackles_away",               None, None),
    "freeKicks":                ("free_kicks_home",            "free_kicks_away",            None, None),
    "yellowCards":              ("yellow_cards_home",          "yellow_cards_away",          None, None),
    "redCards":                 ("red_cards_home",             "red_cards_away",             None, None),
    "shotsOnGoal":              ("shots_on_target_home",       "shots_on_target_away",       None, None),
    "shotsOffGoal":             ("shots_off_target_home",      "shots_off_target_away",      None, None),
    "blockedScoringAttempt":    ("blocked_shots_home",         "blocked_shots_away",         None, None),
    "totalShotsInsideBox":      ("shots_inside_box_home",      "shots_inside_box_away",      None, None),
    "totalShotsOutsideBox":     ("shots_outside_box_home",     "shots_outside_box_away",     None, None),
    "hitWoodwork":              ("hit_woodwork_home",          "hit_woodwork_away",          None, None),
    "accurateThroughBall":      ("through_balls_home",         "through_balls_away",         None, None),
    "touchesInOppBox":          ("touches_in_opp_box_home",   "touches_in_opp_box_away",    None, None),
    "offsides":                 ("offsides_home",              "offsides_away",              None, None),
    "accuratePasses":           ("accurate_passes_home",       "accurate_passes_away",       None, None),
    "throwIns":                 ("throw_ins_home",             "throw_ins_away",             None, None),
    "accurateLongBalls":        ("long_balls_home",            "long_balls_away",            "long_balls_home_total",    "long_balls_away_total"),
    "accurateCross":            ("crosses_home",               "crosses_away",               "crosses_home_total",       "crosses_away_total"),
    "finalThirdPhaseStatistic": ("final_third_home",           "final_third_away",           "final_third_home_total",   "final_third_away_total"),
    "duelWonPercent":           ("duel_won_pct_home",          "duel_won_pct_away",          None, None),
    "dispossessed":             ("dispossessed_home",          "dispossessed_away",          None, None),
    "groundDuelsPercentage":    ("ground_duels_home",          "ground_duels_away",          "ground_duels_home_total",  "ground_duels_away_total"),
    "aerialDuelsPercentage":    ("aerial_duels_home",          "aerial_duels_away",          "aerial_duels_home_total",  "aerial_duels_away_total"),
    "dribblesPercentage":       ("dribbles_home",              "dribbles_away",              "dribbles_home_total",      "dribbles_away_total"),
    "interceptionWon":          ("interceptions_home",         "interceptions_away",         None, None),
    "totalClearance":           ("clearances_home",            "clearances_away",            None, None),
    "errorsLeadToShot":         ("errors_lead_to_shot_home",   "errors_lead_to_shot_away",   None, None),
    "goalKicks":                ("goal_kicks_home",            "goal_kicks_away",            None, None),
}


def _flatten_stats(raw_stats: list[dict]) -> dict[str, dict]:
    """
    Returns {period: {col: value}} — one flat dict per period.
    Deduplicates by (period, stat_key) — first occurrence wins.
    """
    by_period = {}
    seen = set()
    for period_block in raw_stats:
        period = period_block.get("period", "ALL")
        if period not in by_period:
            by_period[period] = {}
        for group in period_block.get("groups", []):
            for item in group.get("statisticsItems", []):
                key = item.get("key")
                dedup_key = (period, key)
                if dedup_key in seen or key not in STAT_COLUMN_MAP:
                    continue
                seen.add(dedup_key)
                h_col, a_col, ht_col, at_col = STAT_COLUMN_MAP[key]
                by_period[period][h_col] = item.get("homeValue")
                by_period[period][a_col] = item.get("awayValue")
                if ht_col:
                    by_period[period][ht_col] = item.get("homeTotal")
                    by_period[period][at_col] = item.get("awayTotal")
    return by_period


def store_statistics(game_id: int, sofa_event_id: int, raw_stats: list[dict], date: str):
    """Save raw JSON and return flattened stats per period."""
    path = save_json(
        subdir=f"{date}/statistics",
        filename=f"game_{game_id}_sofa_{sofa_event_id}.json",
        data={"game_id": game_id, "sofa_event_id": sofa_event_id, "fetched_at": datetime.utcnow().isoformat(), "data": raw_stats},
    )
    logger.info(f"      Saved statistics → {path}")
    return _flatten_stats(raw_stats)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(date: str, dry_run: bool, unmatched_only: bool, min_confidence: float, min_games: int):
    if not RAPIDAPI_KEY:
        raise ValueError("RAPIDAPI_KEY not set in .env")

    by_country = load_db_games(date, unmatched_only)

    # Split into countries we can call vs ones with no category mapping
    callable_countries  = {c: g for c, g in by_country.items() if c in CATEGORY_MAP}
    skipped_countries   = {c: g for c, g in by_country.items() if c not in CATEGORY_MAP}

    # Filter by minimum games per country
    below_threshold     = {c: g for c, g in callable_countries.items() if len(g) < min_games}
    callable_countries  = {c: g for c, g in callable_countries.items() if len(g) >= min_games}

    total_games = sum(len(g) for g in by_country.values())

    print()
    print(f"  Batch Sofasport Match — {date}")
    print(f"  {'='*65}")
    print(f"  Total games       : {total_games}")
    print(f"  Min games filter  : {min_games}")
    print(f"  Countries to call : {len(callable_countries)}")
    print(f"  Below threshold   : {len(below_threshold)}" + (f" {[(c, len(g)) for c, g in below_threshold.items()]}" if below_threshold else ""))
    print(f"  Skipped countries : {len(skipped_countries)}" + (f" {list(skipped_countries)}" if skipped_countries else ""))
    print(f"  Min confidence    : {min_confidence}")
    print(f"  Dry run           : {dry_run}")
    print()

    grand_matched = grand_missed = grand_skipped = 0
    all_to_write  = []   # (game_id, sofa_id, sofa_event_dict)
    all_misses    = []   # (game, method, confidence)

    for country, db_games in sorted(callable_countries.items()):
        print(f"  [{country}] {len(db_games)} game(s) — fetching...", end=" ", flush=True)

        try:
            sofa_events = fetch_sofa_events(country, date)
            print(f"{len(sofa_events)} sofa events")
        except Exception as e:
            print(f"API ERROR: {e}")
            grand_skipped += len(db_games)
            continue

        time.sleep(API_CALL_DELAY)

        matched = missed = 0
        for g in db_games:
            sofa, method, confidence = match_game(g, sofa_events)

            if method in ("NO_TIME", "MISS") or confidence < min_confidence:
                missed += 1
                grand_missed += 1
                all_misses.append((g, method, confidence))
                status = "✗"
            else:
                matched += 1
                grand_matched += 1
                all_to_write.append((g["id"], sofa["id"], sofa))
                status = "✓"

            db_label   = f"{g['home_team']} vs {g['away_team']}"
            sofa_label = f"{sofa['home']} vs {sofa['away']} (id={sofa['id']})" if sofa else "— NO MATCH —"
            print(f"    {status} [{g['id']:>5}] {method:<12} {confidence:>4.0f}  {db_label:<40} {sofa_label}")

        print(f"    → matched {matched}/{len(db_games)}")
        print()

    # ── Write sofa_event_ids to DB ────────────────────────────────────────────
    if all_to_write:
        all_db_games_flat = [g for games in by_country.values() for g in games]
        write_sofa_ids(all_to_write, dry_run, all_db_games_flat)
        action = "DRY RUN — would write" if dry_run else "Written"
        print(f"  {action} {len(all_to_write)} sofa_event_id(s) to DB")

    # ── Fetch odds + statistics per matched game ───────────────────────────────
    if all_to_write and not dry_run:
        print()
        print(f"  Fetching odds + statistics for {len(all_to_write)} matched game(s)...")
        for i, (game_id, sofa_id, _sofa_event) in enumerate(all_to_write, 1):
            try:
                raw_odds = fetch_sofa_odds(sofa_id)
                store_odds(game_id, sofa_id, raw_odds, date)
                time.sleep(API_CALL_DELAY)

                raw_stats = fetch_sofa_statistics(sofa_id)
                store_statistics(game_id, sofa_id, raw_stats, date)
                time.sleep(API_CALL_DELAY)

                n_stat_groups = sum(len(p.get("groups", [])) for p in raw_stats)
                print(f"    [{i}/{len(all_to_write)}] game_id={game_id} sofa_id={sofa_id} — {len(raw_odds)} odds markets, {n_stat_groups} stat groups")
            except Exception as e:
                logger.error(f"    [FAILED] game_id={game_id} sofa_id={sofa_id} — {e}")

    # ── Misses summary ────────────────────────────────────────────────────────
    if all_misses:
        print()
        print(f"  Unmatched games ({len(all_misses)}):")
        for g, method, confidence in all_misses:
            print(f"    [{g['id']:>5}] {method:<10} conf={confidence:>4.0f}  {g['home_team']} vs {g['away_team']} ({g['country']})")

    # ── Grand summary ─────────────────────────────────────────────────────────
    print()
    print(f"  {'='*65}")
    print(f"  Matched  : {grand_matched}")
    print(f"  Missed   : {grand_missed}")
    print(f"  Skipped  : {grand_skipped} (API errors)")
    if skipped_countries:
        print(f"  No category mapping: {list(skipped_countries.keys())}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Batch match DB games against Sofasport for a full date")
    parser.add_argument("--date",           required=True,                    help="Date (YYYY-MM-DD)")
    parser.add_argument("--dry-run",        action="store_true",              help="Match but don't write sofa_event_id to DB")
    parser.add_argument("--unmatched-only", action="store_true",              help="Skip games that already have a sofa_event_id")
    parser.add_argument("--min-confidence", type=float, default=55,           help="Minimum confidence to accept a match (default: 55)")
    parser.add_argument("--min-games",       type=int,   default=1,            help="Minimum games a country must have to trigger an API call (default: 1)")
    args = parser.parse_args()
    run(args.date, args.dry_run, args.unmatched_only, args.min_confidence, args.min_games)