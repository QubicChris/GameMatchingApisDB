"""
Read queries for the dashboard API. SQL ported from the Streamlit dashboard
(dashboard.py); each function returns plain JSON-ready Python data.
"""
from datetime import date as _date, datetime
from decimal import Decimal

from sqlalchemy import text

from database import engine


def _clean(v):
    if isinstance(v, Decimal):
        return int(v) if v == v.to_integral_value() else float(v)
    if isinstance(v, (datetime, _date)):
        return v.isoformat()
    return v


def _rows(conn, sql: str, params: dict | None = None) -> list[dict]:
    return [{k: _clean(v) for k, v in r.items()} for r in conn.execute(text(sql), params or {}).mappings()]


def _iso(d):
    return d.isoformat() if d else None


# ── Summary ──────────────────────────────────────────────────────────────────

def load_summary() -> dict:
    with engine.connect() as conn:
        total     = conn.execute(text("SELECT COUNT(*) FROM games")).scalar()
        matched   = conn.execute(text("SELECT COUNT(*) FROM games WHERE sofa_event_id IS NOT NULL")).scalar()
        countries = conn.execute(text("SELECT COUNT(DISTINCT country) FROM games")).scalar()
        bookers   = conn.execute(text("SELECT COUNT(DISTINCT company_name) FROM company_games")).scalar()
        dates     = conn.execute(text("SELECT MIN(DATE(date_time_starts_utc)), MAX(DATE(date_time_starts_utc)) FROM games")).fetchone()
    total = int(total or 0)
    matched = int(matched or 0)
    return {
        "total_games": total,
        "matched": matched,
        "unmatched": total - matched,
        "match_pct": round(matched / total * 100, 1) if total else 0.0,
        "countries": int(countries or 0),
        "bookmakers": int(bookers or 0),
        "date_from": _iso(dates[0]),
        "date_to": _iso(dates[1]),
    }


def load_api_quota() -> dict:
    import batch_match_sofa as bms  # lazy: module has import-time side effects

    start = bms.get_billing_cycle_start()
    used = bms.get_cycle_call_count(start)
    return {
        "api_calls_used": None if used < 0 else used,
        "api_call_limit": bms.MONTHLY_CALL_LIMIT,
        "api_cycle_start": start.strftime("%Y-%m-%d") if start else None,
    }


def load_daily_counts(days: int) -> list[dict]:
    sql = """
        SELECT DATE(date_time_starts_utc) AS d, COUNT(*) AS total,
               SUM(CASE WHEN sofa_event_id IS NOT NULL THEN 1 ELSE 0 END) AS matched
        FROM games
        GROUP BY d
        ORDER BY d DESC
        LIMIT :days
    """
    with engine.connect() as conn:
        rows = _rows(conn, sql, {"days": days})
    return [{"date": r["d"], "total": r["total"], "matched": r["matched"]} for r in reversed(rows)]


def load_filters() -> dict:
    with engine.connect() as conn:
        dates = conn.execute(text(
            "SELECT DISTINCT DATE(date_time_starts_utc) AS d FROM games ORDER BY d DESC"
        )).fetchall()
        countries = conn.execute(text(
            "SELECT DISTINCT country FROM games WHERE country IS NOT NULL ORDER BY country"
        )).fetchall()
        bookmakers = conn.execute(text(
            "SELECT DISTINCT company_name FROM company_games ORDER BY company_name"
        )).fetchall()
    return {
        "dates": [str(r[0]) for r in dates if r[0] is not None],
        "countries": [r[0] for r in countries],
        "bookmakers": [r[0] for r in bookmakers],
    }


# ── Games ────────────────────────────────────────────────────────────────────

