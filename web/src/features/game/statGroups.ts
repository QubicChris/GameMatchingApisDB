export type StatKind = 'count' | 'decimal' | 'pct' | 'ratio';
export interface StatDef { key: string; label: string; kind: StatKind }
export interface StatGroup { name: string; stats: StatDef[] }

export const PERIOD_LABELS: Record<string, string> = { ALL: 'Full match', '1ST': '1st half', '2ND': '2nd half' };

export const STAT_GROUPS: StatGroup[] = [
  { name: 'Match overview', stats: [
    { key: 'ball_possession', label: 'Ball possession', kind: 'pct' },
    { key: 'expected_goals', label: 'Expected goals (xG)', kind: 'decimal' },
    { key: 'total_shots', label: 'Total shots', kind: 'count' },
    { key: 'shots_on_target', label: 'Shots on target', kind: 'count' },
    { key: 'corner_kicks', label: 'Corner kicks', kind: 'count' },
    { key: 'goalkeeper_saves', label: 'Goalkeeper saves', kind: 'count' },
  ] },
  { name: 'Shots', stats: [
    { key: 'shots_off_target', label: 'Shots off target', kind: 'count' },
    { key: 'blocked_shots', label: 'Blocked shots', kind: 'count' },
    { key: 'shots_inside_box', label: 'Shots inside box', kind: 'count' },
    { key: 'shots_outside_box', label: 'Shots outside box', kind: 'count' },
    { key: 'hit_woodwork', label: 'Hit woodwork', kind: 'count' },
  ] },
  { name: 'Attack', stats: [
    { key: 'through_balls', label: 'Through balls', kind: 'count' },
    { key: 'touches_in_opp_box', label: 'Touches in opp. box', kind: 'count' },
    { key: 'offsides', label: 'Offsides', kind: 'count' },
  ] },
  { name: 'Passing', stats: [
    { key: 'passes', label: 'Passes', kind: 'count' },
    { key: 'accurate_passes', label: 'Accurate passes', kind: 'count' },
    { key: 'long_balls', label: 'Long balls', kind: 'ratio' },
    { key: 'crosses', label: 'Crosses', kind: 'ratio' },
    { key: 'final_third', label: 'Final third entries', kind: 'ratio' },
    { key: 'throw_ins', label: 'Throw-ins', kind: 'count' },
  ] },
  { name: 'Duels', stats: [
    { key: 'duel_won_pct', label: 'Duels won', kind: 'pct' },
    { key: 'ground_duels', label: 'Ground duels', kind: 'ratio' },
    { key: 'aerial_duels', label: 'Aerial duels', kind: 'ratio' },
    { key: 'dribbles', label: 'Dribbles', kind: 'ratio' },
    { key: 'dispossessed', label: 'Dispossessed', kind: 'count' },
  ] },
  { name: 'Defending', stats: [
    { key: 'tackles', label: 'Tackles', kind: 'count' },
    { key: 'interceptions', label: 'Interceptions', kind: 'count' },
    { key: 'clearances', label: 'Clearances', kind: 'count' },
    { key: 'errors_lead_to_shot', label: 'Errors leading to shot', kind: 'count' },
  ] },
  { name: 'Discipline', stats: [
    { key: 'fouls', label: 'Fouls', kind: 'count' },
    { key: 'yellow_cards', label: 'Yellow cards', kind: 'count' },
    { key: 'red_cards', label: 'Red cards', kind: 'count' },
    { key: 'free_kicks', label: 'Free kicks', kind: 'count' },
  ] },
  { name: 'Goalkeeping', stats: [
    { key: 'goal_kicks', label: 'Goal kicks', kind: 'count' },
  ] },
];

/** Formats one side's value. For ratio stats: "12/30 (40%)". */
export function formatStat(kind: StatKind, value: number | null | undefined, total?: number | null): string {
  if (value == null) return '—';
  switch (kind) {
    case 'pct': return `${Math.round(value)}%`;
    case 'decimal': return value.toFixed(2);
    case 'count': return String(Math.round(value));
    case 'ratio':
      return total != null && total > 0
        ? `${Math.round(value)}/${Math.round(total)} (${Math.round((value / total) * 100)}%)`
        : String(Math.round(value));
  }
}

export interface StatRow {
  def: StatDef;
  home: number;
  away: number;
  homeTotal: number | null;
  awayTotal: number | null;
}

/** Rows for one group and period; skips stats where home or away is missing (like the old dashboard). */
export function groupRows(group: StatGroup, stats: Record<string, number | null>): StatRow[] {
  const rows: StatRow[] = [];
  for (const def of group.stats) {
    const home = stats[`${def.key}_home`];
    const away = stats[`${def.key}_away`];
    if (home == null || away == null) continue;
    rows.push({
      def, home, away,
      homeTotal: def.kind === 'ratio' ? stats[`${def.key}_home_total`] ?? null : null,
      awayTotal: def.kind === 'ratio' ? stats[`${def.key}_away_total`] ?? null : null,
    });
  }
  return rows;
}

/** Home share 0–100 for the comparison bar; 50 when both are 0. */
export function homeShare(home: number, away: number): number {
  const sum = home + away;
  return sum > 0 ? (home / sum) * 100 : 50;
}
