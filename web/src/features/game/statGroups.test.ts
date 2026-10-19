import { describe, it, expect } from 'vitest';
import { STAT_GROUPS, formatStat, groupRows, homeShare } from './statGroups';

describe('formatStat', () => {
  it('handles each kind', () => {
    expect(formatStat('pct', 55.4)).toBe('55%');
    expect(formatStat('decimal', 1.5)).toBe('1.50');
    expect(formatStat('count', 7.2)).toBe('7');
    expect(formatStat('ratio', 12, 30)).toBe('12/30 (40%)');
  });
  it('handles null and missing totals', () => {
    expect(formatStat('count', null)).toBe('—');
    expect(formatStat('pct', undefined)).toBe('—');
    expect(formatStat('ratio', 5, 0)).toBe('5');
    expect(formatStat('ratio', 5)).toBe('5');
  });
});

describe('groupRows', () => {
  it('skips stats with a missing side and reads totals', () => {
    const passing = STAT_GROUPS.find((g) => g.name === 'Passing')!;
    const rows = groupRows(passing, {
      passes_home: 400, passes_away: 300, accurate_passes_home: 350, accurate_passes_away: null,
      long_balls_home: 12, long_balls_away: 10, long_balls_home_total: 30, long_balls_away_total: 25,
    });
    expect(rows.map((r) => r.def.key)).toEqual(['passes', 'long_balls']);
    expect(rows[1].homeTotal).toBe(30);
    expect(rows[1].awayTotal).toBe(25);
    expect(rows[0].homeTotal).toBeNull();
  });
});

describe('homeShare', () => {
  it('computes share', () => {
    expect(homeShare(0, 0)).toBe(50);
    expect(homeShare(3, 1)).toBe(75);
    expect(homeShare(0, 4)).toBe(0);
  });
});
