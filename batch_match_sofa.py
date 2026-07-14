"""
Batch Sofasport Matching
Fetches all countries with unmatched games for a given date,
calls the Sofasport API once per country, fuzzy-matches, and
writes sofa_event_id back to the games table.

Usage:
    python batch_match_sofa.py --date 2026-05-12
    python batch_match_sofa.py --dates 2026-05-12 2026-05-13
    python batch_match_sofa.py --dates 2026-05-12,2026-05-13
    python batch_match_sofa.py --date 2026-05-12 --dry-run       # match but don't write
    python batch_match_sofa.py --date 2026-05-12 --unmatched-only # skip already matched
    python batch_match_sofa.py --date 2026-05-12 --min-confidence 70
    python batch_match_sofa.py --date 2026-05-12 --report        # save JSON report to reports/
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

# RapidAPI quota resets on the 18th of each month; stop calling once this many
# calls have been logged in the current cycle.
BILLING_CYCLE_DAY  = 18
MONTHLY_CALL_LIMIT = 9990

# Sofasport odds provider (1 = Bet365)
ODDS_PROVIDER_ID = int(os.getenv("ODDS_PROVIDER_ID", "1"))

CATEGORY_MAP = {
    "Afghanistan": 1084, "Albania": 257, "Algeria": 304, "Angola": 500,
    "Argentina": 48, "Armenia": 296, "Australia": 34, "Austria": 17,
    "Azerbaijan": 297, "Bahrain": 351, "Belarus": 91, "Belgium": 33,
    "Bolivia": 379, "Bosnia": 158, "Brazil": 13, "Bulgaria": 78,
    "Chile": 49, "China": 99, "Colombia": 274, "Costa Rica": 289,
    "Croatia": 14, "Cyprus": 102, "Czech Republic": 18, "Denmark": 8,
    "Ecuador": 165, "Egypt": 305, "England": 1, "Estonia": 92,
    "Europe": 1465, "Finland": 19, "France": 7, "Georgia": 270,
    "Germany": 30, "Ghana": 542, "Greece": 67, "Honduras": 437,
    "Hong Kong": 339, "Hungary": 11, "Iceland": 10, "India": 352,
    "Indonesia": 368, "Iran": 301, "Ireland": 51, "Israel": 66,
    "UEFA": 1465,
    "FIFA": 1468,
    "World": 1468,
    "Italy": 31, "Jamaica": 502, "Japan": 52, "Jordan": 329,
    "Kazakhstan": 278, "Kenya": 805, "Kosovo": 1112, "Kuwait": 331,
    "Latvia": 163, "Lebanon": 428, "Lithuania": 160, "Luxembourg": 197,
    "Malaysia": 85, "Malta": 134, "Mexico": 12, "Moldova": 279,
    "Montenegro": 386, "Morocco": 303, "Netherlands": 35, "New Zealand": 148,
    "Nicaragua": 1130, "Nigeria": 1132, "North & Central America": 1469,
    "North Macedonia": 159, "Northern Ireland": 130, "Norway": 5,
    "Oman": 415, "Panama": 526, "Paraguay": 280, "Peru": 20,
    "Philippines": 847, "Poland": 47, "Portugal": 44, "Qatar": 353,
    "Romania": 77, "Russia": 21, "Saudi Arabia": 310, "Scotland": 22,
    "Serbia": 152, "Singapore": 45, "Slovakia": 23, "Slovenia": 24,
    "South America": 1470, "South Korea": 291, "Spain": 32, "Sweden": 9,
    "Switzerland": 25, "Tanzania": 1151, "Thailand": 485, "Tunisia": 378,
    "Turkey": 46, "USA": 26, "Uganda": 1022, "Ukraine": 86,
    "Uruguay": 57, "Uzbekistan": 385, "Venezuela": 281, "Wales": 131,
    "Zambia": 1158,
}


# ---------------------------------------------------------------------------
# API call logging
# ---------------------------------------------------------------------------

def log_api_call(endpoint: str):
    """Log a single RapidAPI call to the api_call_log table."""
    try:
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO api_call_log (provider, endpoint, called_at)
                VALUES ('rapidapi', :endpoint, NOW())
            """), {"endpoint": endpoint})
    except Exception as e:
        logger.warning(f"Failed to log API call: {e}")


