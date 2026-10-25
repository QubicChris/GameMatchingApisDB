import type { SofaSyncOutcome } from '../api/types';

/** "1 h 05 min", "12 min", "45 s" from seconds. */
export function formatDuration(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  if (s < 60) return `${s} s`;
  if (s < 3600) return `${Math.floor(s / 60)} min`;
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return `${h} h ${String(m).padStart(2, '0')} min`;
}

/** Plain-English outcome for the last run. */
export function outcomeText(outcome: SofaSyncOutcome): string {
  switch (outcome) {
    case 'finished': return 'Finished — caught up or reached the call limit.';
    case 'stopped': return 'Stopped from the dashboard. The interrupted date will be redone next run.';
    case 'busy': return "Didn't start — another run was already in progress.";
    case 'error': return 'Ended with an error — see the log below.';
  }
}

export const OUTCOME_COLOR: Record<SofaSyncOutcome, string> = {
  finished: 'teal', stopped: 'gray', busy: 'yellow', error: 'red',
};

/** 0–100 for the dates progress bar; 0 when total is 0. */
export function datesPercent(done: number | null, total: number): number {
  if (!total || total <= 0) return 0;
  return Math.min(100, Math.max(0, ((done ?? 0) / total) * 100));
}

/** "25 Oct 2026, 14:03" in UTC from an ISO timestamp. */
export function formatUtc(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const p = (n: number) => String(n).padStart(2, '0');
  return `${p(d.getUTCDate())} ${months[d.getUTCMonth()]} ${d.getUTCFullYear()}, ${p(d.getUTCHours())}:${p(d.getUTCMinutes())}`;
}