def load_games(date, country, sofa, q) -> list[dict]:
    sql = """
        SELECT
            g.id,
            g.date_time_starts_utc AS kickoff,
            g.home_team,
            g.away_team,
            g.league,
            g.country,
            g.sofa_event_id,
            COUNT(DISTINCT cg.company_name) AS bookmakers,
            MAX(cg.score_home)              AS score_home,
            MAX(cg.score_away)              AS score_away
        FROM games g
        LEFT JOIN company_games cg ON cg.game_id = g.id
        WHERE 1=1
    """
    params: dict = {}
    if date:
        sql += " AND DATE(g.date_time_starts_utc) = :date"
        params["date"] = date
    if country:
        sql += " AND g.country = :country"
        params["country"] = country
    if sofa == "matched":
        sql += " AND g.sofa_event_id IS NOT NULL"
    elif sofa == "unmatched":
        sql += " AND g.sofa_event_id IS NULL"
    if q:
        sql += " AND (g.home_team LIKE :q OR g.away_team LIKE :q OR g.league LIKE :q)"
        params["q"] = f"%{q}%"
    sql += """
        GROUP BY g.id, g.date_time_starts_utc, g.home_team, g.away_team, g.league,
                 g.country, g.sofa_event_id
    """
    if date:
        sql += " ORDER BY g.date_time_starts_utc"
    else:
        sql += " ORDER BY g.date_time_starts_utc DESC LIMIT 200"
    with engine.connect() as conn:
        return _rows(conn, sql, params)


def load_game(game_id: int) -> dict | None:
    sql = """
        SELECT g.id, g.date_time_starts_utc AS kickoff, g.home_team, g.away_team, g.league, g.country,
               g.sofa_event_id, sg.status AS sofa_status,
               MAX(cg.score_home) AS score_home, MAX(cg.score_away) AS score_away
        FROM games g
        LEFT JOIN company_games cg ON cg.game_id = g.id
        LEFT JOIN sofa_games sg ON sg.sofa_event_id = g.sofa_event_id
        WHERE g.id = :game_id
        GROUP BY g.id, g.date_time_starts_utc, g.home_team, g.away_team, g.league, g.country, g.sofa_event_id, sg.status
    """
    with engine.connect() as conn:
        row = conn.execute(text(sql), {"game_id": game_id}).mappings().first()
        if row is None:
            return None
        books = conn.execute(text(
            "SELECT company_name FROM company_games WHERE game_id = :game_id ORDER BY company_name"
        ), {"game_id": game_id}).fetchall()
    game = {k: _clean(v) for k, v in row.items()}
    game["_kickoff_dt"] = row["kickoff"]
    game["bookmakers"] = [b[0] for b in books]
    return game


# ── Odds ─────────────────────────────────────────────────────────────────────

_ODDS_SQL = """
    SELECT pm.umid, mt.canonical_name AS market_name,
           COALESCE(s.canonical_outcome, s.raw_outcome) AS outcome,
           s.line_value, cg.company_name,
           MAX(s.odd) AS odd, MAX(so.odd) AS sofa_close, MAX(so.winning) AS sofa_winning
    FROM games g
    JOIN company_games cg ON cg.game_id = g.id
    JOIN pregame_markets pm ON pm.company_game_id = cg.id
    JOIN market_types mt ON mt.umid = pm.umid
    JOIN selections s ON s.market_id = pm.id
    LEFT JOIN sofa_odds so ON so.game_id = g.id
        AND so.market_id = CASE pm.umid
            WHEN 1  THEN 1  WHEN 2  THEN 2  WHEN 4  THEN 3
            WHEN 6  THEN 4  WHEN 3  THEN 5  WHEN 50 THEN 9
            WHEN 53 THEN 17 WHEN 58 THEN 20 WHEN 55 THEN 21
        END
        AND CASE LOWER(so.outcome)
            WHEN '1'     THEN 'home'  WHEN '2'     THEN 'away'
            WHEN 'x'     THEN 'draw'  WHEN 'yes'   THEN 'yes'
            WHEN 'no'    THEN 'no'    WHEN '1x'    THEN '1x'
            WHEN 'x2'    THEN 'x2'    WHEN '12'    THEN '12'
            WHEN 'over'  THEN 'over'  WHEN 'under' THEN 'under'
            ELSE LOWER(so.outcome)
        END COLLATE utf8mb4_unicode_ci = s.canonical_outcome COLLATE utf8mb4_unicode_ci
        AND (so.choice_group COLLATE utf8mb4_unicode_ci = CAST(s.line_value AS CHAR)
             OR (so.choice_group IS NULL AND s.line_value IS NULL))
    WHERE g.id = :game_id
    GROUP BY pm.umid, mt.canonical_name, COALESCE(s.canonical_outcome, s.raw_outcome), s.line_value, cg.company_name
    ORDER BY pm.umid, s.line_value,
        MIN(CASE COALESCE(s.canonical_outcome, s.raw_outcome)  WHEN 'home' THEN 1 WHEN 'draw' THEN 2 WHEN 'away' THEN 3
                      WHEN 'yes' THEN 1 WHEN 'no' THEN 2 WHEN 'over' THEN 1 WHEN 'under' THEN 2
                      WHEN '1x' THEN 1 WHEN 'x2' THEN 2 WHEN '12' THEN 3 ELSE 4 END),
        COALESCE(s.canonical_outcome, s.raw_outcome), cg.company_name
"""