def save_report(date: str, report: dict):
    """Save match report to reports/<date>.json"""
    folder = Path("reports")
    folder.mkdir(exist_ok=True)
    path = folder / f"{date}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False, default=str)
    print(f"  Report saved → {path}")
    return path


def get_billing_cycle_start(reference: datetime = None) -> datetime:
    """
    RapidAPI quota resets on the 18th of each month. Returns the start
    (00:00 UTC) of the current cycle — the most recent 18th on or before
    `reference` (e.g. on 2026-07-06 this returns 2026-06-18).
    """
    reference = reference or datetime.utcnow()
    if reference.day >= BILLING_CYCLE_DAY:
        return reference.replace(day=BILLING_CYCLE_DAY, hour=0, minute=0, second=0, microsecond=0)
    year, month = reference.year, reference.month - 1
    if month == 0:
        month, year = 12, year - 1
    return reference.replace(year=year, month=month, day=BILLING_CYCLE_DAY, hour=0, minute=0, second=0, microsecond=0)


def get_cycle_call_count(cycle_start: datetime) -> int:
    """Return the number of RapidAPI calls logged since `cycle_start`."""
    try:
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT COUNT(*) FROM api_call_log
                WHERE provider = 'rapidapi' AND called_at >= :cycle_start
            """), {"cycle_start": cycle_start})
            return result.scalar() or 0
    except Exception as e:
        logger.warning(f"Failed to get cycle call count: {e}")
        return -1


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

    log_api_call(f"events/schedule/category/{country}")

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

def load_team_aliases() -> dict[str, str]:
    """
    Load confirmed DB-team-name -> Sofasport-name mappings from past matches,
    so recurring name mismatches (rebrands, translations, sponsor names)
    don't have to be re-solved by fuzzy text every run.
    """
    try:
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT canonical_name, company_team_name
                FROM team_aliases
                WHERE company_name = 'Sofasport'
            """)).fetchall()
        return {r.canonical_name: r.company_team_name for r in rows}
    except Exception as e:
        logger.warning(f"Failed to load team aliases: {e}")
        return {}


def fuzzy_name_score(db_home: str, db_away: str, sofa_event: dict, aliases: dict[str, str] | None = None) -> float:
    aliases = aliases or {}

    if aliases.get(db_home) == sofa_event["home"]:
        h = 100.0
    else:
        h = fuzz.token_sort_ratio(db_home.lower(), sofa_event["home"].lower())

    if aliases.get(db_away) == sofa_event["away"]:
        a = 100.0
    else:
        a = fuzz.token_sort_ratio(db_away.lower(), sofa_event["away"].lower())

    return (h + a) / 2


def score_pair(db_game: dict, sofa_event: dict, aliases: dict[str, str] | None = None) -> tuple[float, str]:
    """
    Return (confidence, method) for a single DB game vs sofa event pair,
    without committing to any assignment. Used to build the cost matrix.
    """
    db_epoch    = calendar.timegm(db_game["date_time_starts_utc"].timetuple())
    window_secs = TIME_WINDOW_MINUTES * 60

    if abs(sofa_event["ts"] - db_epoch) > window_secs:
        return 0.0, "NO_TIME"

    name_score = fuzzy_name_score(db_game["home_team"], db_game["away_team"], sofa_event, aliases)

    sh, sa = db_game["score_home"], db_game["score_away"]
    if sh is not None and sa is not None:
        if sofa_event["score_home"] == sh and sofa_event["score_away"] == sa:
            if name_score >= SCORE_MATCH_THRESHOLD:
                return 100.0, "SCORE"
            return name_score, "SCORE+FUZZY"

    if name_score >= FUZZY_MATCH_THRESHOLD:
        return name_score, "FUZZY"
    return name_score, "MISS"


