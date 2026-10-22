"""
Export games for a kickoff date range to an Excel workbook with readable headers.

One workbook holds one sheet per dataset. Foreign-key ids are replaced by names,
and bookmaker odds are pivoted wide (one column per bookmaker) to keep row counts
down. A full database dump does not fit in Excel, so every export is bounded by a
kickoff date range and refuses (ExportTooLarge) if any sheet would exceed
MAX_SHEET_ROWS.

Used by export_excel.py (CLI) and webapi/routes.py (download endpoint).
"""
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Callable

import xlsxwriter
from sqlalchemy import bindparam, text

from models import SofaStatistic

# Excel's hard limit is 1,048,576 rows per sheet. 500k keeps server memory
# reasonable, because XlsxWriter holds a sheet in memory.
MAX_SHEET_ROWS = 500_000

RANGE = "g.date_time_starts_utc >= :start AND g.date_time_starts_utc < :end /*GAME_FILTER*/"
MATCH = "CONCAT(g.home_team, ' v ', g.away_team)"


@dataclass(frozen=True)
class Col:
    key: str
    header: str
    kind: str = "text"


@dataclass(frozen=True)
class SheetSpec:
    name: str
    sql: str
    count_sql: str
    columns: tuple
    odds: bool = False
    ranged: bool = True
    transform: Callable[[dict], dict] | None = None


class ExportTooLarge(Exception):
    def __init__(self, too_large: dict):
        self.too_large = too_large
        parts = ", ".join(f"{n} has more than {MAX_SHEET_ROWS:,} rows" for n in too_large)
        super().__init__(
            f"Too many rows for Excel: {parts} (max {MAX_SHEET_ROWS:,}). "
            "Pick a shorter date range or leave out odds or add filters."
        )


class ExportRangeError(ValueError):
    pass


class ExportFilterError(ValueError):
    pass


class ExportCancelled(Exception):
    """Raised from a progress callback to stop an export early."""


# progress(stage, sheet, rows_done_in_this_stage_for_this_sheet)
# stage is "fetching" | "writing" | "saving". The callback may raise ExportCancelled.
ProgressFn = Callable[[str, "str | None", int], None]
PROGRESS_EVERY = 5000


@dataclass(frozen=True)
class ExportFilters:
    """Optional narrowing of an export. Empty tuple = no filter on that dimension."""
    countries: tuple[str, ...] = ()
    leagues: tuple[str, ...] = ()
    umids: tuple[int, ...] = ()
    sheets: tuple[str, ...] = ()      # data sheet names to include; empty = all

    @property
    def narrows_rows(self) -> bool:
        return bool(self.countries or self.leagues or self.umids)


NO_FILTERS = ExportFilters()

# Our market id (umid) -> Sofascore market id. Mirrors the CASE in _ODDS_SQL; keep them in sync.
UMID_TO_SOFA_MARKET = {1: 1, 2: 2, 4: 3, 6: 4, 3: 5, 50: 9, 53: 17, 58: 20, 55: 21}


# ── Pure helpers ─────────────────────────────────────────────────────────────

STAT_LABELS = {
    "ball_possession": "Possession %", "expected_goals": "Expected Goals (xG)", "total_shots": "Total Shots",
    "goalkeeper_saves": "Goalkeeper Saves", "corner_kicks": "Corners", "fouls": "Fouls", "passes": "Passes",
    "tackles": "Tackles", "free_kicks": "Free Kicks", "yellow_cards": "Yellow Cards", "red_cards": "Red Cards",
    "shots_on_target": "Shots on Target", "shots_off_target": "Shots off Target", "blocked_shots": "Blocked Shots",
    "shots_inside_box": "Shots Inside Box", "shots_outside_box": "Shots Outside Box", "hit_woodwork": "Hit Woodwork",
    "through_balls": "Through Balls", "touches_in_opp_box": "Touches in Opp. Box", "offsides": "Offsides",
    "accurate_passes": "Accurate Passes", "throw_ins": "Throw-ins", "long_balls": "Accurate Long Balls",
    "crosses": "Accurate Crosses", "final_third": "Final Third Entries", "duel_won_pct": "Duels Won %",
    "dispossessed": "Dispossessed", "ground_duels": "Ground Duels Won", "aerial_duels": "Aerial Duels Won",
    "dribbles": "Successful Dribbles", "interceptions": "Interceptions", "clearances": "Clearances",
    "errors_lead_to_shot": "Errors Leading to Shot", "goal_kicks": "Goal Kicks",
}


