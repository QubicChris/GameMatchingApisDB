"""
DB Integrity & Sanity Tests
Run: python test_db.py

Tests:
  1.  Duplicate company_games (same bookmaker twice for same game)
  2.  Duplicate pregame_markets (same market twice for same company_game)
  3.  Duplicate selections (same outcome twice in same market)
  4.  Markets with no selections
  5.  Company games with no markets
  6.  Games with no company games
  7.  Selections with NULL odd (might be ok, just flagged)
  8.  Selections with NULL canonical_outcome
  9.  Unknown umids (not in market_types)
  10. Market types with NULL canonical_name
  11. Selections with invalid line_value for O/U markets (negative)
  12. Match Result markets (umid=1) should have exactly 3 selections (home/draw/away)
  13. Over/Under markets should always have both over and under
  14. Asian Handicap markets should have both home and away
  15. Score sanity (score_home or score_away negative)
"""

import os
import logging
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

logging.basicConfig(level=logging.WARNING)

DATABASE_URL = os.getenv("DATABASE_URL", "mysql+pymysql://user:password@localhost:3306/pregames")
engine = create_engine(DATABASE_URL)

PASS  = "✓ PASS"
FAIL  = "✗ FAIL"
WARN  = "⚠ WARN"

results = []

def run(label, sql, params=None, expect_zero=True, warn_only=False):
    with engine.connect() as conn:
        rows = conn.execute(text(sql), params or {}).fetchall()
        count = len(rows)
        if expect_zero:
            status = PASS if count == 0 else (WARN if warn_only else FAIL)
        else:
            status = PASS  # informational only
        results.append((status, label, count, rows[:5]))
    return rows


print("=" * 70)
print("  Pregames DB Integrity Tests")
print("=" * 70)

# ── 1. Duplicate company_games ────────────────────────────────────────────
run("Duplicate company_games (same bookmaker per game)", """
    SELECT game_id, company_name, COUNT(*) AS cnt
    FROM company_games
    GROUP BY game_id, company_name
    HAVING COUNT(*) > 1
    LIMIT 20
""")

# ── 2. Duplicate pregame_markets ──────────────────────────────────────────
run("Duplicate pregame_markets (same market_id per company_game)", """
    SELECT company_game_id, market_id, COUNT(*) AS cnt
    FROM pregame_markets
    GROUP BY company_game_id, market_id
    HAVING COUNT(*) > 1
    LIMIT 20
""")

# ── 3. Duplicate selections ───────────────────────────────────────────────
run("Duplicate selections (same outcome+line in same market)", """
    SELECT market_id, canonical_outcome, line_value, COUNT(*) AS cnt
    FROM selections
    GROUP BY market_id, canonical_outcome, line_value
    HAVING COUNT(*) > 1
    LIMIT 20
""")

# ── 4. Markets with no selections ─────────────────────────────────────────
run("Markets with no selections", """
    SELECT pm.id, pm.umid, pm.company_game_id
    FROM pregame_markets pm
    LEFT JOIN selections s ON s.market_id = pm.id
    WHERE s.id IS NULL
    LIMIT 20
""")

# ── 5. Company games with no markets ──────────────────────────────────────
run("Company games with no markets", """
    SELECT cg.id, cg.company_name, cg.game_id
    FROM company_games cg
    LEFT JOIN pregame_markets pm ON pm.company_game_id = cg.id
    WHERE pm.id IS NULL
    LIMIT 20
""")

# ── 6. Games with no company games ────────────────────────────────────────
run("Games with no company games", """
    SELECT g.id, g.home_team, g.away_team
    FROM games g
    LEFT JOIN company_games cg ON cg.game_id = g.id
    WHERE cg.id IS NULL
    LIMIT 20
""")

# ── 7. Selections with NULL odd ───────────────────────────────────────────
run("Selections with NULL odd", """
    SELECT COUNT(*) AS cnt
    FROM selections
    WHERE odd IS NULL
    LIMIT 1
""", expect_zero=False, warn_only=True)

# ── 8. Selections with NULL canonical_outcome ─────────────────────────────
run("Selections with NULL canonical_outcome", """
    SELECT pm.umid, mt.canonical_name, cg.company_name, COUNT(*) AS cnt
    FROM selections s
    JOIN pregame_markets pm ON pm.id = s.market_id
    JOIN company_games cg ON cg.id = pm.company_game_id
    LEFT JOIN market_types mt ON mt.umid = pm.umid
    WHERE s.canonical_outcome IS NULL
    GROUP BY pm.umid, mt.canonical_name, cg.company_name
    ORDER BY cnt DESC
    LIMIT 10
""", warn_only=True)

# ── 9. Unknown umids not in market_types ──────────────────────────────────
run("Unknown umids (not in market_types)", """
    SELECT DISTINCT pm.umid, COUNT(*) as cnt
    FROM pregame_markets pm
    LEFT JOIN market_types mt ON mt.umid = pm.umid
    WHERE mt.umid IS NULL
    GROUP BY pm.umid
    ORDER BY cnt DESC
    LIMIT 20
""", warn_only=True)

# ── 10. Market types with NULL canonical_name ─────────────────────────────
run("Market types with NULL canonical_name", """
    SELECT umid FROM market_types
    WHERE canonical_name IS NULL
    LIMIT 20
""", warn_only=True)

# ── 11. O/U markets with negative line_value ─────────────────────────────
run("Over/Under selections with negative line_value", """
    SELECT s.id, s.canonical_outcome, s.line_value, pm.umid
    FROM selections s
    JOIN pregame_markets pm ON pm.id = s.market_id
    WHERE pm.umid IN (50, 51, 54, 55, 58, 13, 60)
      AND s.line_value < 0
    LIMIT 20
""")

