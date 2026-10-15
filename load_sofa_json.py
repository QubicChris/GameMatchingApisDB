"""
Load saved sofa_calls JSON files into the database.

Reads statistics, odds and incidents JSON files from sofa_calls/<date>/ and
writes them into sofa_statistics, sofa_odds and sofa_incidents. Each game's
rows are replaced, so re-running is safe.

The write_* functions are also used by batch_match_sofa.py to store fresh
API responses.

Usage:
    # Load a specific date
    python load_sofa_json.py --date 2026-05-12

    # Load every date folder under sofa_calls/
    python load_sofa_json.py --all

    # Load a specific folder
    python load_sofa_json.py --folder sofa_calls/2026-05-12

    # Preview only — don't write to DB
    python load_sofa_json.py --all --dry-run
"""
import argparse
import json
import logging
import os
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "mysql+pymysql://user:password@localhost:3306/pregames")
engine = create_engine(DATABASE_URL)

SOFA_CALLS_DIR = Path("sofa_calls")

# ---------------------------------------------------------------------------
# Stat column mapping
# ---------------------------------------------------------------------------
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
    """Returns {period: {col: value}} — deduplicated by (period, stat_key)."""
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


def _bool_to_int(v):
    return None if v is None else int(bool(v))


def _flatten_incidents(raw_incidents: list[dict]) -> list[dict]:
    """Flatten raw /events/incidents JSON into rows matching the sofa_incidents columns."""
    rows = []
    for item in raw_incidents:
        player     = item.get("player") or {}
        manager    = item.get("manager") or {}
        assist     = item.get("assist1") or {}
        player_in  = item.get("playerIn") or {}
        player_out = item.get("playerOut") or {}

        rows.append({
            "sofa_incident_id":     item.get("id"),
            "incident_type":        item.get("incidentType"),
            "incident_class":       item.get("incidentClass"),
            "time":                 item.get("time"),
            "added_time":           item.get("addedTime"),
            "reversed_period_time": item.get("reversedPeriodTime"),
            "is_home":              _bool_to_int(item.get("isHome")),
            "home_score":           item.get("homeScore"),
            "away_score":           item.get("awayScore"),
            "player_id":            player.get("id"),
            "player_name":          player.get("name"),
            "assist_player_id":     assist.get("id"),
            "assist_player_name":   assist.get("name"),
            "player_in_id":         player_in.get("id"),
            "player_in_name":       player_in.get("name"),
            "player_out_id":        player_out.get("id"),
            "player_out_name":      player_out.get("name"),
            "reason":               item.get("reason"),
            "rescinded":            _bool_to_int(item.get("rescinded")),
            "confirmed":            _bool_to_int(item.get("confirmed")),
            "injury":               _bool_to_int(item.get("injury")),
            "manager_id":           manager.get("id"),
            "manager_name":         manager.get("name"),
            "text":                 item.get("text"),
            "length":               item.get("length"),
        })
    return rows


def incident_fallback_key_exists(conn) -> bool:
    """The old uq_sofa_incident_fallback key makes same-minute incidents overwrite each other."""
    return bool(conn.execute(text("""
        SELECT COUNT(*) FROM information_schema.statistics
        WHERE table_schema = DATABASE()
          AND table_name = 'sofa_incidents'
          AND index_name = 'uq_sofa_incident_fallback'
    """)).scalar())


# ---------------------------------------------------------------------------
# Writers — replace one game's rows inside the caller's transaction
# ---------------------------------------------------------------------------

def write_statistics(conn, game_id: int, sofa_event_id: int, raw_stats: list[dict]) -> list[str]:
    """Replace a game's sofa_statistics rows. Returns the periods written."""
    by_period = _flatten_stats(raw_stats)
    if not by_period:
        return []

    conn.execute(text("DELETE FROM sofa_statistics WHERE game_id = :gid"), {"gid": game_id})
    for period, cols in by_period.items():
        cols["game_id"] = game_id
        cols["sofa_event_id"] = sofa_event_id
        cols["period"] = period
        col_names = ", ".join(cols.keys())
        placeholders = ", ".join(f":{k}" for k in cols.keys())
        conn.execute(text(f"INSERT INTO sofa_statistics ({col_names}) VALUES ({placeholders})"), cols)
    return list(by_period)