def stat_header(col: str) -> str:
    for suffix, side in (("_home_total", "Home, Total"), ("_away_total", "Away, Total"),
                         ("_home", "Home"), ("_away", "Away")):
        if col.endswith(suffix):
            base = col[: -len(suffix)]
            return f"{STAT_LABELS.get(base, base.replace('_', ' ').title())} ({side})"
    return col.replace("_", " ").title()


def incident_minute(time, added_time) -> str:
    if time is None:
        return ""
    s = f"{time}'"
    if added_time not in (None, 0, 999):
        s += f"+{added_time}"
    return s


def yes_no(v):
    if v is None:
        return None
    return "Yes" if v else "No"


def _won_lost(v):
    if v is None:
        return None
    return "Won" if v else "Lost"


def _max(a, b):
    return b if a is None else a if b is None else max(a, b)


def pivot_odds_rows(rows, cap: int | None = None,
                    progress: Callable[[int], None] | None = None) -> tuple[list[str], list[dict]]:
    """Group raw odds rows into one wide row per (game, market, outcome, line).

    Grouping happens here, not in MySQL: a GROUP BY over a week of selections spills
    MySQL's temp table to disk, where some MySQL 8 builds raise a false
    "1062 Duplicate entry ... for key <group_key>". Dict-based (not pandas) so NULL
    line_value rows survive. Repeated (key, bookmaker) rows keep the max, like SQL MAX().
    """
    books: set[str] = set()
    wide: dict = {}
    consumed = 0
    for r in rows:
        consumed += 1
        if progress and consumed % PROGRESS_EVERY == 0:
            progress(len(wide))
        key = (r["game_id"], r["umid"], r["outcome"], r["line_value"])
        w = wide.get(key)
        if w is None:
            w = wide[key] = {
                "game_id": r["game_id"], "kickoff": r["kickoff"], "match_name": r["match_name"],
                "league": r["league"], "umid": r["umid"],
                "market": r["market"] or f"Market {r['umid']}",
                "outcome": r["outcome"], "line_value": r["line_value"],
                "_odds": {}, "sofa_close": None, "_win": None,
            }
        b = r["company_name"]
        books.add(b)
        w["_odds"][b] = _max(w["_odds"].get(b), r["odd"])
        w["sofa_close"] = _max(w["sofa_close"], r.get("sofa_close"))
        w["_win"] = _max(w["_win"], r.get("sofa_winning"))
        if cap is not None and len(wide) > cap:
            break
    if progress:
        progress(len(wide))
    bookmakers = sorted(books)
    out = []
    for w in wide.values():
        odds = w.pop("_odds")
        w["sofa_result"] = _won_lost(w.pop("_win"))
        for b in bookmakers:
            w[f"odds_{b}"] = odds.get(b)
        vals = {b: v for b, v in odds.items() if v is not None}
        if vals:
            best = max(vals.values())
            w["best_odds"] = best
            w["best_bookmaker"] = ", ".join(b for b in bookmakers if vals.get(b) == best)
        else:
            w["best_odds"] = None
            w["best_bookmaker"] = None
        out.append(w)
    return bookmakers, out


def count_odds_keys(keys, cap: int) -> int:
    """Number of distinct (game, market, outcome, line) keys; stops counting once it exceeds `cap`."""
    seen = set()
    for k in keys:
        seen.add(tuple(k))
        if len(seen) > cap:
            break
    return len(seen)


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_range(date_from: str, date_to: str) -> tuple[datetime, datetime]:
    parsed = []
    for label, v in (("from", date_from), ("to", date_to)):
        if not isinstance(v, str) or not _DATE_RE.match(v):
            raise ExportRangeError(f"Invalid '{label}' date {v!r}; use YYYY-MM-DD.")
        try:
            parsed.append(datetime.strptime(v, "%Y-%m-%d"))
        except ValueError:
            raise ExportRangeError(f"Invalid '{label}' date {v!r}; use YYYY-MM-DD.")
    start, end = parsed
    if start > end:
        raise ExportRangeError(f"'from' date {date_from} is after 'to' date {date_to}.")
    return start, end + timedelta(days=1)