# ── 12. Match Result (umid=1) should have 3 selections ───────────────────
run("Match Result markets without exactly 3 selections", """
    SELECT pm.id, pm.company_game_id, COUNT(s.id) AS sel_count
    FROM pregame_markets pm
    JOIN selections s ON s.market_id = pm.id
    WHERE pm.umid = 1
    GROUP BY pm.id, pm.company_game_id
    HAVING COUNT(s.id) != 3
    LIMIT 20
""", warn_only=True)

# ── 13. O/U markets missing over or under ─────────────────────────────────
run("Over/Under markets missing over OR under side", """
    SELECT pm.id, pm.umid, s.line_value,
           SUM(CASE WHEN s.canonical_outcome = 'over'  THEN 1 ELSE 0 END) AS has_over,
           SUM(CASE WHEN s.canonical_outcome = 'under' THEN 1 ELSE 0 END) AS has_under
    FROM pregame_markets pm
    JOIN selections s ON s.market_id = pm.id
    WHERE pm.umid IN (50, 51, 54, 55, 13, 60)
      AND s.canonical_outcome IN ('over', 'under')
    GROUP BY pm.id, pm.umid, s.line_value
    HAVING has_over = 0 OR has_under = 0
    LIMIT 20
""", warn_only=True)

# ── 14. Asian Handicap missing home or away ───────────────────────────────
run("Asian Handicap lines missing home OR away side", """
    SELECT pm.id, pm.umid, s.line_value,
           SUM(CASE WHEN s.canonical_outcome = 'home' THEN 1 ELSE 0 END) AS has_home,
           SUM(CASE WHEN s.canonical_outcome = 'away' THEN 1 ELSE 0 END) AS has_away
    FROM pregame_markets pm
    JOIN selections s ON s.market_id = pm.id
    WHERE pm.umid IN (53, 16)
      AND s.canonical_outcome IN ('home', 'away')
    GROUP BY pm.id, pm.umid, s.line_value
    HAVING has_home = 0 OR has_away = 0
    LIMIT 20
""", warn_only=True)

# ── 15. Negative scores ───────────────────────────────────────────────────
run("Company games with negative scores", """
    SELECT id, company_name, game_id, score_home, score_away
    FROM company_games
    WHERE score_home < 0 OR score_away < 0
    LIMIT 20
""")


# ── 16. Score disagreement across bookmakers for same game ────────────────
run("Score disagreement between bookmakers for same game", """
    SELECT
        g.id AS game_id,
        g.home_team,
        g.away_team,
        cg.company_name,
        cg.score_home,
        cg.score_away
    FROM company_games cg
    JOIN games g ON g.id = cg.game_id
    WHERE cg.score_home IS NOT NULL
      AND cg.score_away IS NOT NULL
      AND (
          cg.score_home != (
              SELECT MAX(cg2.score_home)
              FROM company_games cg2
              WHERE cg2.game_id = cg.game_id
                AND cg2.score_home IS NOT NULL
          )
          OR
          cg.score_away != (
              SELECT MAX(cg2.score_away)
              FROM company_games cg2
              WHERE cg2.game_id = cg.game_id
                AND cg2.score_away IS NOT NULL
          )
      )
    ORDER BY g.id
    LIMIT 20
""", warn_only=True)

# ── 17. Corners disagreement across bookmakers for same game ──────────────
run("Corners disagreement between bookmakers for same game", """
    SELECT
        g.id AS game_id,
        g.home_team,
        g.away_team,
        cg.company_name,
        cg.corners_home,
        cg.corners_away
    FROM company_games cg
    JOIN games g ON g.id = cg.game_id
    WHERE cg.corners_home IS NOT NULL
      AND cg.corners_away IS NOT NULL
      AND (
          cg.corners_home != (
              SELECT MAX(cg2.corners_home)
              FROM company_games cg2
              WHERE cg2.game_id = cg.game_id
                AND cg2.corners_home IS NOT NULL
          )
          OR
          cg.corners_away != (
              SELECT MAX(cg2.corners_away)
              FROM company_games cg2
              WHERE cg2.game_id = cg.game_id
                AND cg2.corners_away IS NOT NULL
          )
      )
    ORDER BY g.id
    LIMIT 20
""", warn_only=True)

# ── Summary ───────────────────────────────────────────────────────────────
print()
print(f"{'Test':<55} {'Status':<8} {'Issues'}")
print("-" * 75)

total_fail = total_warn = total_pass = 0
for status, label, count, sample_rows in results:
    if status == PASS:
        print(f"  {label:<53} {status}")
        total_pass += 1
    elif status == WARN:
        print(f"  {label:<53} {status}  ({count} rows)")
        if sample_rows and count > 0:
            for row in sample_rows[:3]:
                print(f"      → {dict(row._mapping)}")
        total_warn += 1
    else:
        print(f"  {label:<53} {status}  ({count} rows)")
        for row in sample_rows[:3]:
            print(f"      → {dict(row._mapping)}")
        total_fail += 1

print()
print("=" * 70)
print(f"  PASSED: {total_pass}  |  WARNINGS: {total_warn}  |  FAILED: {total_fail}")
print("=" * 70)

if total_fail == 0 and total_warn == 0:
    print("  All checks passed. DB looks clean.")
elif total_fail == 0:
    print("  No critical issues. Review warnings above.")
else:
    print("  Critical issues found. Review failures above.")