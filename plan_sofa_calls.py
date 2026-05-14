"""
Sofasport Call Planner
Queries the DB for a given date and prints all the API calls
that need to be made to fetch Sofasport events — without executing them.

Usage:
    python plan_sofa_calls.py --date 2026-04-28
    python plan_sofa_calls.py --date 2026-04-28 --unmatched-only
"""
import argparse
import os
from collections import defaultdict
from datetime import datetime
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "mysql+pymysql://user:password@localhost:3306/pregames")
engine = create_engine(DATABASE_URL)

# Country → Sofasport category_id
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

BASE_URL = "https://sofasport.p.rapidapi.com/v1/events/schedule/category"


def plan(target_date: str, unmatched_only: bool = False):
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
            GROUP BY g.id, g.home_team, g.away_team, g.league,
                     g.country, g.date_time_starts_utc, g.sofa_event_id
            ORDER BY g.date_time_starts_utc
        """), {"date": target_date}).fetchall()

    if not rows:
        print(f"No games found for {target_date}")
        return

    # Filter to unmatched only if requested
    games = [dict(r._mapping) for r in rows]
    if unmatched_only:
        games = [g for g in games if not g["sofa_event_id"]]

    # Group by country
    by_country = defaultdict(list)
    no_category = []
    for g in games:
        country = g["country"] or ""
        if country in CATEGORY_MAP:
            by_country[country].append(g)
        else:
            no_category.append(g)

    # ── Summary ───────────────────────────────────────────────────────────────
    total_games    = len(games)
    already_matched = sum(1 for g in games if g["sofa_event_id"])
    need_matching  = total_games - already_matched
    total_calls    = len(by_country)

    print(f"")
    print(f"  Sofasport Call Plan — {target_date}")
    print(f"  {'='*50}")
    print(f"  Total games in DB     : {total_games}")
    print(f"  Already have sofa_id  : {already_matched}")
    print(f"  Need matching         : {need_matching}")
    print(f"  API calls required    : {total_calls}")
    print(f"  No category mapping   : {len(no_category)}")
    print()

    # ── API calls ─────────────────────────────────────────────────────────────
    print(f"  {'CALL':<4} {'COUNTRY':<30} {'CAT_ID':<8} {'GAMES':<6} URL")
    print(f"  {'-'*100}")

    for i, (country, country_games) in enumerate(sorted(by_country.items()), 1):
        cat_id = CATEGORY_MAP[country]
        url = f"{BASE_URL}?category_id={cat_id}&date={target_date}"
        unmatched_count = sum(1 for g in country_games if not g["sofa_event_id"])
        matched_count   = len(country_games) - unmatched_count
        flag = f"({matched_count} already matched)" if matched_count > 0 else ""
        print(f"  {i:<4} {country:<30} {cat_id:<8} {len(country_games):<6} {url} {flag}")

    # ── Games per country ─────────────────────────────────────────────────────
    print()
    print(f"  Games per country:")
    print(f"  {'-'*100}")
    for country, country_games in sorted(by_country.items()):
        print(f"\n  [{country}]")
        for g in country_games:
            time_str = g["date_time_starts_utc"].strftime("%H:%M")
            score    = f"{g['score_home']}-{g['score_away']}" if g["score_home"] is not None else "?-?"
            sofa_id  = f"sofa_id={g['sofa_event_id']}" if g["sofa_event_id"] else "NOT MATCHED"
            print(f"    [{g['id']:>5}] {time_str} | {score:>5} | {g['home_team']} vs {g['away_team']} | {sofa_id}")

    # ── No category mapping ───────────────────────────────────────────────────
    if no_category:
        print()
        print(f"  Games with no category mapping (will be skipped):")
        print(f"  {'-'*60}")
        for g in no_category:
            print(f"    [{g['id']:>5}] country={g['country']!r} | {g['home_team']} vs {g['away_team']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Plan Sofasport API calls for a given date")
    parser.add_argument("--date", required=True, help="Date to plan (YYYY-MM-DD)")
    parser.add_argument("--unmatched-only", action="store_true", help="Only show games without a sofa_event_id")
    args = parser.parse_args()
    plan(args.date, unmatched_only=args.unmatched_only)