def default_filename(date_from, date_to, include_odds: bool = True, filtered: bool = False) -> str:
    suffix = ("" if include_odds else "_no-odds") + ("_filtered" if filtered else "")
    return f"pregames_{date_from}_to_{date_to}{suffix}.xlsx"


# ── Sheet definitions ────────────────────────────────────────────────────────

def _count(sql: str) -> str:
    return f"SELECT COUNT(*) FROM ({sql.split('ORDER BY')[0]}) t"


def _games_tf(r: dict) -> dict:
    r["sofa_matched"] = "Yes" if r.get("sofa_event_id") else "No"
    return r


def _sofa_odds_tf(r: dict) -> dict:
    r["winning"] = _won_lost(r.get("winning"))
    ch = r.get("change")
    r["change"] = None if ch is None else {1: "Up", -1: "Down", 0: "No change"}.get(int(ch), str(ch))
    return r


_PERIODS = {"ALL": "Full Match", "1ST": "1st Half", "2ND": "2nd Half"}


def _stats_tf(r: dict) -> dict:
    r["period"] = _PERIODS.get(r["period"], r["period"])
    return r


_EVENTS = {"goal": "Goal", "card": "Card", "substitution": "Substitution", "varDecision": "VAR Decision",
           "period": "Period", "injuryTime": "Injury Time"}


def _incidents_tf(r: dict) -> dict:
    r["match_name"] = f"{r['home_team']} v {r['away_team']}"
    r["minute"] = incident_minute(r["time"], r["added_time"])
    t = r["incident_type"]
    r["event"] = _EVENTS.get(t, t)
    ih = r["is_home"]
    r["team"] = None if ih is None else (r["home_team"] if ih else r["away_team"])
    for k in ("rescinded", "confirmed", "injury"):
        r[k] = yes_no(r[k])
    r["score_after"] = (f"{r['home_score']}-{r['away_score']}"
                        if r["home_score"] is not None and r["away_score"] is not None else None)
    return r


def _rates_tf(r: dict) -> dict:
    total = int(r["total"] or 0)
    matched = int(r["matched"] or 0)
    r["total"], r["matched"] = total, matched
    r["unmatched"] = total - matched
    r["rate"] = matched / total if total else None
    return r


STAT_COLUMNS = [c.name for c in SofaStatistic.__table__.columns
                if c.name not in ("id", "game_id", "sofa_event_id", "period", "fetched_at")]

_G_COLS = (Col("game_id", "Game ID", "int"), Col("kickoff", "Kickoff (UTC)", "datetime"))

_GAMES_SQL = f"""
SELECT g.id AS game_id, g.date_time_starts_utc AS kickoff, g.country, g.league,
       g.home_team, g.away_team, cg.score_home, cg.score_away, cg.bookmakers,
       g.sofa_event_id, sg.status AS sofa_status, sg.score_home AS sofa_score_home,
       sg.score_away AS sofa_score_away, g.univ_home_id, g.univ_away_id, g.univ_league_id, g.created_at
FROM games g
LEFT JOIN (SELECT game_id, MAX(score_home) AS score_home, MAX(score_away) AS score_away,
                  COUNT(DISTINCT company_name) AS bookmakers
           FROM company_games GROUP BY game_id) cg ON cg.game_id = g.id
LEFT JOIN sofa_games sg ON sg.sofa_event_id = g.sofa_event_id
WHERE {RANGE}
ORDER BY g.date_time_starts_utc, g.id
"""

_BG_SQL = f"""
SELECT g.id AS game_id, g.date_time_starts_utc AS kickoff, {MATCH} AS match_name, cg.company_name,
       cg.home_team, cg.away_team, cg.league, cg.score_home, cg.score_away,
       cg.corners_home, cg.corners_away, cg.date_pregame_data_updated, cg.date_live_data_updated
FROM company_games cg JOIN games g ON g.id = cg.game_id
WHERE {RANGE}
ORDER BY g.date_time_starts_utc, g.id, cg.company_name
"""

