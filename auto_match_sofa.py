"""
Automatic Sofasport matching — meant to run once a day from Task Scheduler.

Works forward one kickoff date at a time, starting after the last date it
completed, matching games and fetching odds/statistics/incidents
(batch_match_sofa.run with --unmatched-only). Stops when it reaches the
RapidAPI call limit for the billing cycle or catches up.

  - First run: starts at the latest date that already has matched games.
  - Never processes today, or the newest kickoff date in the DB (its games may
    still be arriving).
  - A date cut short by the call limit is not marked done; the next run resumes
    it, including details for games matched but not yet fetched.

Usage:
    python auto_match_sofa.py                     # run until caught up or out of calls
    python auto_match_sofa.py --plan              # show what would run; no API calls
    python auto_match_sofa.py --start 2026-09-10  # start from this date instead

Exit codes: 0 done or caught up, 3 another run holds the lock, 1 error.
"""
import argparse
import sys
from datetime import date, datetime, timedelta

from sqlalchemy import text

import batch_match_sofa as bms
from models import SofaMatchDate

LOCK_NAME = "pregames_auto_match"


def calls_used() -> int:
    return bms.get_cycle_call_count(bms.get_billing_cycle_start())


def date_window(conn, start_override: date | None) -> tuple[date | None, date | None, date | None]:
    """Return (last_completed, start, end) — start/end are None when there is nothing to do."""
    last_done = conn.execute(text("SELECT MAX(match_date) FROM sofa_match_dates")).scalar()
    latest_game = conn.execute(text("SELECT MAX(DATE(date_time_starts_utc)) FROM games")).scalar()

    if start_override:
        start = start_override
    elif last_done:
        start = last_done + timedelta(days=1)
    else:
        start = conn.execute(text(
            "SELECT MAX(DATE(date_time_starts_utc)) FROM games WHERE sofa_event_id IS NOT NULL"
        )).scalar()

    if start is None or latest_game is None:
        return last_done, None, None
    end = min(datetime.utcnow().date() - timedelta(days=1), latest_game - timedelta(days=1))
    return last_done, start, end


def plan_rows(conn, start: date, end: date) -> list[dict]:
    """Per kickoff date: games, games still to match (in callable countries), countries to call, max API calls."""
    rows = conn.execute(text("""
        SELECT DATE(date_time_starts_utc) AS d, country,
               COUNT(*) AS games, SUM(sofa_event_id IS NULL) AS unmatched
        FROM games
        WHERE DATE(date_time_starts_utc) BETWEEN :start AND :end
        GROUP BY d, country
    """), {"start": start, "end": end}).fetchall()

    per_date = {}
    for r in rows:
        games, unmatched, countries = per_date.get(r.d, (0, 0, 0))
        callable_unmatched = int(r.unmatched) if r.country in bms.CATEGORY_MAP else 0
        per_date[r.d] = (games + r.games, unmatched + callable_unmatched,
                         countries + (1 if callable_unmatched else 0))

    return [{"date": str(d), "games": games, "to_match": unmatched,
             "countries": countries, "max_calls": countries + 3 * unmatched}
            for d, (games, unmatched, countries) in sorted(per_date.items())]


def print_plan(conn, start: date, end: date):
    print(f"  {'date':<12}{'games':>7}{'to match':>10}{'countries':>11}{'max calls':>11}")
    total = 0
    for r in plan_rows(conn, start, end):
        total += r["max_calls"]
        print(f"  {r['date']:<12}{r['games']:>7}{r['to_match']:>10}{r['countries']:>11}{r['max_calls']:>11}")
    print(f"  {'':<12}{'':>7}{'':>10}{'total':>11}{total:>11}   (upper bound: assumes every game matches)")


def acquire_run_lock():
    """Hold a MySQL named lock for the whole run so only one matcher runs at a time
    (scheduled task, CLI or dashboard). Returns the connection holding it, or None if taken.
    MySQL releases the lock automatically if this process dies."""
    conn = bms.engine.connect()
    got = conn.execute(text("SELECT GET_LOCK(:n, 0)"), {"n": LOCK_NAME}).scalar()
    if got != 1:
        conn.close()
        return None
    return conn


def release_run_lock(conn) -> None:
    try:
        conn.execute(text("SELECT RELEASE_LOCK(:n)"), {"n": LOCK_NAME})
    finally:
        conn.close()


def main():
    # Scheduled runs log to a file; keep ✓/✗/→ from failing on Windows' default encoding.
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Match Sofasport games day by day until the RapidAPI call limit")
    parser.add_argument("--plan", action="store_true", help="Show which dates would be processed; make no API calls")
    parser.add_argument("--start", type=date.fromisoformat, help="Start from this date (YYYY-MM-DD) instead of after the last completed one")
    parser.add_argument("--min-confidence", type=float, default=55, help="Minimum confidence to accept a match (default: 55)")
    args = parser.parse_args()

    SofaMatchDate.__table__.create(bms.engine, checkfirst=True)

    with bms.engine.connect() as conn:
        last_done, start, end = date_window(conn, args.start)

        used = calls_used()
        print()
        print(f"  Auto Sofasport match — {datetime.utcnow():%Y-%m-%d %H:%M} UTC")
        print(f"  {'='*65}")
        print(f"  Last completed date  : {last_done or '—'}")
        print(f"  RapidAPI calls used  : {used} / {bms.MONTHLY_CALL_LIMIT} (cycle since {bms.get_billing_cycle_start().date()})")

        if start is None:
            print("  No matched games to continue from — pass --start YYYY-MM-DD.")
            return
        if end < start:
            print(f"  Nothing to do — caught up (next date {start} needs games on a later date first).")
            return
        print(f"  Dates to process     : {start} → {end}")
        print()
        print_plan(conn, start, end)

    if args.plan:
        return
    if used < 0:
        sys.exit("  Could not read api_call_log — refusing to call the API without a quota count.")

    lock = acquire_run_lock()
    if lock is None:
        print("  Another auto-match run is already in progress — exiting.")
        sys.exit(3)
    try:
        d = start
        while d <= end:
            used = calls_used()
            if used < 0:
                sys.exit("  Could not read api_call_log — stopping.")
            if used >= bms.MONTHLY_CALL_LIMIT:
                print(f"\n  Call limit reached ({used}/{bms.MONTHLY_CALL_LIMIT}) — will continue from {d} next cycle.")
                return

            result = bms.run(d.isoformat(), dry_run=False, unmatched_only=True,
                             min_confidence=args.min_confidence, min_games=1, report=True,
                             fetch_missing_details=True)
            if result["hit_limit"]:
                print(f"\n  Call limit reached during {d} — it will be resumed next cycle.")
                return

            with bms.engine.begin() as conn:
                conn.execute(text("""
                    INSERT INTO sofa_match_dates (match_date, matched, missed, completed_at)
                    VALUES (:d, :matched, :missed, :now)
                    ON DUPLICATE KEY UPDATE matched = VALUES(matched), missed = VALUES(missed),
                                            completed_at = VALUES(completed_at)
                """), {"d": d, "matched": result["matched"], "missed": result["missed"], "now": datetime.utcnow()})
            print(f"  ✓ {d} marked complete")
            d += timedelta(days=1)

        print(f"\n  Caught up to {end}. RapidAPI calls used: {calls_used()} / {bms.MONTHLY_CALL_LIMIT}")
    finally:
        release_run_lock(lock)


if __name__ == "__main__":
    main()
