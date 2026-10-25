import { describe, expect, it } from 'vitest';
import { formatEta, isActive, stageLabel } from './exportProgress';
import type { ExportJob } from '../api/types';

describe('formatEta', () => {
  it('handles unknown and tiny values', () => {
    expect(formatEta(null)).toBe('Estimating…');
    expect(formatEta(3)).toBe('Almost done…');
  });
  it('rounds seconds up to multiples of 5', () => {
    expect(formatEta(37)).toBe('About 40 s left');
  });
  it('carries into minutes', () => {
    expect(formatEta(57)).toBe('About 1 min left');
    expect(formatEta(60)).toBe('About 1 min left');
    expect(formatEta(75)).toBe('About 1 min 15 s left');
    expect(formatEta(118)).toBe('About 2 min left');
  });
});

describe('stageLabel', () => {
  it('labels every stage', () => {
    expect(stageLabel({ stage: 'queued', sheet: null })).toBe('Waiting to start');
    expect(stageLabel({ stage: 'counting', sheet: null })).toBe('Counting rows');
    expect(stageLabel({ stage: 'fetching', sheet: 'Odds' })).toBe('Fetching Odds');
    expect(stageLabel({ stage: 'fetching', sheet: null })).toBe('Fetching data');
    expect(stageLabel({ stage: 'writing', sheet: 'Games' })).toBe('Writing Games');
    expect(stageLabel({ stage: 'saving', sheet: null })).toBe('Saving the file');
    expect(stageLabel({ stage: 'done', sheet: null })).toBe('Ready');
  });
});

describe('isActive', () => {
  it('is true only for queued and running', () => {
    const states: ExportJob['state'][] = ['queued', 'running', 'done', 'error', 'cancelled'];
    expect(states.map((state) => isActive({ state }))).toEqual([true, true, false, false, false]);
    expect(isActive(null)).toBe(false);
    expect(isActive(undefined)).toBe(false);
  });
});