# Raw (ungrouped) rows: grouping is done in Python by pivot_odds_rows (see its docstring).
# Never GROUP/ORDER BY the bare alias `outcome` (sofa_odds has a column of that name -> error 1055).
_ODDS_SQL = f"""
SELECT g.id AS game_id, g.date_time_starts_utc AS kickoff, {MATCH} AS match_name, g.league,
       pm.umid, mt.canonical_name AS market,
       COALESCE(s.canonical_outcome, s.raw_outcome) AS outcome, s.line_value,
       cg.company_name, s.odd AS odd, so.odd AS sofa_close, so.winning AS sofa_winning
FROM games g
JOIN company_games cg ON cg.game_id = g.id
JOIN pregame_markets pm ON pm.company_game_id = cg.id
LEFT JOIN market_types mt ON mt.umid = pm.umid
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
WHERE {RANGE}/*MARKET_FILTER*/
ORDER BY g.date_time_starts_utc, g.id, pm.umid, s.line_value, s.id
"""

_ODDS_KEYS_SQL = f"""
SELECT g.id, pm.umid, COALESCE(s.canonical_outcome, s.raw_outcome), s.line_value
FROM games g JOIN company_games cg ON cg.game_id = g.id
JOIN pregame_markets pm ON pm.company_game_id = cg.id JOIN selections s ON s.market_id = pm.id
WHERE {RANGE}/*MARKET_FILTER*/
"""

_LADDER_SQL = f"""
SELECT g.id AS game_id, g.date_time_starts_utc AS kickoff, {MATCH} AS match_name, cg.company_name,
       pm.umid, mt.canonical_name AS market, s.canonical_outcome, s.line_value, s.raw_outcome, s.odd,
       s.back_bpf_pos1, s.back_bsz_pos1, s.back_bpf_pos2, s.back_bsz_pos2, s.back_bpf_pos3, s.back_bsz_pos3,
       s.lay_bpf_pos1, s.lay_bsz_pos1, s.lay_bpf_pos2, s.lay_bsz_pos2, s.lay_bpf_pos3, s.lay_bsz_pos3
FROM selections s
JOIN pregame_markets pm ON pm.id = s.market_id
JOIN company_games cg ON cg.id = pm.company_game_id
JOIN games g ON g.id = cg.game_id
LEFT JOIN market_types mt ON mt.umid = pm.umid
WHERE {RANGE}/*MARKET_FILTER*/ AND (s.back_bpf_pos1 IS NOT NULL OR s.lay_bpf_pos1 IS NOT NULL)
ORDER BY g.date_time_starts_utc, g.id, cg.company_name, pm.umid, s.line_value, s.id
"""

_SOFA_ODDS_SQL = f"""
SELECT g.id AS game_id, g.date_time_starts_utc AS kickoff, {MATCH} AS match_name, so.sofa_event_id,
       so.market_id, so.market_name, so.market_group, so.market_period, so.choice_group, so.outcome,
       so.initial_odd, so.odd, so.winning, so.`change`
FROM sofa_odds so JOIN games g ON g.id = so.game_id
WHERE {RANGE}/*SOFA_MARKET_FILTER*/
ORDER BY g.date_time_starts_utc, g.id, so.market_id, so.choice_group, so.id
"""

_STATS_SQL = (
    "SELECT g.id AS game_id, g.date_time_starts_utc AS kickoff, g.home_team, g.away_team, st.period, "
    + ", ".join(f"st.{c}" for c in STAT_COLUMNS)
    + f"\nFROM sofa_statistics st JOIN games g ON g.id = st.game_id\nWHERE {RANGE}\n"
    "ORDER BY g.date_time_starts_utc, g.id, FIELD(st.period, 'ALL', '1ST', '2ND'), st.period"
)

_INCIDENTS_SQL = f"""
SELECT g.id AS game_id, g.date_time_starts_utc AS kickoff, g.home_team, g.away_team,
       i.incident_type, i.incident_class, i.time, i.added_time, i.is_home,
       i.player_name, i.assist_player_name, i.player_in_name, i.player_out_name,
       i.reason, i.rescinded, i.confirmed, i.injury, i.manager_name, i.home_score, i.away_score,
       i.text, i.length
FROM sofa_incidents i JOIN games g ON g.id = i.game_id
WHERE {RANGE}
ORDER BY g.date_time_starts_utc, g.id, i.time, i.added_time, i.id
"""

_RATES_SQL = f"""
SELECT COALESCE(g.country, 'Unknown') AS country, COALESCE(g.league, 'Unknown') AS league,
       COUNT(*) AS total, SUM(CASE WHEN g.sofa_event_id IS NOT NULL THEN 1 ELSE 0 END) AS matched
FROM games g WHERE {RANGE}
GROUP BY COALESCE(g.country, 'Unknown'), COALESCE(g.league, 'Unknown')
ORDER BY country, total DESC
"""

