import { describe, expect, it } from 'vitest';
import { cliCommand, EXPORT_SHEETS, presetRange, rangeDays } from './exportRanges';

const dates = ['2026-05-16', '2026-05-15', '2026-04-01'];

describe('presetRange', () => {
  it('latest is the newest day only', () => {
    expect(presetRange('latest', dates)).toEqual(['2026-05-16', '2026-05-16']);
  });
  it('last7 spans 7 days ending at the newest date', () => {
    expect(presetRange('last7', dates)).toEqual(['2026-05-10', '2026-05-16']);
  });
  it('last30 spans 30 days ending at the newest date', () => {
    expect(presetRange('last30', dates)).toEqual(['2026-04-17', '2026-05-16']);
  });
  it('returns null for no dates', () => {
    expect(presetRange('last7', [])).toBeNull();
  });
});

describe('cliCommand', () => {
  const base = 'python export_excel.py --from 2026-05-01 --to 2026-05-07';
  it('has no extra flags without options', () => {
    expect(cliCommand('2026-05-01', '2026-05-07')).toBe(base);
  });
  it('adds country and market flags', () => {
    expect(cliCommand('2026-05-01', '2026-05-07', { countries: ['Saudi Arabia'], umids: [1, 50] }))
      .toBe(`${base} --country "Saudi Arabia" --market 1 --market 50`);
  });
  it('omits --sheets when all sheets are selected', () => {
    expect(cliCommand('2026-05-01', '2026-05-07', { sheets: [...EXPORT_SHEETS] })).toBe(base);
  });
  it('adds --sheets for a subset', () => {
    expect(cliCommand('2026-05-01', '2026-05-07', { sheets: ['Games', 'Odds'] })).toBe(`${base} --sheets "Games,Odds"`);
  });
});

describe('rangeDays', () => {
  it('counts inclusive days', () => {
    expect(rangeDays('2026-05-01', '2026-05-07')).toBe(7);
    expect(rangeDays('2026-05-01', '2026-05-01')).toBe(1);
  });
});
