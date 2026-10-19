import { describe, it, expect } from 'vitest';
import type { Incident } from '../../api/types';
import { describeIncident, incidentTeam } from './incidents';

const base: Incident = {
  incident_type: null, incident_class: null, time: null, added_time: null, reversed_period_time: null,
  is_home: null, home_score: null, away_score: null, player_name: null, assist_player_name: null,
  player_in_name: null, player_out_name: null, reason: null, rescinded: null, confirmed: null, injury: null,
  manager_name: null, text: null, length: null,
};
const mk = (o: Partial<Incident>): Incident => ({ ...base, ...o });

describe('describeIncident', () => {
  it('goal variants', () => {
    expect(describeIncident(mk({ incident_type: 'goal', player_name: 'A' }))).toMatchObject({ kind: 'goal', label: 'Goal', detail: 'A', color: 'teal' });
    expect(describeIncident(mk({ incident_type: 'goal', incident_class: 'penalty', player_name: 'A' })).label).toBe('Penalty goal');
    expect(describeIncident(mk({ incident_type: 'goal', incident_class: 'ownGoal' })).label).toBe('Own goal');
    expect(describeIncident(mk({ incident_type: 'goal' })).detail).toBe('—');
  });
  it('goal with assist', () => {
    expect(describeIncident(mk({ incident_type: 'goal', player_name: 'A', assist_player_name: 'B' })).detail).toBe('A (assist: B)');
  });
  it('cards', () => {
    expect(describeIncident(mk({ incident_type: 'card', incident_class: 'red', player_name: 'P' }))).toMatchObject({ label: 'Red card', color: 'red' });
    expect(describeIncident(mk({ incident_type: 'card', incident_class: 'yellowRed' }))).toMatchObject({ label: 'Second yellow', color: 'red' });
    expect(describeIncident(mk({ incident_type: 'card', incident_class: 'yellow', player_name: 'P' }))).toMatchObject({ label: 'Yellow card', color: 'yellow' });
    expect(describeIncident(mk({ incident_type: 'card', incident_class: 'yellow', player_name: 'P', reason: 'Foul', rescinded: 1 })).detail).toBe('P — Foul (rescinded)');
  });
  it('substitution', () => {
    expect(describeIncident(mk({ incident_type: 'substitution', player_out_name: 'O', player_in_name: 'I' }))).toMatchObject({ kind: 'substitution', detail: 'O → I', color: 'blue' });
    expect(describeIncident(mk({ incident_type: 'substitution', player_out_name: 'O', injury: 1 })).detail).toBe('O → ? (injury)');
  });
  it('VAR', () => {
    expect(describeIncident(mk({ incident_type: 'varDecision', incident_class: 'goalAwarded' }))).toMatchObject({ kind: 'var', detail: 'Goal awarded', color: 'grape' });
    expect(describeIncident(mk({ incident_type: 'varDecision', incident_class: 'weird' })).detail).toBe('weird');
    expect(describeIncident(mk({ incident_type: 'varDecision' })).detail).toBe('—');
  });
  it('period', () => {
    expect(describeIncident(mk({ incident_type: 'period', text: 'HT' })).label).toBe('Half time');
    expect(describeIncident(mk({ incident_type: 'period', text: 'FT' })).label).toBe('Full time');
    expect(describeIncident(mk({ incident_type: 'period', text: 'ET' })).label).toBe('ET');
    expect(describeIncident(mk({ incident_type: 'period' })).label).toBe('Period');
  });
  it('injury time', () => {
    expect(describeIncident(mk({ incident_type: 'injuryTime', length: 4 }))).toMatchObject({ kind: 'injuryTime', detail: '4 min added' });
    expect(describeIncident(mk({ incident_type: 'injuryTime' })).detail).toBe('');
  });
  it('unknown', () => {
    expect(describeIncident(mk({ incident_type: 'foo' }))).toMatchObject({ kind: 'other', label: 'foo', detail: '' });
    expect(describeIncident(mk({}))).toMatchObject({ kind: 'other', label: 'Event' });
  });
});

describe('incidentTeam', () => {
  it('maps is_home', () => {
    expect(incidentTeam(mk({ is_home: 1 }), 'H', 'A')).toBe('H');
    expect(incidentTeam(mk({ is_home: 0 }), 'H', 'A')).toBe('A');
    expect(incidentTeam(mk({ is_home: null }), 'H', 'A')).toBeNull();
  });
});