def match_country_optimal(
    db_games: list[dict],
    sofa_events: list[dict],
    min_confidence: float,
    aliases: dict[str, str] | None = None,
) -> list[tuple[dict, dict | None, str, float]]:
    """
    Optimally assign DB games to sofa events using the Hungarian algorithm
    so that no two DB games claim the same sofa event and the total
    confidence across all assignments is maximised.

    Returns a list of (db_game, sofa_event_or_None, method, confidence)
    one entry per DB game.
    """
    import numpy as np
    from scipy.optimize import linear_sum_assignment

    n_db   = len(db_games)
    n_sofa = len(sofa_events)

    # Build score matrix  [n_db x n_sofa]
    score_matrix  = np.zeros((n_db, n_sofa))
    method_matrix = [["NO_TIME"] * n_sofa for _ in range(n_db)]

    for i, g in enumerate(db_games):
        for j, e in enumerate(sofa_events):
            conf, meth = score_pair(g, e, aliases)
            score_matrix[i, j]  = conf
            method_matrix[i][j] = meth

    # linear_sum_assignment minimises cost — negate to maximise
    row_ind, col_ind = linear_sum_assignment(-score_matrix)
    assigned_cols = dict(zip(row_ind.tolist(), col_ind.tolist()))

    results = []
    for i, g in enumerate(db_games):
        if i not in assigned_cols:
            # More DB games than sofa events — no candidate at all
            results.append((g, None, "NO_TIME", 0.0))
            continue

        j          = assigned_cols[i]
        confidence = float(score_matrix[i, j])
        method     = method_matrix[i][j]
        sofa       = sofa_events[j]

        if method == "NO_TIME" or confidence < min_confidence:
            results.append((g, sofa, "MISS" if method != "NO_TIME" else "NO_TIME", confidence))
        else:
            results.append((g, sofa, method, confidence))

    return results


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
        data = json.loads(resp.read().decode("utf-8"))

    log_api_call(f"events/odds/{sofa_event_id}")

    return data.get("data", [])


