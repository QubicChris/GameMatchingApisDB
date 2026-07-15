"""
Pregames Data Browser
Run with: streamlit run dashboard.py
Requires DATABASE_URL in .env and auth.yaml for user credentials.
Generate auth.yaml with: python make_auth.py
"""
import os
import yaml
import streamlit as st
import pandas as pd
import streamlit_authenticator as stauth
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

st.set_page_config(
    page_title="Pregames Browser",
    page_icon="⚽",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Authentication ────────────────────────────────────────────────────────────

AUTH_FILE = os.path.join(os.path.dirname(__file__), "auth.yaml")

if not os.path.exists(AUTH_FILE):
    st.error("auth.yaml not found. Run `python make_auth.py` to create it.")
    st.stop()

with open(AUTH_FILE) as f:
    auth_config = yaml.safe_load(f)

authenticator = stauth.Authenticate(
    auth_config["credentials"],
    auth_config["cookie"]["name"],
    auth_config["cookie"]["key"],
    auth_config["cookie"]["expiry_days"],
)

authenticator.login()

if st.session_state.get("authentication_status") is False:
    st.error("Incorrect username or password.")
    st.stop()

if st.session_state.get("authentication_status") is None:
    st.warning("Please enter your username and password.")
    st.stop()

# Logged in — show logout button in sidebar
with st.sidebar:
    authenticator.logout("Logout", "sidebar")
    st.caption(f"Logged in as **{st.session_state.get('name')}**")
    st.markdown("---")

# ── DB connection ─────────────────────────────────────────────────────────────

@st.cache_resource
def get_engine():
    url = os.getenv("DATABASE_URL", "mysql+pymysql://user:password@localhost:3306/pregames")
    return create_engine(url)

engine = get_engine()


# ── Queries ───────────────────────────────────────────────────────────────────

@st.cache_data(ttl=60)
def load_summary():
    with engine.connect() as conn:
        total     = conn.execute(text("SELECT COUNT(*) FROM games")).scalar()
        matched   = conn.execute(text("SELECT COUNT(*) FROM games WHERE sofa_event_id IS NOT NULL")).scalar()
        countries = conn.execute(text("SELECT COUNT(DISTINCT country) FROM games")).scalar()
        bookers   = conn.execute(text("SELECT COUNT(DISTINCT company_name) FROM company_games")).scalar()
        dates     = conn.execute(text("SELECT MIN(DATE(date_time_starts_utc)), MAX(DATE(date_time_starts_utc)) FROM games")).fetchone()
    return {
        "total": total, "matched": matched, "unmatched": total - matched,
        "countries": countries, "bookers": bookers,
        "date_from": str(dates[0]), "date_to": str(dates[1]),
    }


@st.cache_data(ttl=60)
def load_dates():
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT DISTINCT DATE(date_time_starts_utc) AS d FROM games ORDER BY d DESC LIMIT 60"
        )).fetchall()
    return [str(r[0]) for r in rows]


@st.cache_data(ttl=60)
def load_countries():
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT DISTINCT country FROM games WHERE country IS NOT NULL ORDER BY country"
        )).fetchall()
    return [r[0] for r in rows]


@st.cache_data(ttl=30)
def load_games(date, country, sofa_filter):
    sql = """
        SELECT
            g.id,
            g.date_time_starts_utc AS kickoff,
            g.home_team,
            g.away_team,
            g.league,
            g.country,
            g.sofa_event_id,
            COUNT(DISTINCT cg.company_name) AS bookers,
            MAX(cg.score_home)              AS score_home,
            MAX(cg.score_away)              AS score_away
        FROM games g
        LEFT JOIN company_games cg ON cg.game_id = g.id
        WHERE DATE(g.date_time_starts_utc) = :date
    """
    params = {"date": date}
    if country != "All":
        sql += " AND g.country = :country"
        params["country"] = country
    if sofa_filter == "Matched":
        sql += " AND g.sofa_event_id IS NOT NULL"
    elif sofa_filter == "Unmatched":
        sql += " AND g.sofa_event_id IS NULL"
    sql += """
        GROUP BY g.id, g.home_team, g.away_team, g.league,
                 g.country, g.sofa_event_id
        ORDER BY g.date_time_starts_utc
    """
    with engine.connect() as conn:
        return pd.read_sql(text(sql), conn, params=params)