def _outcome_label(outcome, line_value) -> str:
    if outcome is None:
        return "—"
    if line_value is None:
        return str(outcome)
    return f"{outcome} {line_value:g}"


def pivot_odds(rows: list[dict]) -> dict:
    bookmakers = sorted({r["company_name"] for r in rows})
    markets: dict = {}          # umid -> market dict, insertion-ordered
    for r in rows:
        m = markets.setdefault(r["umid"], {
            "umid": r["umid"],
            "name": r["market_name"] or f"Market {r['umid']}",
            "rows": {},
        })
        key = (r["outcome"], r["line_value"])
        row = m["rows"].setdefault(key, {
            "outcome": r["outcome"],
            "line_value": r["line_value"],
            "label": _outcome_label(r["outcome"], r["line_value"]),
            "odds": {b: None for b in bookmakers},
            "sofa_close": None,
            "sofa_winning": None,
        })
        row["odds"][r["company_name"]] = r["odd"]
        if r["sofa_close"] is not None:
            row["sofa_close"] = r["sofa_close"]
        if r["sofa_winning"] is not None:
            row["sofa_winning"] = r["sofa_winning"]
    return {
        "bookmakers": bookmakers,
        "markets": [{**m, "rows": list(m["rows"].values())} for m in markets.values()],
    }


def load_odds(game_id: int) -> dict:
    with engine.connect() as conn:
        rows = _rows(conn, _ODDS_SQL, {"game_id": game_id})
    return pivot_odds(rows)


# ── Statistics / incidents ───────────────────────────────────────────────────

_STAT_DROP = {"id", "game_id", "sofa_event_id", "period", "fetched_at"}
_PERIOD_ORDER = {"ALL": 0, "1ST": 1, "2ND": 2}


def load_statistics(game_id: int) -> dict:
    with engine.connect() as conn:
        rows = _rows(conn, "SELECT * FROM sofa_statistics WHERE game_id = :gid", {"gid": game_id})
    stats = {r["period"]: {k: v for k, v in r.items() if k not in _STAT_DROP} for r in rows}
    periods = sorted(stats, key=lambda p: (_PERIOD_ORDER.get(p, 3), p))
    return {"periods": periods, "stats": stats}


def load_incidents(game_id: int) -> list[dict]:
    sql = """
        SELECT
            incident_type, incident_class, time, added_time, reversed_period_time,
            is_home, home_score, away_score,
            player_name, assist_player_name, player_in_name, player_out_name,
            reason, rescinded, confirmed, injury,
            manager_name, text, length
        FROM sofa_incidents
        WHERE game_id = :game_id
        ORDER BY time, added_time, id
    """
    with engine.connect() as conn:
        return _rows(conn, sql, {"game_id": game_id})


# ── Reference data ───────────────────────────────────────────────────────────

def load_aliases(q: str = "") -> dict:
    sql = """
        SELECT canonical_name, company_name, company_team_name
        FROM team_aliases
    """
    params: dict = {}
    if q:
        sql += """
        WHERE canonical_name IN (
            SELECT canonical_name FROM (
                SELECT DISTINCT canonical_name FROM team_aliases
                WHERE canonical_name LIKE :s OR company_team_name LIKE :s
            ) m
        )
        """
        params["s"] = f"%{q}%"
    sql += " ORDER BY canonical_name, company_name"
    with engine.connect() as conn:
        flat = _rows(conn, sql, params)
    sources = sorted({r["company_name"] for r in flat})
    grouped: dict = {}
    for r in flat:
        grouped.setdefault(r["canonical_name"], {})[r["company_name"]] = r["company_team_name"]
    return {
        "sources": sources,
        "rows": [{"canonical_name": c, "names": n} for c, n in grouped.items()],
    }