def fetch_sofa_statistics(sofa_event_id: int) -> list[dict]:
    url = f"https://{RAPIDAPI_HOST}/v1/events/statistics"
    params = urllib.parse.urlencode({"event_id": sofa_event_id})
    req = urllib.request.Request(
        f"{url}?{params}",
        headers={"x-rapidapi-key": RAPIDAPI_KEY, "x-rapidapi-host": RAPIDAPI_HOST},
        method="GET"
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    log_api_call(f"events/statistics/{sofa_event_id}")

    return data.get("data", [])


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

def run(date: str, dry_run: bool, unmatched_only: bool, min_confidence: float, min_games: int, report: bool = False):
    if not RAPIDAPI_KEY:
        raise ValueError("RAPIDAPI_KEY not set in .env")

    by_country = load_db_games(date, unmatched_only)
    aliases    = load_team_aliases()

    # Split into countries we can call vs ones with no category mapping
    callable_countries  = {c: g for c, g in by_country.items() if c in CATEGORY_MAP}
    skipped_countries   = {c: g for c, g in by_country.items() if c not in CATEGORY_MAP}

    # Filter by minimum games per country
    below_threshold     = {c: g for c, g in callable_countries.items() if len(g) < min_games}
    callable_countries  = {c: g for c, g in callable_countries.items() if len(g) >= min_games}

    total_games = sum(len(g) for g in by_country.values())

    # RapidAPI call count for the current billing cycle (18th → 18th) BEFORE this run
    cycle_start  = get_billing_cycle_start()
    calls_before = get_cycle_call_count(cycle_start)
    calls_used   = calls_before

    print()
    print(f"  Batch Sofasport Match — {date}")
    print(f"  {'='*65}")
    print(f"  Total games          : {total_games}")
    print(f"  Min games filter     : {min_games}")
    print(f"  Countries to call    : {len(callable_countries)}")
    print(f"  Below threshold      : {len(below_threshold)}" + (f" {[(c, len(g)) for c, g in below_threshold.items()]}" if below_threshold else ""))
    print(f"  Skipped countries    : {len(skipped_countries)}" + (f" {list(skipped_countries)}" if skipped_countries else ""))
    print(f"  Min confidence       : {min_confidence}")
    print(f"  Dry run              : {dry_run}")
    print(f"  RapidAPI calls (cycle since {cycle_start.date()}) : {calls_before} / {MONTHLY_CALL_LIMIT} (before this run)")
    print()

    if calls_before >= MONTHLY_CALL_LIMIT:
        print(f"  ABORTING — RapidAPI call limit reached ({calls_before}/{MONTHLY_CALL_LIMIT} since {cycle_start.date()}). No requests made.")
        return

    grand_matched = grand_missed = grand_skipped = 0
    all_to_write  = []   # (game_id, sofa_id, sofa_event_dict)
    all_misses    = []   # (game, method, confidence)
    report_rows         = []   # all games for the JSON report
    sofa_unmatched_rows = []   # sofa events that were never claimed by any DB game

    remaining_countries = sorted(callable_countries.items())
    for idx, (country, db_games) in enumerate(remaining_countries):
        if calls_used >= MONTHLY_CALL_LIMIT:
            not_run = remaining_countries[idx:]
            print(f"  RapidAPI call limit reached ({calls_used}/{MONTHLY_CALL_LIMIT}) — stopping, "
                  f"skipping {len(not_run)} remaining countr{'y' if len(not_run) == 1 else 'ies'}.")
            grand_skipped += sum(len(g) for _, g in not_run)
            break

        print(f"  [{country}] {len(db_games)} game(s) — fetching...", end=" ", flush=True)

        try:
            sofa_events = fetch_sofa_events(country, date)
            calls_used += 1
            print(f"{len(sofa_events)} sofa events")
        except Exception as e:
            print(f"API ERROR: {e}")
            grand_skipped += len(db_games)
            continue

        time.sleep(API_CALL_DELAY)

        matched = missed = 0
        matched_sofa_ids = set()
        assignments = match_country_optimal(db_games, sofa_events, min_confidence, aliases)

        for g, sofa, method, confidence in assignments:
            if method in ("NO_TIME", "MISS"):
                missed += 1
                grand_missed += 1
                all_misses.append((g, method, confidence))
                status = "✗"
            else:
                matched += 1
                grand_matched += 1
                matched_sofa_ids.add(sofa["id"])
                all_to_write.append((g["id"], sofa["id"], sofa))
                status = "✓"

            db_label   = f"{g['home_team']} vs {g['away_team']}"
            sofa_label = f"{sofa['home']} vs {sofa['away']} (id={sofa['id']})" if sofa else "— NO MATCH —"
            print(f"    {status} [{g['id']:>5}] {method:<12} {confidence:>4.0f}  {db_label:<40} {sofa_label}")

            report_rows.append({
                "game_id":        g["id"],
                "status":         "matched" if status == "✓" else "unmatched",
                "method":         method,
                "confidence":     round(confidence, 1),
                "country":        g["country"],
                "league":         g["league"],
                "db_home":        g["home_team"],
                "db_away":        g["away_team"],
                "db_kickoff_utc": str(g["date_time_starts_utc"]),
                "db_score":       f"{g['score_home']}-{g['score_away']}" if g["score_home"] is not None else None,
                "sofa_id":        sofa["id"]   if sofa else None,
                "sofa_home":      sofa["home"] if sofa else None,
                "sofa_away":      sofa["away"] if sofa else None,
                "sofa_score":     f"{sofa['score_home']}-{sofa['score_away']}" if sofa and sofa.get("score_home") is not None else None,
                "sofa_league":    sofa["league"] if sofa else None,
            })

        print(f"    → matched {matched}/{len(db_games)}")
        print()

        # Collect sofa events that no DB game claimed
        for e in sofa_events:
            if e["id"] not in matched_sofa_ids:
                sofa_unmatched_rows.append({
                    "sofa_id":     e["id"],
                    "country":     country,
                    "sofa_home":   e["home"],
                    "sofa_away":   e["away"],
                    "sofa_league": e["league"],
                    "sofa_score":  f"{e['score_home']}-{e['score_away']}" if e.get("score_home") is not None else None,
                    "sofa_status": e.get("status"),
                    "sofa_ts":     e["ts"],
                    "kickoff_utc": datetime.utcfromtimestamp(e["ts"]).isoformat() if e.get("ts") else None,
                })

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
            if calls_used + 2 > MONTHLY_CALL_LIMIT:
                skipped_odds_stats = len(all_to_write) - i + 1
                print(f"  RapidAPI call limit reached ({calls_used}/{MONTHLY_CALL_LIMIT}) — stopping, "
                      f"skipping odds/statistics for {skipped_odds_stats} remaining game(s).")
                break

            try:
                raw_odds = fetch_sofa_odds(sofa_id)
                calls_used += 1
                store_odds(game_id, sofa_id, raw_odds, date)
                time.sleep(API_CALL_DELAY)

                raw_stats = fetch_sofa_statistics(sofa_id)
                calls_used += 1
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
    calls_after    = get_cycle_call_count(cycle_start)
    calls_this_run = calls_after - calls_before if calls_before >= 0 else "N/A"

    print()
    print(f"  {'='*65}")
    print(f"  Matched  : {grand_matched}")
    print(f"  Missed   : {grand_missed}")
    print(f"  Skipped  : {grand_skipped} (API errors / call-limit stop)")
    if skipped_countries:
        print(f"  No category mapping : {list(skipped_countries.keys())}")
    print(f"  {'='*65}")
    print(f"  RapidAPI calls this run              : {calls_this_run}")
    print(f"  RapidAPI calls (cycle since {cycle_start.date()}) : {calls_after} / {MONTHLY_CALL_LIMIT}")
    print()

    # ── Save JSON report ──────────────────────────────────────────────────────
    if report:
        report_data = {
            "date":              date,
            "generated_at":      datetime.utcnow().isoformat(),
            "dry_run":           dry_run,
            "min_confidence":    min_confidence,
            "summary": {
                "total_games":           grand_matched + grand_missed + grand_skipped,
                "matched":               grand_matched,
                "unmatched":             grand_missed,
                "skipped":               grand_skipped,
                "match_rate_pct":        round(grand_matched / (grand_matched + grand_missed) * 100, 1)
                                         if (grand_matched + grand_missed) > 0 else 0,
                "sofa_events_unmatched": len(sofa_unmatched_rows),
                "rapidapi_calls_this_run":   calls_this_run,
                "rapidapi_calls_this_cycle": calls_after,
                "rapidapi_cycle_start":      str(cycle_start.date()),
            },
            "matched":   [r for r in report_rows if r["status"] == "matched"],
            "unmatched": [r for r in report_rows if r["status"] == "unmatched"],
            "sofa_unmatched": sofa_unmatched_rows,
            "skipped_countries": list(skipped_countries.keys()),
        }
        save_report(date, report_data)


def parse_dates(date: str | None, dates: list[str] | None) -> list[str]:
    """Normalize one or many date inputs into a validated YYYY-MM-DD list."""
    raw_inputs = []
    if date:
        raw_inputs.append(date)
    if dates:
        raw_inputs.extend(dates)

    normalized = []
    for item in raw_inputs:
        for token in item.split(","):
            d = token.strip()
            if not d:
                continue
            try:
                datetime.strptime(d, "%Y-%m-%d")
            except ValueError as exc:
                raise ValueError(f"Invalid date '{d}'. Expected format: YYYY-MM-DD") from exc
            normalized.append(d)

    # Preserve user order while avoiding duplicate runs.
    return list(dict.fromkeys(normalized))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Batch match DB games against Sofasport for a full date")
    date_group = parser.add_mutually_exclusive_group(required=True)
    date_group.add_argument("--date",                                          help="Single date (YYYY-MM-DD)")
    date_group.add_argument("--dates", nargs="+",                             help="One or many dates; supports spaces or comma-separated values")
    parser.add_argument("--dry-run",        action="store_true",              help="Match but don't write sofa_event_id to DB")
    parser.add_argument("--unmatched-only", action="store_true",              help="Skip games that already have a sofa_event_id")
    parser.add_argument("--min-confidence", type=float, default=55,           help="Minimum confidence to accept a match (default: 55)")
    parser.add_argument("--min-games",       type=int,   default=1,            help="Minimum games a country must have to trigger an API call (default: 1)")
    parser.add_argument("--report",          action="store_true",              help="Save a JSON match report to reports/<date>.json")
    args = parser.parse_args()

    dates_to_run = parse_dates(args.date, args.dates)
    if not dates_to_run:
        raise ValueError("No valid dates provided.")

    for i, run_date in enumerate(dates_to_run, 1):
        if len(dates_to_run) > 1:
            print(f"\n[{i}/{len(dates_to_run)}] Processing {run_date}")
        run(run_date, args.dry_run, args.unmatched_only, args.min_confidence, args.min_games, args.report)