@st.cache_data(ttl=30)
def load_odds(game_id):
    sql = """
        SELECT
            pm.umid,
            mt.canonical_name,
            s.canonical_outcome,
            s.line_value,
            CASE
                WHEN s.line_value IS NULL THEN s.canonical_outcome
                ELSE CONCAT(s.canonical_outcome, ' ', s.line_value)
            END AS outcome,
            MAX(CASE WHEN cg.company_name = 'Pinnacle'  THEN s.odd END) AS pinnacle,
            MAX(CASE WHEN cg.company_name = 'Fair888'   THEN s.odd END) AS fair888,
            MAX(CASE WHEN cg.company_name = 'Stoiximan' THEN s.odd END) AS stoiximan,
            MAX(so.odd)     AS sofa_close,
            MAX(so.winning) AS sofa_winning
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
        GROUP BY pm.umid, mt.canonical_name, s.canonical_outcome, s.line_value
        ORDER BY pm.umid, s.line_value,
            CASE s.canonical_outcome
                WHEN 'home'  THEN 1
                WHEN 'draw'  THEN 2
                WHEN 'away'  THEN 3
                WHEN 'yes'   THEN 1
                WHEN 'no'    THEN 2
                WHEN 'over'  THEN 1
                WHEN 'under' THEN 2
                WHEN '1x'    THEN 1
                WHEN 'x2'    THEN 2
                WHEN '12'    THEN 3
                ELSE 4
            END
    """
    with engine.connect() as conn:
        return pd.read_sql(text(sql), conn, params={"game_id": game_id})


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
    "accurateLongBalls":        ("long_balls_home",            "long_balls_away",            "long_balls_home_total",   "long_balls_away_total"),
    "accurateCross":            ("crosses_home",               "crosses_away",               "crosses_home_total",      "crosses_away_total"),
    "finalThirdPhaseStatistic": ("final_third_home",           "final_third_away",           "final_third_home_total",  "final_third_away_total"),
    "duelWonPercent":           ("duel_won_pct_home",          "duel_won_pct_away",          None, None),
    "dispossessed":             ("dispossessed_home",          "dispossessed_away",          None, None),
    "groundDuelsPercentage":    ("ground_duels_home",          "ground_duels_away",          "ground_duels_home_total", "ground_duels_away_total"),
    "aerialDuelsPercentage":    ("aerial_duels_home",          "aerial_duels_away",          "aerial_duels_home_total", "aerial_duels_away_total"),
    "dribblesPercentage":       ("dribbles_home",              "dribbles_away",              "dribbles_home_total",     "dribbles_away_total"),
    "interceptionWon":          ("interceptions_home",         "interceptions_away",         None, None),
    "totalClearance":           ("clearances_home",            "clearances_away",            None, None),
    "errorsLeadToShot":         ("errors_lead_to_shot_home",   "errors_lead_to_shot_away",   None, None),
    "goalKicks":                ("goal_kicks_home",            "goal_kicks_away",            None, None),
}