def load_market_types() -> list[dict]:
    with engine.connect() as conn:
        return _rows(conn, "SELECT umid, canonical_name, first_seen_at, last_updated_at FROM market_types ORDER BY umid")


def load_blown_leads(min_lead: int) -> list[dict]:
    sql = """
        WITH goals AS (
            SELECT sofa_event_id, time, added_time, home_score, away_score,
                   home_score - away_score AS diff
            FROM sofa_incidents
            WHERE incident_type = 'goal'
        ),
        agg AS (
            SELECT sofa_event_id,
                   MAX(diff) AS max_home_lead,
                   MIN(diff) AS max_away_lead
            FROM goals
            GROUP BY sofa_event_id
        ),
        home_cross AS (
            SELECT sofa_event_id, time, added_time, home_score, away_score,
                   ROW_NUMBER() OVER (PARTITION BY sofa_event_id ORDER BY time, added_time) AS rn
            FROM goals
            WHERE diff >= :min_lead
        ),
        away_cross AS (
            SELECT sofa_event_id, time, added_time, home_score, away_score,
                   ROW_NUMBER() OVER (PARTITION BY sofa_event_id ORDER BY time, added_time) AS rn
            FROM goals
            WHERE diff <= -:min_lead
        )
        SELECT
            gm.id AS game_id,
            g.sofa_event_id,
            COALESCE(gm.home_team, g.home_name) AS home_name,
            COALESCE(gm.away_team, g.away_name) AS away_name,
            g.score_home, g.score_away,
            FROM_UNIXTIME(g.start_timestamp) AS match_date,
            CASE
                WHEN a.max_home_lead >= :min_lead AND g.score_home <= g.score_away THEN 'home_blew_lead'
                WHEN a.max_away_lead <= -:min_lead AND g.score_away <= g.score_home THEN 'away_blew_lead'
            END AS scenario,
            CASE
                WHEN a.max_home_lead >= :min_lead AND g.score_home <= g.score_away THEN hc.home_score
                ELSE ac.home_score
            END AS lead_score_home,
            CASE
                WHEN a.max_home_lead >= :min_lead AND g.score_home <= g.score_away THEN hc.away_score
                ELSE ac.away_score
            END AS lead_score_away,
            CASE
                WHEN a.max_home_lead >= :min_lead AND g.score_home <= g.score_away THEN hc.time
                ELSE ac.time
            END AS lead_time
        FROM sofa_games g
        JOIN agg a ON a.sofa_event_id = g.sofa_event_id
        LEFT JOIN games gm ON gm.sofa_event_id = g.sofa_event_id
        LEFT JOIN home_cross hc ON hc.sofa_event_id = g.sofa_event_id AND hc.rn = 1
        LEFT JOIN away_cross ac ON ac.sofa_event_id = g.sofa_event_id AND ac.rn = 1
        WHERE (a.max_home_lead >= :min_lead AND g.score_home <= g.score_away)
           OR (a.max_away_lead <= -:min_lead AND g.score_away <= g.score_home)
        ORDER BY g.start_timestamp DESC
    """
    with engine.connect() as conn:
        return _rows(conn, sql, {"min_lead": min_lead})


def load_match_rates() -> dict:
    country_sql = """
        SELECT
            COALESCE(country, 'Unknown') AS country,
            COUNT(*) AS total,
            SUM(CASE WHEN sofa_event_id IS NOT NULL THEN 1 ELSE 0 END) AS matched
        FROM games
        GROUP BY COALESCE(country, 'Unknown')
        ORDER BY total DESC
    """
    league_sql = """
        SELECT
            COALESCE(country, 'Unknown') AS country,
            COALESCE(league, 'Unknown') AS league,
            COUNT(*) AS total,
            SUM(CASE WHEN sofa_event_id IS NOT NULL THEN 1 ELSE 0 END) AS matched
        FROM games
        GROUP BY COALESCE(country, 'Unknown'), COALESCE(league, 'Unknown')
        ORDER BY country, total DESC
    """
    with engine.connect() as conn:
        return {"countries": _rows(conn, country_sql), "leagues": _rows(conn, league_sql)}