def write_odds(conn, game_id: int, sofa_event_id: int, raw_odds: list[dict]) -> int:
    """Replace a game's sofa_odds rows. Returns the number of markets written."""
    rows = []
    for market in raw_odds:
        for choice in market.get("choices", []):
            winning = choice.get("winning")
            rows.append({
                "game_id":        game_id,
                "sofa_event_id":  sofa_event_id,
                "market_id":      market.get("marketId"),
                "market_name":    market.get("marketName"),
                "market_group":   market.get("marketGroup"),
                "market_period":  market.get("marketPeriod"),
                "choice_group":   market.get("choiceGroup"),
                "outcome":        choice.get("name"),
                "odd":            choice.get("fractionalValue"),
                "initial_odd":    choice.get("initialFractionalValue"),
                "winning":        1 if winning is True else (0 if winning is False else None),
                "change":         choice.get("change"),
            })
    if not rows:
        return 0

    conn.execute(text("DELETE FROM sofa_odds WHERE game_id = :gid"), {"gid": game_id})
    conn.execute(text("""
        INSERT INTO sofa_odds
            (game_id, sofa_event_id, market_id, market_name, market_group,
             market_period, choice_group, outcome, odd, initial_odd, winning, `change`)
        VALUES
            (:game_id, :sofa_event_id, :market_id, :market_name, :market_group,
             :market_period, :choice_group, :outcome, :odd, :initial_odd, :winning, :change)
    """), rows)
    return len(raw_odds)


def write_incidents(conn, game_id: int, sofa_event_id: int, raw_incidents: list[dict]) -> int:
    """Replace an event's sofa_incidents rows. Returns the number of rows written."""
    rows = _flatten_incidents(raw_incidents)
    if not rows:
        return 0

    # Every VALUES entry must be a placeholder: pymysql's executemany regex backtracks for
    # ~20-50s per call on a literal like CURRENT_TIMESTAMP before falling back to row-by-row.
    fetched_at = datetime.utcnow()
    for row in rows:
        row["game_id"] = game_id
        row["sofa_event_id"] = sofa_event_id
        row["fetched_at"] = fetched_at

    conn.execute(text("DELETE FROM sofa_incidents WHERE sofa_event_id = :sid"), {"sid": sofa_event_id})
    conn.execute(text("""
        INSERT INTO sofa_incidents (
            game_id, sofa_event_id, sofa_incident_id, incident_type, incident_class,
            time, added_time, reversed_period_time, is_home,
            home_score, away_score,
            player_id, player_name, assist_player_id, assist_player_name,
            player_in_id, player_in_name, player_out_id, player_out_name,
            reason, rescinded, confirmed, injury,
            manager_id, manager_name, text, length, fetched_at
        ) VALUES (
            :game_id, :sofa_event_id, :sofa_incident_id, :incident_type, :incident_class,
            :time, :added_time, :reversed_period_time, :is_home,
            :home_score, :away_score,
            :player_id, :player_name, :assist_player_id, :assist_player_name,
            :player_in_id, :player_in_name, :player_out_id, :player_out_name,
            :reason, :rescinded, :confirmed, :injury,
            :manager_id, :manager_name, :text, :length, :fetched_at
        )
    """), rows)
    return len(rows)


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

def load_statistics_file(path: Path, dry_run: bool) -> bool:
    with open(path, encoding="utf-8") as f:
        d = json.load(f)

    game_id = d["game_id"]
    sofa_event_id = d["sofa_event_id"]

    if dry_run:
        for period, cols in _flatten_stats(d["data"]).items():
            logger.info(f"  [DRY RUN] game={game_id} sofa={sofa_event_id} period={period} cols={len(cols)}")
        return True

    with engine.begin() as conn:
        periods = write_statistics(conn, game_id, sofa_event_id, d["data"])
    if not periods:
        logger.warning(f"  No stats found in {path.name}")
        return False

    logger.info(f"  ✓ statistics game={game_id} sofa={sofa_event_id} periods={periods}")
    return True


