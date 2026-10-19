import type { Incident } from '../../api/types';

export type IncidentKind = 'goal' | 'card' | 'substitution' | 'var' | 'period' | 'injuryTime' | 'other';
export interface IncidentView { kind: IncidentKind; label: string; detail: string; color: string }

const VAR_DETAIL: Record<string, string> = {
  goalAwarded: 'Goal awarded',
  goalNotAwarded: 'Goal not awarded',
  penaltyAwarded: 'Penalty awarded',
  penaltyNotAwarded: 'Penalty not awarded',
  cardUpgrade: 'Card upgraded',
};

export function describeIncident(i: Incident): IncidentView {
  switch (i.incident_type) {
    case 'goal': {
      const label = i.incident_class === 'penalty' ? 'Penalty goal' : i.incident_class === 'ownGoal' ? 'Own goal' : 'Goal';
      const detail = `${i.player_name ?? '—'}${i.assist_player_name ? ` (assist: ${i.assist_player_name})` : ''}`;
      return { kind: 'goal', label, detail, color: 'teal' };
    }
    case 'card': {
      const label = i.incident_class === 'red' ? 'Red card' : i.incident_class === 'yellowRed' ? 'Second yellow' : 'Yellow card';
      const color = i.incident_class === 'red' || i.incident_class === 'yellowRed' ? 'red' : 'yellow';
      const detail = `${i.player_name ?? '—'}${i.reason ? ` — ${i.reason}` : ''}${i.rescinded ? ' (rescinded)' : ''}`;
      return { kind: 'card', label, detail, color };
    }
    case 'substitution':
      return {
        kind: 'substitution', label: 'Substitution', color: 'blue',
        detail: `${i.player_out_name ?? '?'} → ${i.player_in_name ?? '?'}${i.injury ? ' (injury)' : ''}`,
      };
    case 'varDecision':
      return {
        kind: 'var', label: 'VAR', color: 'grape',
        detail: (i.incident_class && VAR_DETAIL[i.incident_class]) || i.incident_class || '—',
      };
    case 'period':
      return {
        kind: 'period', detail: '', color: 'gray',
        label: i.text === 'HT' ? 'Half time' : i.text === 'FT' ? 'Full time' : i.text || 'Period',
      };
    case 'injuryTime':
      return {
        kind: 'injuryTime', label: 'Stoppage time', color: 'gray',
        detail: i.length != null ? `${i.length} min added` : '',
      };
    default:
      return { kind: 'other', label: i.incident_type || 'Event', detail: '', color: 'gray' };
  }
}

export function incidentTeam(i: Incident, home: string, away: string): string | null {
  return i.is_home == null ? null : i.is_home ? home : away;
}

export const INCIDENT_FILTERS: { value: IncidentKind; label: string }[] = [
  { value: 'goal', label: 'Goals' }, { value: 'card', label: 'Cards' },
  { value: 'substitution', label: 'Substitutions' }, { value: 'var', label: 'VAR' },
  { value: 'period', label: 'Periods' }, { value: 'injuryTime', label: 'Stoppage time' },
];
