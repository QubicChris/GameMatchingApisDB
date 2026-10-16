"""
Insert (or remove) ONE clearly-marked fake game in the DEV database, so the
statistics, incidents and blown-leads screens have something to show.

Usage:
    python seed_dev_data.py --confirm-dev-db
    python seed_dev_data.py --remove --confirm-dev-db

Refuses to run without --confirm-dev-db, and refuses if `games` has more than
1000 rows (that looks like production, where DATABASE_URL also says localhost).
"""
import argparse
import sys
from datetime import datetime, timedelta

from sqlalchemy import text

from database import engine

SEED_SOFA_EVENT_ID = 990000001
SEED_LEAGUE = "DEV SEED League"
SEED_COUNTRY = "Devland"
HOME, AWAY = "Seed United", "Sample City"
MAX_GAMES = 1000

COMPANIES = [("Pinnacle", 0.00), ("Fair888", 0.05), ("Stoiximan", -0.05)]

# period -> {stat_name: (home, away)}  (stat_name maps to <name>_home / <name>_away)
STATS = {
    "ALL": {
        "ball_possession": (55, 45), "expected_goals": (1.82, 1.45), "total_shots": (14, 11),
        "shots_on_target": (6, 5), "corner_kicks": (7, 4), "fouls": (11, 13),
        "yellow_cards": (1, 2), "passes": (480, 410), "accurate_passes": (410, 340),
        "long_balls": (35, 30), "tackles": (16, 18), "interceptions": (9, 11), "goal_kicks": (6, 8),
    },
    "1ST": {
        "ball_possession": (58, 42), "expected_goals": (1.10, 0.52), "total_shots": (8, 4),
        "shots_on_target": (4, 1), "corner_kicks": (4, 1), "fouls": (5, 6),
        "yellow_cards": (0, 1), "passes": (250, 190), "accurate_passes": (215, 160),
        "long_balls": (18, 14), "tackles": (8, 9), "interceptions": (4, 5), "goal_kicks": (3, 4),
    },
    "2ND": {
        "ball_possession": (52, 48), "expected_goals": (0.72, 0.93), "total_shots": (6, 7),
        "shots_on_target": (2, 4), "corner_kicks": (3, 3), "fouls": (6, 7),
        "yellow_cards": (1, 1), "passes": (230, 220), "accurate_passes": (195, 180),
        "long_balls": (17, 16), "tackles": (8, 9), "interceptions": (5, 6), "goal_kicks": (3, 4),
    },
}
LONG_BALL_TOTALS = {"ALL": (52, 48), "1ST": (27, 22), "2ND": (25, 26)}


def _kickoff(conn) -> datetime:
    d = conn.execute(text("SELECT MAX(DATE(date_time_starts_utc)) FROM games")).scalar()
    base = datetime(d.year, d.month, d.day) if d else datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    return base + timedelta(hours=15)


def _guard(conn) -> None:
    n = conn.execute(text("SELECT COUNT(*) FROM games")).scalar()
    if n > MAX_GAMES:
        print(f"games has {n} rows — this looks like a production DB. Refusing.")
        sys.exit(2)


def _seed_game_id(conn):
    return conn.execute(
        text("SELECT id FROM games WHERE sofa_event_id = :s"), {"s": SEED_SOFA_EVENT_ID}
    ).scalar()


