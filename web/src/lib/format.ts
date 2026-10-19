import dayjs from 'dayjs';

export const DASH = '—';
export const formatNumber = (n: number | null | undefined) => (n == null ? DASH : n.toLocaleString('en-US'));
export const ratioPct = (part: number, total: number) => (total ? (part / total) * 100 : 0);
export const formatPct = (pct: number | null | undefined, digits = 0) => (pct == null ? DASH : `${pct.toFixed(digits)}%`);
export const formatOdd = (v: number | null | undefined) => (v == null ? DASH : v.toFixed(2));
export const formatKickoff = (iso: string) => dayjs(iso).format('DD MMM YYYY, HH:mm');
export const formatTime = (iso: string) => dayjs(iso).format('HH:mm');
export const formatDateLong = (isoDate: string) => dayjs(isoDate).format('ddd D MMM YYYY');
export const formatScore = (h: number | null | undefined, a: number | null | undefined) =>
  h == null || a == null ? DASH : `${h} – ${a}`;
/** 45' / 90'+3 — added_time 0 and 999 (period markers) are not shown, like the old dashboard. */
export const incidentMinute = (time: number | null, added: number | null) =>
  time == null ? DASH : `${time}'${added != null && added !== 0 && added !== 999 ? `+${added}` : ''}`;
/** Bookmaker names holding the highest price in a row (empty when there are no prices). */
export function bestBookmakers(odds: Record<string, number | null>): string[] {
  const vals = Object.values(odds).filter((v): v is number => v != null);
  if (!vals.length) return [];
  const max = Math.max(...vals);
  return Object.entries(odds).filter(([, v]) => v === max).map(([k]) => k);
}
export const matchRateColor = (pct: number) => (pct >= 80 ? 'teal' : pct >= 50 ? 'yellow' : 'red');
