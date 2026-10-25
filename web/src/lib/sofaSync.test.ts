import { describe, expect, it } from 'vitest';
import { datesPercent, formatDuration, formatUtc, outcomeText } from './sofaSync';

describe('formatDuration', () => {
  it('formats seconds, minutes and hours', () => {
    expect(formatDuration(45)).toBe('45 s');
    expect(formatDuration(720)).toBe('12 min');
    expect(formatDuration(3900)).toBe('1 h 05 min');
  });
});

describe('outcomeText', () => {
  it('covers every outcome', () => {
    expect(outcomeText('finished')).toBe('Finished — caught up or reached the call limit.');
    expect(outcomeText('stopped')).toBe('Stopped from the dashboard. The interrupted date will be redone next run.');
    expect(outcomeText('busy')).toBe("Didn't start — another run was already in progress.");
    expect(outcomeText('error')).toBe('Ended with an error — see the log below.');
  });
});

describe('datesPercent', () => {
  it('computes and clamps', () => {
    expect(datesPercent(1, 3)).toBeCloseTo(33.33, 1);
    expect(datesPercent(null, 3)).toBe(0);
    expect(datesPercent(5, 3)).toBe(100);
    expect(datesPercent(1, 0)).toBe(0);
  });
});

describe('formatUtc', () => {
  it('formats in UTC', () => {
    expect(formatUtc('2026-10-25T14:03:59+00:00')).toBe('25 Oct 2026, 14:03');
  });
});