def _fetch_and_store_statistics(game_id: int, sofa_event_id: int):
    import urllib.request, urllib.parse, json
    rapidapi_key  = os.getenv("RAPIDAPI_KEY", "")
    rapidapi_host = "sofasport.p.rapidapi.com"
    if not rapidapi_key:
        return None
    url = f"https://{rapidapi_host}/v1/events/statistics"
    params = urllib.parse.urlencode({"event_id": sofa_event_id})
    req = urllib.request.Request(
        f"{url}?{params}",
        headers={"x-rapidapi-key": rapidapi_key, "x-rapidapi-host": rapidapi_host},
        method="GET"
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        raw_stats = json.loads(resp.read().decode("utf-8")).get("data", [])

    seen = set()
    by_period = {}
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

    if not by_period:
        return None

    with engine.begin() as conn:
        conn.execute(text("DELETE FROM sofa_statistics WHERE game_id = :gid"), {"gid": game_id})
        for period, cols in by_period.items():
            cols["game_id"] = game_id
            cols["sofa_event_id"] = sofa_event_id
            cols["period"] = period
            col_names    = ", ".join(cols.keys())
            placeholders = ", ".join(f":{k}" for k in cols.keys())
            conn.execute(text(f"INSERT INTO sofa_statistics ({col_names}) VALUES ({placeholders})"), cols)

    return by_period.get("ALL")


@st.cache_data(ttl=300)
def load_statistics(game_id, sofa_event_id):
    with engine.connect() as conn:
        df = pd.read_sql(
            text("SELECT * FROM sofa_statistics WHERE game_id = :gid AND period = 'ALL' LIMIT 1"),
            conn, params={"gid": game_id}
        )
    if not df.empty:
        return df.iloc[0]
    try:
        cols = _fetch_and_store_statistics(game_id, sofa_event_id)
        if cols:
            return pd.Series(cols)
    except Exception as e:
        st.warning(f"Could not fetch statistics from API: {e}")
    return None


@st.cache_data(ttl=30)
def load_incidents(game_id):
    sql = """
        SELECT
            incident_type, incident_class, time, added_time, reversed_period_time,
            is_home, home_score, away_score,
            player_name, assist_player_name, player_in_name, player_out_name,
            reason, rescinded, confirmed, injury,
            manager_name, text, length
        FROM sofa_incidents
        WHERE game_id = :game_id
        ORDER BY reversed_period_time DESC, time, added_time
    """
    with engine.connect() as conn:
        return pd.read_sql(text(sql), conn, params={"game_id": game_id})


@st.cache_data(ttl=60)
def load_aliases(search=""):
    sql = """
        SELECT
            canonical_name,
            MAX(CASE WHEN company_name = 'Pinnacle'  THEN company_team_name END) AS pinnacle,
            MAX(CASE WHEN company_name = 'Fair888'   THEN company_team_name END) AS fair888,
            MAX(CASE WHEN company_name = 'Stoiximan' THEN company_team_name END) AS stoiximan,
            MAX(CASE WHEN company_name = 'Sofasport' THEN company_team_name END) AS sofasport
        FROM team_aliases
    """
    params = {}
    if search:
        sql += " WHERE canonical_name LIKE :s OR company_team_name LIKE :s"
        params["s"] = f"%{search}%"
    sql += " GROUP BY canonical_name ORDER BY canonical_name"
    with engine.connect() as conn:
        return pd.read_sql(text(sql), conn, params=params)


@st.cache_data(ttl=60)
def load_market_types():
    with engine.connect() as conn:
        return pd.read_sql(
            text("SELECT umid, canonical_name, first_seen_at, last_updated_at FROM market_types ORDER BY umid"),
            conn
        )


@st.cache_data(ttl=60)
def load_blown_leads(min_lead):
    sql = """
        WITH goals AS (
            SELECT sofa_event_id, time, added_time,
                   home_score - away_score AS diff
            FROM sofa_incidents
            WHERE incident_type = 'goal'
        ),
        running AS (
            SELECT sofa_event_id,
                   MAX(diff) OVER (PARTITION BY sofa_event_id ORDER BY time, added_time
                                    ROWS UNBOUNDED PRECEDING) AS running_max,
                   MIN(diff) OVER (PARTITION BY sofa_event_id ORDER BY time, added_time
                                    ROWS UNBOUNDED PRECEDING) AS running_min
            FROM goals
        ),
        agg AS (
            SELECT sofa_event_id,
                   MAX(running_max) AS max_home_lead,
                   MIN(running_min) AS max_away_lead
            FROM running
            GROUP BY sofa_event_id
        )
        SELECT
            g.sofa_event_id, g.home_name, g.away_name, g.score_home, g.score_away,
            FROM_UNIXTIME(g.start_timestamp) AS match_date,
            a.max_home_lead, a.max_away_lead,
            CASE
                WHEN a.max_home_lead >= :min_lead AND g.score_home <= g.score_away THEN 'home_blew_lead'
                WHEN a.max_away_lead <= -:min_lead AND g.score_away <= g.score_home THEN 'away_blew_lead'
            END AS scenario
        FROM sofa_games g
        JOIN agg a ON a.sofa_event_id = g.sofa_event_id
        WHERE (a.max_home_lead >= :min_lead AND g.score_home <= g.score_away)
           OR (a.max_away_lead <= -:min_lead AND g.score_away <= g.score_home)
        ORDER BY g.start_timestamp DESC
    """
    with engine.connect() as conn:
        return pd.read_sql(text(sql), conn, params={"min_lead": min_lead})


# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("## ⚽ Pregames")
    st.markdown("---")

    try:
        summary = load_summary()
        pct = int(summary["matched"] / summary["total"] * 100) if summary["total"] else 0
        st.metric("Total Games",   summary["total"])
        st.metric("Sofa Matched",  f"{summary['matched']} / {summary['total']}", f"{pct}%")
        st.metric("Unmatched",     summary["unmatched"])
        st.metric("Countries",     summary["countries"])
        st.metric("Bookmakers",    summary["bookers"])
        st.caption(f"{summary['date_from']} → {summary['date_to']}")
    except Exception as e:
        st.error(f"DB connection error: {e}")

    st.markdown("---")
    st.markdown("### Filters")

    try:
        dates = load_dates()
    except Exception as e:
        st.error(f"Failed to load available dates: {e}")
        st.exception(e)
        dates = []

    from datetime import date, datetime
    default_date = datetime.strptime(dates[0], "%Y-%m-%d").date() if dates else date.today()
    sel_date_dt  = st.date_input("Date", value=default_date)
    sel_date     = sel_date_dt.strftime("%Y-%m-%d")

    try:
        countries = ["All"] + load_countries()
    except Exception as e:
        st.error(f"Failed to load countries: {e}")
        st.exception(e)
        countries = ["All"]

    sel_country = st.selectbox("Country", countries)
    sofa_filter = st.radio("Sofa Status", ["All", "Matched", "Unmatched"], horizontal=True)

    st.markdown("---")
    page = st.radio(
        "View",
        ["🎮 Games", "🔤 Team Aliases", "📋 Market Types", "📉 Blown Leads"],
        label_visibility="collapsed"
    )

    st.markdown("---")
    if st.button("🔄 Refresh data", use_container_width=True):
        st.cache_data.clear()
        st.rerun()


# ── Games page ────────────────────────────────────────────────────────────────

if page == "🎮 Games":
    st.markdown(f"### Games — {sel_date}")

    try:
        games = load_games(sel_date, sel_country, sofa_filter)
    except Exception as e:
        st.error(f"Failed to load games: {e}")
        st.exception(e)
        st.stop()

    if games.empty:
        st.info("No games found for the selected filters.")
        st.stop()

    matched_count = games["sofa_event_id"].notna().sum()
    st.caption(f"{len(games)} game(s) · {matched_count} sofa matched · {len(games) - matched_count} unmatched")

    # Build display table
    table = games.copy()
    table["score"] = table.apply(
        lambda r: f"{int(r.score_home)}-{int(r.score_away)}" if pd.notna(r.score_home) else "—", axis=1
    )
    table["sofa"] = table["sofa_event_id"].apply(lambda x: "✓" if pd.notna(x) else "✗")
    table["sofa_event_id"] = table["sofa_event_id"].apply(lambda x: int(x) if pd.notna(x) else "—")
    table["kickoff"] = pd.to_datetime(table["kickoff"]).dt.strftime("%Y-%m-%d %H:%M")
    display_table = table[["id", "kickoff", "home_team", "away_team", "league", "score", "sofa_event_id", "sofa"]].copy()
    display_table = display_table.rename(columns={
        "id": "game_id", "kickoff": "kickoff", "home_team": "home", "away_team": "away",
        "sofa_event_id": "sofa_id", "sofa": "matched"
    })
    st.dataframe(display_table.style.hide(axis="index"), use_container_width=True, height=min(400, len(games)*38+40))

    # Game selector by ID
    game_ids = games["id"].tolist()
    sel_id = st.number_input("Enter game_id to inspect", min_value=min(game_ids), max_value=max(game_ids), value=game_ids[0], step=1)
    matches = games[games["id"] == sel_id]
    if matches.empty:
        st.warning(f"game_id {sel_id} not found in the current filter.")
        st.stop()
    row = matches.iloc[0]

    kickoff_str = pd.to_datetime(row.kickoff).strftime("%Y-%m-%d %H:%M") if pd.notna(row.kickoff) else "—"
    st.markdown(f"### {row.home_team} vs {row.away_team}")
    st.caption(f"📅 {kickoff_str} · {row.league} · {row.country}")

    st.markdown("---")


    tab_odds, tab_stats, tab_incidents = st.tabs(["📈 Odds Comparison", "📊 Statistics", "🕒 Incidents"])

    # ── Odds ──────────────────────────────────────────────────────────────────
    with tab_odds:
        try:
            odds = load_odds(int(row.id))
        except Exception as e:
            st.error(f"Failed to load odds: {e}")
            odds = pd.DataFrame()

        if odds.empty:
            st.info("No odds data for this game.")
        else:
            for market in odds["canonical_name"].dropna().unique():
                st.markdown(f"**{market}**")
                mkt = odds[odds["canonical_name"] == market].copy()

                display = mkt[["outcome","pinnacle","fair888","stoiximan","sofa_close"]].copy()
                display = display.rename(columns={"sofa_close": "sofa close"})

                st.dataframe(
                    display.style
                        .format({"pinnacle":"{:.2f}","fair888":"{:.2f}","stoiximan":"{:.2f}","sofa close":"{:.2f}"}, na_rep="—")
                        .hide(axis="index"),
                    use_container_width=True,
                    height=len(mkt) * 38 + 40,
                )
                st.markdown("")

    # ── Statistics ────────────────────────────────────────────────────────────
    with tab_stats:
        if pd.isna(row.sofa_event_id):
            st.warning("No Sofasport match — statistics unavailable.")
        else:
            try:
                stats = load_statistics(int(row.id), int(row.sofa_event_id))
            except Exception as e:
                st.error(f"Failed to load statistics: {e}")
                stats = None

            if stats is None:
                st.info("Statistics not available for this game.")
            else:
                home = row.home_team
                away = row.away_team

                # Score table
                score_home = int(row.score_home) if pd.notna(row.score_home) else "—"
                score_away = int(row.score_away) if pd.notna(row.score_away) else "—"
                score_df = pd.DataFrame([{
                    "": "Score",
                    home: score_home,
                    away: score_away,
                }]).set_index("")
                st.dataframe(score_df, use_container_width=False)
                st.markdown("")

                STAT_GROUPS = {
                    "Match Overview": [
                        ("Ball Possession %", "ball_possession", True),
                        ("Expected Goals",    "expected_goals",  False),
                        ("Total Shots",       "total_shots",     False),
                        ("Shots on Target",   "shots_on_target", False),
                        ("Corner Kicks",      "corner_kicks",    False),
                        ("Goalkeeper Saves",  "goalkeeper_saves",False),
                    ],
                    "Shots": [
                        ("Shots Off Target",  "shots_off_target",  False),
                        ("Blocked Shots",     "blocked_shots",     False),
                        ("Shots Inside Box",  "shots_inside_box",  False),
                        ("Shots Outside Box", "shots_outside_box", False),
                        ("Hit Woodwork",      "hit_woodwork",      False),
                    ],
                    "Discipline": [
                        ("Fouls",        "fouls",        False),
                        ("Yellow Cards", "yellow_cards", False),
                        ("Red Cards",    "red_cards",    False),
                        ("Free Kicks",   "free_kicks",   False),
                    ],
                    "Passing & Attack": [
                        ("Passes",          "passes",           False),
                        ("Accurate Passes", "accurate_passes",  False),
                        ("Through Balls",   "through_balls",    False),
                        ("Offsides",        "offsides",         False),
                        ("Touches in Box",  "touches_in_opp_box",False),
                    ],
                    "Defending": [
                        ("Tackles",       "tackles",       False),
                        ("Interceptions", "interceptions", False),
                        ("Clearances",    "clearances",    False),
                        ("Errors → Shot", "errors_lead_to_shot", False),
                    ],
                }

                col_left, col_right = st.columns(2)
                groups = list(STAT_GROUPS.items())

                for i, (group_name, fields) in enumerate(groups):
                    col = col_left if i % 2 == 0 else col_right
                    rows_data = []
                    for label, key, is_pct in fields:
                        h = stats.get(f"{key}_home")
                        a = stats.get(f"{key}_away")
                        if pd.notna(h) and pd.notna(a):
                            fmt = "{:.0f}%" if is_pct else "{:.2f}" if isinstance(h, float) and h != int(h) else "{:.0f}"
                            rows_data.append({"Stat": label, home: h, away: a})
                    if rows_data:
                        with col:
                            st.markdown(f"**{group_name}**")
                            st.dataframe(
                                pd.DataFrame(rows_data).set_index("Stat"),
                                use_container_width=True,
                            )
                            st.markdown("")

    # ── Incidents ─────────────────────────────────────────────────────────────
    with tab_incidents:
        if pd.isna(row.sofa_event_id):
            st.warning("No Sofasport match — incidents unavailable.")
        else:
            try:
                incidents = load_incidents(int(row.id))
            except Exception as e:
                st.error(f"Failed to load incidents: {e}")
                incidents = pd.DataFrame()

            if incidents.empty:
                st.info("No incidents recorded for this game.")
            else:
                def minute(r):
                    if pd.isna(r.time):
                        return "—"
                    m = f"{int(r.time)}'"
                    if pd.notna(r.added_time) and r.added_time not in (0, 999):
                        m += f"+{int(r.added_time)}"
                    return m

                def team(r):
                    if pd.isna(r.is_home):
                        return "—"
                    return row.home_team if r.is_home else row.away_team

                def event_detail(r):
                    t = r.incident_type
                    if t == "goal":
                        icon = {"penalty": "🥅⚽", "ownGoal": "🔴⚽"}.get(r.incident_class, "⚽")
                        label = {"penalty": "Penalty", "ownGoal": "Own Goal"}.get(r.incident_class, "Goal")
                        detail = r.player_name if pd.notna(r.player_name) else "—"
                        if pd.notna(r.assist_player_name):
                            detail += f" (assist: {r.assist_player_name})"
                        return icon, label, detail
                    if t == "card":
                        icon = "🟥" if r.incident_class == "red" else "🟨"
                        class_label = r.incident_class.title() if pd.notna(r.incident_class) else ""
                        detail = r.player_name if pd.notna(r.player_name) else "—"
                        if pd.notna(r.reason):
                            detail += f" — {r.reason}"
                        if r.rescinded:
                            detail += " (rescinded)"
                        return icon, f"{class_label} Card".strip(), detail
                    if t == "substitution":
                        out_name = r.player_out_name if pd.notna(r.player_out_name) else "?"
                        in_name = r.player_in_name if pd.notna(r.player_in_name) else "?"
                        detail = f"{out_name} ➜ {in_name}"
                        if r.injury:
                            detail += " (injury)"
                        return "🔄", "Substitution", detail
                    if t == "varDecision":
                        return "📺", "VAR", r.incident_class if pd.notna(r.incident_class) else "—"
                    if t == "period":
                        return "⏱️", "Half Time" if r.text == "HT" else "Full Time", ""
                    if t == "injuryTime":
                        return "➕", "Injury Time", f"{int(r.length)} min added" if pd.notna(r.length) else ""
                    return "•", t, ""

                table_rows = []
                for _, r in incidents.iterrows():
                    icon, label, detail = event_detail(r)
                    table_rows.append({
                        "Min": minute(r),
                        "Event": f"{icon} {label}",
                        "Team": team(r),
                        "Detail": detail,
                        "Score": f"{int(r.home_score)}-{int(r.away_score)}" if pd.notna(r.home_score) else "",
                    })

                st.dataframe(
                    pd.DataFrame(table_rows).style.hide(axis="index"),
                    use_container_width=True,
                    height=min(600, len(table_rows) * 38 + 40),
                )


# ── Team Aliases page ─────────────────────────────────────────────────────────

elif page == "🔤 Team Aliases":
    st.markdown("### Team Aliases")
    st.caption("How each source names the same team")

    search = st.text_input("Search", placeholder="e.g. Bayern")

    try:
        df = load_aliases(search)
        st.dataframe(df.style.hide(axis="index"), use_container_width=True, height=600)
        st.caption(f"{len(df)} team(s)")
    except Exception as e:
        st.error(f"Failed to load aliases: {e}")


# ── Market Types page ─────────────────────────────────────────────────────────

elif page == "📋 Market Types":
    st.markdown("### Market Types")
    st.caption("All known umids and their canonical names")

    try:
        df = load_market_types()
        null_count = df["canonical_name"].isna().sum()
        st.caption(f"{len(df)} market types · {null_count} with no canonical name yet")
        st.dataframe(df.style.hide(axis="index"), use_container_width=True, height=600)
    except Exception as e:
        st.error(f"Failed to load market types: {e}")


# ── Blown Leads page ──────────────────────────────────────────────────────────

elif page == "📉 Blown Leads":
    st.markdown("### Blown Leads")
    st.caption("Games where a team led by N+ goals at some point but didn't win")

    min_lead = st.number_input("Minimum lead", min_value=1, max_value=5, value=2, step=1)

    try:
        df = load_blown_leads(int(min_lead))
    except Exception as e:
        st.error(f"Failed to load blown leads: {e}")
        df = pd.DataFrame()

    if df.empty:
        st.info(f"No games found with a blown {min_lead}+ goal lead.")
    else:
        display = df.copy()
        display["date"] = pd.to_datetime(display["match_date"]).dt.strftime("%Y-%m-%d %H:%M")
        display["score"] = display.apply(lambda r: f"{int(r.score_home)}-{int(r.score_away)}", axis=1)
        display = display[["date", "home_name", "away_name", "score", "max_home_lead", "max_away_lead", "scenario"]]
        display = display.rename(columns={
            "home_name": "home", "away_name": "away",
            "max_home_lead": "max home lead", "max_away_lead": "max away lead",
        })
        st.caption(f"{len(display)} game(s) found")
        st.dataframe(display.style.hide(axis="index"), use_container_width=True, height=min(600, len(display) * 38 + 40))