_ALIASES_SQL = ("SELECT canonical_name, company_name, company_team_name, first_seen_at "
                "FROM team_aliases ORDER BY canonical_name, company_name")
_MARKETS_SQL = "SELECT umid, canonical_name, first_seen_at, last_updated_at FROM market_types ORDER BY umid"

_LADDER_COLS = []
for _side in ("back", "lay"):
    for _i in (1, 2, 3):
        _LADDER_COLS.append(Col(f"{_side}_bpf_pos{_i}", f"{_side.title()} Price {_i}", "odds"))
        _LADDER_COLS.append(Col(f"{_side}_bsz_pos{_i}", f"{_side.title()} Size {_i}", "float"))

SHEETS: list[SheetSpec] = [
    SheetSpec("Games", _GAMES_SQL, _count(_GAMES_SQL), (
        Col("game_id", "Game ID", "int"), Col("kickoff", "Kickoff (UTC)", "datetime"),
        Col("country", "Country"), Col("league", "League"),
        Col("home_team", "Home Team"), Col("away_team", "Away Team"),
        Col("score_home", "Home Score", "int"), Col("score_away", "Away Score", "int"),
        Col("bookmakers", "Bookmakers", "int"), Col("sofa_matched", "Sofa Matched"),
        Col("sofa_event_id", "Sofa Event ID", "int"), Col("sofa_status", "Sofa Status"),
        Col("sofa_score_home", "Sofa Home Score", "int"), Col("sofa_score_away", "Sofa Away Score", "int"),
        Col("univ_home_id", "Universal Home ID", "int"), Col("univ_away_id", "Universal Away ID", "int"),
        Col("univ_league_id", "Universal League ID", "int"),
        Col("created_at", "First Ingested (UTC)", "datetime"),
    ), transform=_games_tf),
    SheetSpec("Bookmaker Games", _BG_SQL, _count(_BG_SQL), (
        Col("game_id", "Game ID", "int"), Col("kickoff", "Kickoff (UTC)", "datetime"),
        Col("match_name", "Match"), Col("company_name", "Bookmaker"),
        Col("home_team", "Bookmaker Home Name"), Col("away_team", "Bookmaker Away Name"),
        Col("league", "Bookmaker League"),
        Col("score_home", "Home Score", "int"), Col("score_away", "Away Score", "int"),
        Col("corners_home", "Home Corners", "int"), Col("corners_away", "Away Corners", "int"),
        Col("date_pregame_data_updated", "Pregame Data Updated (UTC)", "datetime"),
        Col("date_live_data_updated", "Live Data Updated (UTC)", "datetime"),
    )),
    SheetSpec("Odds", _ODDS_SQL, "", (), odds=True),
    SheetSpec("Exchange Ladder", _LADDER_SQL, _count(_LADDER_SQL), (
        Col("game_id", "Game ID", "int"), Col("kickoff", "Kickoff (UTC)", "datetime"),
        Col("match_name", "Match"), Col("company_name", "Bookmaker"),
        Col("umid", "Market ID", "int"), Col("market", "Market"),
        Col("canonical_outcome", "Outcome"), Col("line_value", "Line", "float"),
        Col("raw_outcome", "Raw Outcome"), Col("odd", "Odds", "odds"),
        *_LADDER_COLS,
    ), odds=True),
    SheetSpec("Sofa Odds", _SOFA_ODDS_SQL, _count(_SOFA_ODDS_SQL), (
        Col("game_id", "Game ID", "int"), Col("kickoff", "Kickoff (UTC)", "datetime"),
        Col("match_name", "Match"), Col("sofa_event_id", "Sofa Event ID", "int"),
        Col("market_id", "Sofa Market ID", "int"), Col("market_name", "Market"),
        Col("market_group", "Market Group"), Col("market_period", "Period"),
        Col("choice_group", "Line"), Col("outcome", "Outcome"),
        Col("initial_odd", "Opening Odds", "odds"), Col("odd", "Closing Odds", "odds"),
        Col("winning", "Result"), Col("change", "Movement"),
    ), odds=True, transform=_sofa_odds_tf),
    SheetSpec("Match Stats", _STATS_SQL, _count(_STATS_SQL), (
        Col("game_id", "Game ID", "int"), Col("kickoff", "Kickoff (UTC)", "datetime"),
        Col("home_team", "Home Team"), Col("away_team", "Away Team"), Col("period", "Period"),
        *(Col(c, stat_header(c), "float") for c in STAT_COLUMNS),
    ), transform=_stats_tf),
    SheetSpec("Incidents", _INCIDENTS_SQL, _count(_INCIDENTS_SQL), (
        Col("game_id", "Game ID", "int"), Col("kickoff", "Kickoff (UTC)", "datetime"),
        Col("match_name", "Match"), Col("minute", "Minute"), Col("event", "Event"),
        Col("incident_class", "Detail"), Col("team", "Team"), Col("player_name", "Player"),
        Col("assist_player_name", "Assist"), Col("player_in_name", "Player In"),
        Col("player_out_name", "Player Out"), Col("reason", "Reason"),
        Col("rescinded", "Rescinded"), Col("confirmed", "VAR Confirmed"), Col("injury", "Injury Substitution"),
        Col("manager_name", "Manager"), Col("score_after", "Score After"),
        Col("text", "Period Marker"), Col("length", "Stoppage Minutes Added", "int"),
    ), transform=_incidents_tf),
    SheetSpec("Match Rates", _RATES_SQL, _count(_RATES_SQL), (
        Col("country", "Country"), Col("league", "League"), Col("total", "Games", "int"),
        Col("matched", "Matched", "int"), Col("unmatched", "Unmatched", "int"),
        Col("rate", "Match Rate", "pct"),
    ), transform=_rates_tf),
    SheetSpec("Team Aliases", _ALIASES_SQL, _count(_ALIASES_SQL), (
        Col("canonical_name", "Team (Canonical)"), Col("company_name", "Source"),
        Col("company_team_name", "Name at Source"), Col("first_seen_at", "First Seen (UTC)", "datetime"),
    ), ranged=False),
    SheetSpec("Market Types", _MARKETS_SQL, _count(_MARKETS_SQL), (
        Col("umid", "Market ID", "int"), Col("canonical_name", "Market Name"),
        Col("first_seen_at", "First Seen (UTC)", "datetime"),
        Col("last_updated_at", "Last Updated (UTC)", "datetime"),
    ), ranged=False),
]


