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

export function cliCommand(from: string, to: string, includeOdds: boolean): string {
  return `python export_excel.py --from ${from} --to ${to}${includeOdds ? '' : ' --no-odds'}`;
}

export function rangeDays(from: string, to: string): number {
  return dayjs(to).diff(dayjs(from), 'day') + 1;
}