def load_odds_file(path: Path, dry_run: bool) -> bool:
    with open(path, encoding="utf-8") as f:
        d = json.load(f)

    game_id = d["game_id"]
    sofa_event_id = d["sofa_event_id"]

    if not d["data"]:
        logger.warning(f"  No odds found in {path.name}")
        return False

    if dry_run:
        logger.info(f"  [DRY RUN] game={game_id} sofa={sofa_event_id} markets={len(d['data'])}")
        return True

    with engine.begin() as conn:
        n_markets = write_odds(conn, game_id, sofa_event_id, d["data"])

    logger.info(f"  ✓ odds game={game_id} sofa={sofa_event_id} markets={n_markets}")
    return True


def load_incidents_file(path: Path, dry_run: bool) -> bool:
    with open(path, encoding="utf-8") as f:
        d = json.load(f)

    game_id = d["game_id"]
    sofa_event_id = d["sofa_event_id"]

    if not d["data"]:
        logger.warning(f"  No incidents found in {path.name}")
        return False

    if dry_run:
        logger.info(f"  [DRY RUN] game={game_id} sofa={sofa_event_id} incidents={len(d['data'])}")
        return True

    with engine.begin() as conn:
        n_rows = write_incidents(conn, game_id, sofa_event_id, d["data"])

    logger.info(f"  ✓ incidents game={game_id} sofa={sofa_event_id} rows={n_rows}")
    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

LOADERS = [
    ("statistics", load_statistics_file),
    ("odds",       load_odds_file),
    ("incidents",  load_incidents_file),
]


def run(folders: list[Path], dry_run: bool):
    files = {
        kind: [f for folder in folders for f in sorted((folder / kind).glob("*.json"))]
        for kind, _ in LOADERS
    }

    print()
    print(f"  Load Sofa JSONs — {folders[0] if len(folders) == 1 else f'{len(folders)} folders'}")
    print(f"  {'='*50}")
    for kind, _ in LOADERS:
        print(f"  {kind.capitalize() + ' files':<17}: {len(files[kind])}")
    print(f"  Dry run          : {dry_run}")
    print()

    if files["incidents"] and not dry_run:
        with engine.connect() as conn:
            if incident_fallback_key_exists(conn):
                raise SystemExit("sofa_incidents still has the old uq_sofa_incident_fallback key — "
                                 "run `python migrate_incident_key.py` first.")

    ok = failed = 0
    for kind, loader in LOADERS:
        if not files[kind]:
            continue
        print(f"\n  {kind.capitalize()}:")
        for f in files[kind]:
            try:
                loader(f, dry_run)
                ok += 1
            except Exception as e:
                logger.error(f"  ✗ {f} — {e}")
                failed += 1

    print()
    print(f"  {'='*50}")
    print(f"  OK: {ok}  |  Failed: {failed}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Load saved sofa_calls JSON files into the DB")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--date",    help="Date folder under sofa_calls/ (YYYY-MM-DD)")
    source.add_argument("--folder",  help="Explicit path to folder containing odds/, statistics/ and incidents/")
    source.add_argument("--all",     action="store_true", help="Every date folder under sofa_calls/")
    parser.add_argument("--dry-run", action="store_true", help="Preview only, don't write to DB")
    args = parser.parse_args()

    if args.all:
        folders = sorted(p for p in SOFA_CALLS_DIR.iterdir() if p.is_dir()) if SOFA_CALLS_DIR.exists() else []
    elif args.folder:
        folders = [Path(args.folder)]
    else:
        folders = [SOFA_CALLS_DIR / args.date]

    missing = [f for f in folders if not f.exists()]
    if not folders or missing:
        raise SystemExit(f"Folder not found: {missing[0] if missing else SOFA_CALLS_DIR}")

    run(folders, args.dry_run)