def insert_seed() -> None:
    with engine.begin() as conn:
        existing = _seed_game_id(conn)
        if existing:
            print(f"Seed already present (game id {existing})")
            return
        kickoff = _kickoff(conn)
        conn.execute(text(
            "INSERT INTO sofa_games (sofa_event_id, home_name, away_name, league_name, start_timestamp, "
            "score_home, score_away, status, fetched_at) VALUES "
            "(:e, :h, :a, :l, :ts, 2, 2, 'Ended', NOW())"
        ), {"e": SEED_SOFA_EVENT_ID, "h": HOME, "a": AWAY, "l": SEED_LEAGUE,
            "ts": int(kickoff.timestamp())})
        res = conn.execute(text(
            "INSERT INTO games (date_time_starts_utc, home_team, away_team, league, country, sofa_event_id, created_at) "
            "VALUES (:k, :h, :a, :l, :c, :e, NOW())"
        ), {"k": kickoff, "h": HOME, "a": AWAY, "l": SEED_LEAGUE, "c": SEED_COUNTRY, "e": SEED_SOFA_EVENT_ID})
        game_id = res.lastrowid

        for company, delta in COMPANIES:
            cg = conn.execute(text(
                "INSERT INTO company_games (game_id, company_name, home_team, away_team, league, score_home, score_away, created_at) "
                "VALUES (:g, :c, :h, :a, :l, 2, 2, NOW())"
            ), {"g": game_id, "c": company, "h": HOME, "a": AWAY, "l": SEED_LEAGUE}).lastrowid

            def market(umid, selections):
                pm = conn.execute(text(
                    "INSERT INTO pregame_markets (company_game_id, market_id, umid, created_at) "
                    "VALUES (:cg, :m, :u, NOW())"
                ), {"cg": cg, "m": f"seed-{umid}", "u": umid}).lastrowid
                for outcome, line, odd in selections:
                    conn.execute(text(
                        "INSERT INTO selections (market_id, selection_id, canonical_outcome, line_value, raw_outcome, odd, created_at) "
                        "VALUES (:m, :sid, :o, :lv, :ro, :odd, NOW())"
                    ), {"m": pm, "sid": f"seed-{umid}-{outcome}", "o": outcome, "lv": line,
                        "ro": outcome, "odd": round(odd + delta, 2)})

            market(1, [("home", None, 2.10), ("draw", None, 3.40), ("away", None, 3.30)])
            market(50, [("over", 2.5, 1.90), ("under", 2.5, 1.95)])

        conn.execute(text(
            "INSERT IGNORE INTO market_types (umid, canonical_name, first_seen_at, last_updated_at) "
            "VALUES (1,'Match Result',NOW(),NOW()), (50,'Match Goals',NOW(),NOW())"
        ))

        odds = [
            (1, "Full time", "1X2", None, "1", 2.05, 0), (1, "Full time", "1X2", None, "X", 3.30, 1),
            (1, "Full time", "1X2", None, "2", 3.40, 0),
            (9, "Match goals", "Match goals", "2.5", "Over", 1.88, 1),
            (9, "Match goals", "Match goals", "2.5", "Under", 1.97, 0),
        ]
        for mid, mname, mgroup, cg_, outcome, odd, win in odds:
            conn.execute(text(
                "INSERT INTO sofa_odds (game_id, sofa_event_id, market_id, market_name, market_group, market_period, "
                "choice_group, outcome, odd, initial_odd, winning, `change`, fetched_at) "
                "VALUES (:g, :e, :m, :mn, :mg, 'Full-time', :cg, :o, :odd, :odd, :w, 0, NOW())"
            ), {"g": game_id, "e": SEED_SOFA_EVENT_ID, "m": mid, "mn": mname, "mg": mgroup,
                "cg": cg_, "o": outcome, "odd": odd, "w": win})

        for period, stats in STATS.items():
            row = {}
            for name, (h, a) in stats.items():
                row[f"{name}_home"] = h
                row[f"{name}_away"] = a
            row["long_balls_home_total"], row["long_balls_away_total"] = LONG_BALL_TOTALS[period]
            cols = ["game_id", "sofa_event_id", "period"] + list(row)
            conn.execute(text(
                f"INSERT INTO sofa_statistics ({', '.join(cols)}, fetched_at) "
                f"VALUES ({', '.join(':' + c for c in cols)}, NOW())"
            ), {"game_id": game_id, "sofa_event_id": SEED_SOFA_EVENT_ID, "period": period, **row})

        # (inc_id, type, class, time, added, rev, is_home, hs, as, extra)
        incidents = [
            (990000101, "goal", "regular", 12, None, 33, 1, 1, 0, {"player_name": "A. Striker", "assist_player_name": "B. Winger"}),
            (990000102, "goal", "regular", 30, None, 15, 1, 2, 0, {"player_name": "A. Striker"}),
            (990000103, "card", "yellow", 38, None, 7, 0, None, None, {"player_name": "C. Defender", "reason": "Foul"}),
            (990000104, "injuryTime", None, 45, 0, None, None, None, None, {"length": 2}),
            (990000105, "period", None, 45, 999, None, None, 2, 0, {"text": "HT"}),
            (990000106, "substitution", "regular", 60, None, 30, 1, None, None,
             {"player_in_name": "D. Sub", "player_out_name": "E. Tired", "injury": 0}),
            (990000107, "goal", "regular", 70, None, 20, 0, 2, 1, {"player_name": "F. Forward"}),
            (990000108, "varDecision", "goalAwarded", 85, None, 5, 0, None, None, {"confirmed": 1}),
            (990000109, "goal", "regular", 90, 3, 0, 0, 2, 2, {"player_name": "F. Forward"}),
            (990000110, "period", None, 90, 999, None, None, 2, 2, {"text": "FT"}),
        ]
        for iid, itype, iclass, t, added, rev, is_home, hs, as_, extra in incidents:
            row = {"game_id": game_id, "sofa_event_id": SEED_SOFA_EVENT_ID, "sofa_incident_id": iid,
                   "incident_type": itype, "incident_class": iclass, "time": t, "added_time": added,
                   "reversed_period_time": rev, "is_home": is_home, "home_score": hs, "away_score": as_, **extra}
            cols = list(row)
            conn.execute(text(
                f"INSERT INTO sofa_incidents ({', '.join('`' + c + '`' for c in cols)}, fetched_at) "
                f"VALUES ({', '.join(':' + c for c in cols)}, NOW())"
            ), row)

        print(f"Seeded game id {game_id}")


