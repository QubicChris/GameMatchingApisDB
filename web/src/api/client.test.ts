import { describe, expect, it } from 'vitest';
import { qs } from './client';

describe('qs', () => {
  it('repeats array keys and skips empty values', () => {
    expect(qs({ a: 'x', b: ['p', 'q'], c: [], d: undefined, e: 2 })).toBe('a=x&b=p&b=q&e=2');
  });
  it('encodes spaces', () => {
    expect(qs({ countries: ['Saudi Arabia'] })).toContain('Saudi+Arabia');
  });
});
