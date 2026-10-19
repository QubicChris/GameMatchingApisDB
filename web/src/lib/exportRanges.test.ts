import { describe, expect, it } from 'vitest';
import { cliCommand, presetRange, rangeDays } from './exportRanges';

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
  it('includes odds by default', () => {
    expect(cliCommand('2026-05-01', '2026-05-07', true)).toBe('python export_excel.py --from 2026-05-01 --to 2026-05-07');
  });
  it('adds --no-odds', () => {
    expect(cliCommand('2026-05-01', '2026-05-07', false)).toBe('python export_excel.py --from 2026-05-01 --to 2026-05-07 --no-odds');
  });
});

describe('rangeDays', () => {
  it('counts inclusive days', () => {
    expect(rangeDays('2026-05-01', '2026-05-07')).toBe(7);
    expect(rangeDays('2026-05-01', '2026-05-01')).toBe(1);
  });
});
