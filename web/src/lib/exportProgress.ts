import type { ExportJob } from '../api/types';

/** "Estimating…" | "About 40 s left" | "About 2 min 5 s left" | "Almost done…" */
export function formatEta(seconds: number | null): string {
  if (seconds === null || seconds === undefined || Number.isNaN(seconds)) return 'Estimating…';
  if (seconds < 5) return 'Almost done…';
  if (seconds < 60) {
    const s = Math.ceil(seconds / 5) * 5;
    if (s < 60) return `About ${s} s left`;
  }
  const total = seconds < 60 ? 60 : Math.round(seconds / 5) * 5;
  const m = Math.floor(total / 60);
  const s = total % 60;
  return s === 0 ? `About ${m} min left` : `About ${m} min ${s} s left`;
}

/** Human label for the current step. */
export function stageLabel(job: Pick<ExportJob, 'stage' | 'sheet'>): string {
  switch (job.stage) {
    case 'queued': return 'Waiting to start';
    case 'counting': return 'Counting rows';
    case 'fetching': return job.sheet ? `Fetching ${job.sheet}` : 'Fetching data';
    case 'writing': return job.sheet ? `Writing ${job.sheet}` : 'Writing data';
    case 'saving': return 'Saving the file';
    case 'done': return 'Ready';
  }
}

export const isActive = (job: Pick<ExportJob, 'state'> | null | undefined) =>
  !!job && (job.state === 'queued' || job.state === 'running');

/** Delay before revoking a download object URL (some browsers cancel if revoked immediately). */
export const REVOKE_DELAY_MS = 1000;

export const JOB_STORAGE_KEY = 'pregames.exportJobId';
