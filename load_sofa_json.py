"""
Load saved sofa_calls JSON files into the database.

Reads statistics and odds JSON files from sofa_calls/<date>/ and
inserts them into sofa_statistics and sofa_odds tables.

Usage:
    # Load a specific date
    python load_sofa_jsons.py --date 2026-05-12

    # Load a specific folder (overrides date)
    python load_sofa_jsons.py --folder sofa_calls/2026-05-12

    # Preview only — don't write to DB
    python load_sofa_jsons.py --date 2026-05-12 --dry-run
"""
import argparse
import json
import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "mysql+pymysql://user:password@localhost:3306/pregames")
engine = create_engine(DATABASE_URL)

# ---------------------------------------------------------------------------
# Stat column mapping (same as batch_match_sofa.py)
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


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

def load_statistics_file(path: Path, dry_run: bool) -> bool:
    with open(path) as f:
        d = json.load(f)

    game_id = d["game_id"]
    sofa_event_id = d["sofa_event_id"]
    raw_stats = d["data"]

    by_period = _flatten_stats(raw_stats)
    if not by_period:
        logger.warning(f"  No stats found in {path.name}")
        return False

    if dry_run:
        for period, cols in by_period.items():
            logger.info(f"  [DRY RUN] game={game_id} sofa={sofa_event_id} period={period} cols={len(cols)}")
        return True

    with engine.begin() as conn:
        conn.execute(text("DELETE FROM sofa_statistics WHERE game_id = :gid"), {"gid": game_id})
        for period, cols in by_period.items():
            cols["game_id"] = game_id
            cols["sofa_event_id"] = sofa_event_id
            cols["period"] = period
            col_names = ", ".join(cols.keys())
            placeholders = ", ".join(f":{k}" for k in cols.keys())
            conn.execute(text(f"INSERT INTO sofa_statistics ({col_names}) VALUES ({placeholders})"), cols)

    logger.info(f"  ✓ statistics game={game_id} sofa={sofa_event_id} periods={list(by_period.keys())}")
    return True


def load_odds_file(path: Path, dry_run: bool) -> bool:
    with open(path) as f:
        d = json.load(f)

    game_id = d["game_id"]
    sofa_event_id = d["sofa_event_id"]
    raw_odds = d["data"]

    if not raw_odds:
        logger.warning(f"  No odds found in {path.name}")
        return False

    if dry_run:
        logger.info(f"  [DRY RUN] game={game_id} sofa={sofa_event_id} markets={len(raw_odds)}")
        return True

    with engine.begin() as conn:
        conn.execute(text("DELETE FROM sofa_odds WHERE game_id = :gid"), {"gid": game_id})
        for market in raw_odds:
            for choice in market.get("choices", []):
                winning = choice.get("winning")
                conn.execute(text("""
                    INSERT INTO sofa_odds
                        (game_id, sofa_event_id, market_id, market_name, market_group,
                         market_period, choice_group, outcome, odd, initial_odd, winning, `change`)
                    VALUES
                        (:game_id, :sofa_event_id, :market_id, :market_name, :market_group,
                         :market_period, :choice_group, :outcome, :odd, :initial_odd, :winning, :change)
                """), {
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

    logger.info(f"  ✓ odds game={game_id} sofa={sofa_event_id} markets={len(raw_odds)}")
    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(folder: Path, dry_run: bool):
    stats_dir = folder / "statistics"
    odds_dir  = folder / "odds"

    stats_files = sorted(stats_dir.glob("*.json")) if stats_dir.exists() else []
    odds_files  = sorted(odds_dir.glob("*.json"))  if odds_dir.exists()  else []

    print()
    print(f"  Load Sofa JSONs — {folder}")
    print(f"  {'='*50}")
    print(f"  Statistics files : {len(stats_files)}")
    print(f"  Odds files       : {len(odds_files)}")
    print(f"  Dry run          : {dry_run}")
    print()

    ok = failed = 0

    if stats_files:
        print("  Statistics:")
        for f in stats_files:
            try:
                load_statistics_file(f, dry_run)
                ok += 1
            except Exception as e:
                logger.error(f"  ✗ {f.name} — {e}")
                failed += 1

    if odds_files:
        print("\n  Odds:")
        for f in odds_files:
            try:
                load_odds_file(f, dry_run)
                ok += 1
            except Exception as e:
                logger.error(f"  ✗ {f.name} — {e}")
                failed += 1

    print()
    print(f"  {'='*50}")
    print(f"  OK: {ok}  |  Failed: {failed}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Load saved sofa_calls JSON files into the DB")
    parser.add_argument("--date",    help="Date folder under sofa_calls/ (YYYY-MM-DD)")
    parser.add_argument("--folder",  help="Explicit path to folder containing odds/ and statistics/")
    parser.add_argument("--dry-run", action="store_true", help="Preview only, don't write to DB")
    args = parser.parse_args()

    if args.folder:
        folder = Path(args.folder)
    elif args.date:
        folder = Path("sofa_calls") / args.date
    else:
        parser.error("Provide --date or --folder")

    if not folder.exists():
        raise SystemExit(f"Folder not found: {folder}")

    run(folder, args.dry_run)