DATA_SHEETS = [s.name for s in SHEETS]


def sheet_specs(include_odds: bool, sheets: tuple[str, ...] = ()) -> list[SheetSpec]:
    unknown = [n for n in sheets if n not in DATA_SHEETS]
    if unknown:
        raise ExportFilterError(f"Unknown sheet(s): {', '.join(unknown)}")
    specs = [s for s in SHEETS if (include_odds or not s.odds) and (not sheets or s.name in sheets)]
    if not specs:
        raise ExportFilterError("Pick at least one sheet to export.")
    return specs


def _filtered(sql: str, f: ExportFilters) -> tuple[str, dict, list[str]]:
    """Fill the filter markers. Returns (sql, extra params, names of list params needing expansion)."""
    params: dict = {}
    game = ""
    if f.countries:
        game += " AND g.country IN :f_countries"
        params["f_countries"] = list(f.countries)
    if f.leagues:
        game += " AND g.league IN :f_leagues"
        params["f_leagues"] = list(f.leagues)
    market = sofa = ""
    if f.umids:
        market = " AND pm.umid IN :f_umids"
        params["f_umids"] = list(f.umids)
        sofa_ids = sorted({UMID_TO_SOFA_MARKET[u] for u in f.umids if u in UMID_TO_SOFA_MARKET})
        if sofa_ids:
            sofa = " AND so.market_id IN :f_sofa_markets"
            params["f_sofa_markets"] = sofa_ids
        else:
            sofa = " AND 1 = 0"   # chosen markets have no Sofascore equivalent
    sql = (sql.replace("/*GAME_FILTER*/", game)
              .replace("/*MARKET_FILTER*/", market)
              .replace("/*SOFA_MARKET_FILTER*/", sofa))
    used = {k: v for k, v in params.items() if f":{k}" in sql}
    return sql, used, list(used)


# ── DB access ────────────────────────────────────────────────────────────────

def _clean(v):
    if isinstance(v, Decimal):
        return int(v) if v == v.to_integral_value() else float(v)
    return v


def _params(spec: SheetSpec, start, end) -> dict:
    return {"start": start, "end": end} if spec.ranged else {}


