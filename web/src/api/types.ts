export interface User { username: string; name: string }

export interface Summary {
  total_games: number; matched: number; unmatched: number; match_pct: number;
  countries: number; bookmakers: number; date_from: string | null; date_to: string | null;
  api_calls_used: number | null; api_call_limit: number; api_cycle_start: string;
}
export interface DailyCount { date: string; total: number; matched: number }
export interface Filters { dates: string[]; countries: string[]; bookmakers: string[] }

export type SofaFilter = 'all' | 'matched' | 'unmatched';
export interface GamesParams { date?: string; country?: string; sofa?: SofaFilter; q?: string }
export interface GameRow {
  id: number; kickoff: string; home_team: string; away_team: string; league: string;
  country: string | null; sofa_event_id: number | null; bookmakers: number;
  score_home: number | null; score_away: number | null;
}
export interface GameDetail {
  id: number; kickoff: string; home_team: string; away_team: string; league: string;
  country: string | null; sofa_event_id: number | null; sofa_status: string | null;
  score_home: number | null; score_away: number | null; bookmakers: string[];
}
export interface OddsRow {
  outcome: string | null; line_value: number | null; label: string;
  odds: Record<string, number | null>; sofa_close: number | null; sofa_winning: number | null;
}
export interface OddsMarket { umid: number; name: string; rows: OddsRow[] }
export interface GameOdds { bookmakers: string[]; markets: OddsMarket[] }
export interface GameStatistics { periods: string[]; stats: Record<string, Record<string, number | null>> }
export interface Incident {
  incident_type: string | null; incident_class: string | null; time: number | null;
  added_time: number | null; reversed_period_time: number | null; is_home: number | null;
  home_score: number | null; away_score: number | null; player_name: string | null;
  assist_player_name: string | null; player_in_name: string | null; player_out_name: string | null;
  reason: string | null; rescinded: number | null; confirmed: number | null; injury: number | null;
  manager_name: string | null; text: string | null; length: number | null;
}
export interface AliasRow { canonical_name: string; names: Record<string, string> }
export interface Aliases { sources: string[]; rows: AliasRow[] }
export interface MarketType { umid: number; canonical_name: string | null; first_seen_at: string | null; last_updated_at: string | null }
export interface BlownLead {
  sofa_event_id: number; game_id: number | null; home_name: string; away_name: string;
  score_home: number; score_away: number; match_date: string;
  scenario: 'home_blew_lead' | 'away_blew_lead'; lead_score_home: number | null;
  lead_score_away: number | null; lead_time: number | null;
}
export interface CountryRate { country: string; total: number; matched: number }
export interface LeagueRate { country: string; league: string; total: number; matched: number }
export interface MatchRates { countries: CountryRate[]; leagues: LeagueRate[] }

export interface ExportParams {
  date_from: string; date_to: string; include_odds: boolean;
  countries?: string[]; leagues?: string[]; umids?: number[]; sheets?: string[];
}
export type ExportJobState = 'queued' | 'running' | 'done' | 'error' | 'cancelled';
export interface ExportJob {
  id: string; state: ExportJobState;
  stage: 'queued' | 'counting' | 'fetching' | 'writing' | 'saving' | 'done';
  sheet: string | null; percent: number; eta_seconds: number | null; elapsed_seconds: number;
  error: string | null; error_status: number | null; filename: string | null;
}
export interface ExportPreview {
  date_from: string; date_to: string; include_odds: boolean; max_rows: number;
  sheets: { name: string; rows: number }[]; too_large: string[]; ok: boolean;
}