def remove_seed() -> None:
    with engine.begin() as conn:
        gid = _seed_game_id(conn)
        e = {"e": SEED_SOFA_EVENT_ID}
        if gid:
            g = {"g": gid}
            conn.execute(text(
                "DELETE s FROM selections s JOIN pregame_markets pm ON pm.id = s.market_id "
                "JOIN company_games cg ON cg.id = pm.company_game_id WHERE cg.game_id = :g"), g)
            conn.execute(text(
                "DELETE pm FROM pregame_markets pm JOIN company_games cg ON cg.id = pm.company_game_id "
                "WHERE cg.game_id = :g"), g)
            conn.execute(text("DELETE FROM company_games WHERE game_id = :g"), g)
        conn.execute(text("DELETE FROM sofa_odds WHERE sofa_event_id = :e"), e)
        conn.execute(text("DELETE FROM sofa_statistics WHERE sofa_event_id = :e"), e)
        conn.execute(text("DELETE FROM sofa_incidents WHERE sofa_event_id = :e"), e)
        conn.execute(text("DELETE FROM games WHERE sofa_event_id = :e"), e)
        conn.execute(text("DELETE FROM sofa_games WHERE sofa_event_id = :e"), e)
        print(f"Seed removed (game id {gid})" if gid else "No seed game found; cleaned any stray seed rows")


def main() -> None:
    ap = argparse.ArgumentParser(description="Insert or remove one fake game in the DEV database.")
    ap.add_argument("--confirm-dev-db", action="store_true", help="required: acknowledge this is a dev DB")
    ap.add_argument("--remove", action="store_true", help="delete the seed game instead of inserting it")
    args = ap.parse_args()
    if not args.confirm_dev_db:
        print("Refusing: pass --confirm-dev-db to confirm DATABASE_URL points at a DEV database.")
        sys.exit(2)
    with engine.connect() as conn:
        _guard(conn)
    if args.remove:
        remove_seed()
    else:
        insert_seed()


if __name__ == "__main__":
    main()