def _stmt(sql: str, spec: "SheetSpec", start, end, f: ExportFilters, limit: int | None = None):
    sql, extra, expanding = _filtered(sql, f)
    if limit is not None:
        sql = f"{sql.rstrip()}\nLIMIT {int(limit)}"
    stmt = text(sql)
    if expanding:
        stmt = stmt.bindparams(*(bindparam(k, expanding=True) for k in expanding))
    return stmt, {**_params(spec, start, end), **extra}


def count_rows(conn, specs, start, end, filters: ExportFilters = NO_FILTERS) -> dict:
    out = {}
    for spec in specs:
        if spec.name == "Odds":
            stmt, params = _stmt(_ODDS_KEYS_SQL, spec, start, end, filters)
            result = conn.execute(stmt.execution_options(stream_results=True), params)
            try:
                out[spec.name] = count_odds_keys(result, MAX_SHEET_ROWS)
            finally:
                result.close()
            continue
        stmt, params = _stmt(spec.count_sql, spec, start, end, filters)
        out[spec.name] = int(conn.execute(stmt, params).scalar() or 0)
    return out


def fetch_sheet(conn, spec: SheetSpec, start, end, filters: ExportFilters = NO_FILTERS, cap: int | None = None,
                progress: ProgressFn | None = None):
    if spec.name == "Odds":
        stmt, params = _stmt(spec.sql, spec, start, end, filters)
        result = conn.execute(stmt.execution_options(stream_results=True), params)
        try:
            bookmakers, wide = pivot_odds_rows(
                ({k: _clean(v) for k, v in m.items()} for m in result.mappings()), cap=cap,
                progress=(lambda n: progress("fetching", "Odds", n)) if progress else None)
        finally:
            result.close()
        cols = [
            Col("game_id", "Game ID", "int"), Col("kickoff", "Kickoff (UTC)", "datetime"),
            Col("match_name", "Match"), Col("league", "League"), Col("umid", "Market ID", "int"),
            Col("market", "Market"), Col("outcome", "Outcome"), Col("line_value", "Line", "float"),
            *(Col(f"odds_{b}", f"{b} Odds", "odds") for b in bookmakers),
            Col("best_odds", "Best Odds", "odds"), Col("best_bookmaker", "Best Bookmaker"),
            Col("sofa_close", "Sofa Closing Odds", "odds"), Col("sofa_result", "Sofa Result"),
        ]
        return cols, wide
    stmt, params = _stmt(spec.sql, spec, start, end, filters, limit=None if cap is None else cap + 1)
    result = conn.execute(stmt, params)
    rows = []
    for m in result.mappings():
        rows.append({k: _clean(v) for k, v in m.items()})
        if progress and len(rows) % PROGRESS_EVERY == 0:
            progress("fetching", spec.name, len(rows))
    if progress:
        progress("fetching", spec.name, len(rows))
    if spec.transform:
        rows = [spec.transform(r) for r in rows]
    return list(spec.columns), rows


# ── Workbook writing ─────────────────────────────────────────────────────────

_NUM_FORMATS = {
    "text": None, "int": "0", "odds": "0.00", "float": "0.00", "pct": "0.0%",
    "datetime": "yyyy-mm-dd hh:mm", "date": "yyyy-mm-dd",
}


def _col_width(col: Col, rows: list) -> float:
    longest = 0
    for r in rows[:300]:
        v = r.get(col.key)
        if v is not None:
            longest = max(longest, len(str(v)))
    return min(45, max(10, len(col.header) + 2, longest + 2))


def _all_or(values) -> str:
    return ", ".join(str(v) for v in values) if values else "All"


