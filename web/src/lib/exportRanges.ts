import dayjs from 'dayjs';

export type RangePreset = 'latest' | 'last7' | 'last30';

const FMT = 'YYYY-MM-DD';

/** Range [from, to] ending at the newest data date. dates are newest-first 'YYYY-MM-DD'. */
export function presetRange(preset: RangePreset, dates: string[]): [string, string] | null {
  if (dates.length === 0) return null;
  const newest = dates[0];
  if (preset === 'latest') return [newest, newest];
  const back = preset === 'last7' ? 6 : 29;
  return [dayjs(newest).subtract(back, 'day').format(FMT), newest];
}

export const EXPORT_SHEETS = [
  'Games', 'Bookmaker Games', 'Odds', 'Exchange Ladder', 'Sofa Odds', 'Match Stats', 'Incidents',
  'Match Rates', 'Team Aliases', 'Market Types',
] as const;
export const ODDS_SHEETS: string[] = ['Odds', 'Exchange Ladder', 'Sofa Odds'];

export interface CliOptions { countries?: string[]; leagues?: string[]; umids?: number[]; sheets?: string[] }

const quote = (v: string) => `"${v.replace(/"/g, '\\"')}"`;

export function cliCommand(from: string, to: string, opts: CliOptions = {}): string {
  const parts = ['python export_excel.py', `--from ${from}`, `--to ${to}`];
  for (const c of opts.countries ?? []) parts.push(`--country ${quote(c)}`);
  for (const l of opts.leagues ?? []) parts.push(`--league ${quote(l)}`);
  for (const m of opts.umids ?? []) parts.push(`--market ${m}`);
  const sheets = opts.sheets ?? [];
  if (sheets.length > 0 && sheets.length < EXPORT_SHEETS.length) parts.push(`--sheets ${quote(sheets.join(','))}`);
  return parts.join(' ');
}

export function rangeDays(from: string, to: string): number {
  return dayjs(to).diff(dayjs(from), 'day') + 1;
}
