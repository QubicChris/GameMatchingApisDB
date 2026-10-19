import { describe, it, expect } from 'vitest';
import {
  bestBookmakers, formatKickoff, formatOdd, formatScore, incidentMinute, matchRateColor, ratioPct,
} from './format';

describe('format', () => {
  it('formatOdd', () => {
    expect(formatOdd(1.849)).toBe('1.85');
    expect(formatOdd(null)).toBe('—');
  });
  it('formatScore', () => {
    expect(formatScore(2, 0)).toBe('2 – 0');
    expect(formatScore(null, 1)).toBe('—');
  });
  it('incidentMinute', () => {
    expect(incidentMinute(45, 999)).toBe("45'");
    expect(incidentMinute(90, 3)).toBe("90'+3");
    expect(incidentMinute(12, null)).toBe("12'");
    expect(incidentMinute(null, null)).toBe('—');
  });
  it('bestBookmakers', () => {
    expect(bestBookmakers({ A: 1.9, B: 2.0, C: 2.0, D: null })).toEqual(['B', 'C']);
    expect(bestBookmakers({ A: null })).toEqual([]);
  });
  it('ratioPct', () => {
    expect(ratioPct(1, 4)).toBe(25);
    expect(ratioPct(1, 0)).toBe(0);
  });
  it('formatKickoff', () => {
    expect(formatKickoff('2026-05-16T07:30:00')).toBe('16 May 2026, 07:30');
  });
  it('matchRateColor', () => {
    expect(matchRateColor(80)).toBe('teal');
    expect(matchRateColor(49.9)).toBe('red');
  });
});