def write_workbook(path, sheets, summary: dict, progress: ProgressFn | None = None) -> None:
    wb = xlsxwriter.Workbook(str(path), {
        "strings_to_formulas": False,
        "strings_to_urls": False,
        "strings_to_numbers": False,
        "default_date_format": "yyyy-mm-dd hh:mm",
        "remove_timezone": True,
    })
    try:
        fmt = {k: (wb.add_format({"num_format": v}) if v else None) for k, v in _NUM_FORMATS.items()}
        bold = wb.add_format({"bold": True})
        summary_ws = wb.add_worksheet("Summary")
        summary_f = summary.get("filters") or NO_FILTERS
        for name, cols, rows in sheets:
            ws = wb.add_worksheet(name)
            if rows:
                ws.add_table(0, 0, len(rows), len(cols) - 1, {
                    "name": "tbl_" + re.sub(r"\W", "_", name),
                    "style": "Table Style Medium 2",
                    "columns": [{"header": c.header, **({"format": fmt[c.kind]} if fmt[c.kind] else {})}
                                for c in cols],
                })
                col_fmts = [fmt[c.kind] for c in cols]
                for i, r in enumerate(rows, start=1):
                    for j, c in enumerate(cols):
                        ws.write(i, j, r.get(c.key), col_fmts[j])
                    if progress and i % PROGRESS_EVERY == 0:
                        progress("writing", name, i)
                if progress:
                    progress("writing", name, len(rows))
            else:
                for i, c in enumerate(cols):
                    ws.write_string(0, i, c.header, bold)
                ws.write_string(1, 0, "No rows for this date range.")
            ws.freeze_panes(1, 0)
            for i, c in enumerate(cols):
                ws.set_column(i, i, _col_width(c, rows))

        summary_ws.set_column(0, 0, 22)
        summary_ws.set_column(1, 1, 60)
        lines = [
            ("Pregames export", None),
            ("Kickoff from", summary["date_from"]),
            ("Kickoff to", f"{summary['date_to']} (inclusive)"),
            ("Odds sheets", "Included" if summary["include_odds"] else "Not included"),
            ("Countries", _all_or(summary_f.countries)),
            ("Leagues", _all_or(summary_f.leagues)),
            ("Market IDs", _all_or(summary_f.umids)),
            ("Sheets", _all_or(summary_f.sheets)),
            ("Generated (UTC)", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")),
            ("Note", "Team Aliases and Market Types contain all rows (not date-filtered). Kickoff times are UTC."),
        ]
        for r, (a, b) in enumerate(lines):
            summary_ws.write_string(r, 0, a, bold)
            if b is not None:
                summary_ws.write_string(r, 1, str(b))
        r = len(lines) + 1
        summary_ws.write_string(r, 0, "Sheet", bold)
        summary_ws.write_string(r, 1, "Rows", bold)
        for name, _cols, rows in sheets:
            r += 1
            summary_ws.write_string(r, 0, name, bold)
            summary_ws.write_number(r, 1, len(rows))
        if progress:
            progress("saving", None, 0)
    finally:
        wb.close()


def preview(date_from: str, date_to: str, include_odds: bool = True, conn=None,
            filters: ExportFilters = NO_FILTERS) -> dict:
    start, end = parse_range(date_from, date_to)
    specs = sheet_specs(include_odds, filters.sheets)
    if conn is None:
        from database import engine  # lazy: keep this module importable without a DB
        with engine.connect() as c:
            counts = count_rows(c, specs, start, end, filters)
    else:
        counts = count_rows(conn, specs, start, end, filters)
    too_large = [n for n, c in counts.items() if c > MAX_SHEET_ROWS]
    return {
        "date_from": date_from, "date_to": date_to, "include_odds": include_odds,
        "max_rows": MAX_SHEET_ROWS,
        "filters": {"countries": list(filters.countries), "leagues": list(filters.leagues),
                    "umids": list(filters.umids), "sheets": list(filters.sheets)},
        "sheets": [{"name": n, "rows": c} for n, c in counts.items()],
        "too_large": too_large, "ok": not too_large,
    }


def build_workbook(path, date_from: str, date_to: str, include_odds: bool = True, conn=None,
                   filters: ExportFilters = NO_FILTERS, progress: ProgressFn | None = None) -> dict:
    start, end = parse_range(date_from, date_to)
    specs = sheet_specs(include_odds, filters.sheets)
    own = conn is None
    if own:
        from database import engine
        conn = engine.connect()
    try:
        sheets = []
        for spec in specs:
            extra = {"progress": progress} if progress else {}   # only pass when used
            cols, rows = fetch_sheet(conn, spec, start, end, filters=filters, cap=MAX_SHEET_ROWS, **extra)
            if len(rows) > MAX_SHEET_ROWS:
                raise ExportTooLarge({spec.name: len(rows)})
            sheets.append((spec.name, cols, rows))
    finally:
        if own:
            conn.close()
    write_workbook(path, sheets, {"date_from": date_from, "date_to": date_to, "include_odds": include_odds,
                                  "filters": filters}, progress=progress)
    return {name: len(rows) for name, _c, rows in sheets}
