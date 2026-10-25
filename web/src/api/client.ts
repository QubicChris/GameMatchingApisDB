import type {
  Aliases, BlownLead, DailyCount, ExportJob, ExportParams, ExportPreview, Filters, GameDetail, GameOdds,
  GameRow, GamesParams, GameStatistics, Incident, MarketType, MatchRates, SofaSyncPlan, SofaSyncStatus, Summary, User,
} from './types';

export const UNAUTHORIZED_EVENT = 'pregames:unauthorized';

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = 'ApiError';
  }
}

function detailMessage(body: unknown, fallback: string): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) return detail.map((d) => (d as { msg?: string }).msg ?? '').filter(Boolean).join('; ') || fallback;
  return fallback;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json');
  const res = await fetch(path, { ...init, headers, credentials: 'same-origin' });
  if (res.status === 204) return undefined as T;
  const body = res.headers.get('content-type')?.includes('application/json') ? await res.json() : null;
  if (!res.ok) {
    if (res.status === 401 && !path.startsWith('/api/auth/')) window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
    throw new ApiError(res.status, detailMessage(body, `${res.status} ${res.statusText}`));
  }
  return body as T;
}

type QsValue = string | number | boolean | undefined | null | (string | number)[];

export function qs(params: Record<string, QsValue>): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (Array.isArray(v)) v.forEach((item) => sp.append(k, String(item)));
    else if (v !== undefined && v !== null && v !== '') sp.set(k, String(v));
  }
  return sp.toString();
}

async function fetchFile(url: string): Promise<{ blob: Blob; filename: string }> {
  const res = await fetch(url, { credentials: 'same-origin' });
  if (!res.ok) {
    const body = res.headers.get('content-type')?.includes('application/json') ? await res.json() : null;
    if (res.status === 401) window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
    throw new ApiError(res.status, detailMessage(body, `${res.status} ${res.statusText}`));
  }
  const cd = res.headers.get('content-disposition') ?? '';
  const filename = /filename="?([^";]+)"?/.exec(cd)?.[1] ?? 'pregames.xlsx';
  return { blob: await res.blob(), filename };
}

export const api = {
  me: () => request<User>('/api/auth/me'),
  login: (username: string, password: string) =>
    request<User>('/api/auth/login', { method: 'POST', body: JSON.stringify({ username, password }) }),
  logout: () => request<void>('/api/auth/logout', { method: 'POST' }),
  summary: () => request<Summary>('/api/summary'),
  daily: (days = 30) => request<DailyCount[]>(`/api/summary/daily?days=${days}`),
  filters: () => request<Filters>('/api/filters'),
  games: (p: GamesParams) => request<GameRow[]>(`/api/games?${qs({ ...p })}`),
  game: (id: number) => request<GameDetail>(`/api/games/${id}`),
  odds: (id: number) => request<GameOdds>(`/api/games/${id}/odds`),
  statistics: (id: number) => request<GameStatistics>(`/api/games/${id}/statistics`),
  fetchStatistics: (id: number) => request<GameStatistics>(`/api/games/${id}/statistics/fetch`, { method: 'POST' }),
  incidents: (id: number) => request<Incident[]>(`/api/games/${id}/incidents`),
  aliases: (q: string) => request<Aliases>(`/api/aliases?${qs({ q })}`),
  marketTypes: () => request<MarketType[]>('/api/market-types'),
  blownLeads: (minLead: number) => request<BlownLead[]>(`/api/blown-leads?min_lead=${minLead}`),
  matchRates: () => request<MatchRates>('/api/match-rates'),
  exportPreview: (p: ExportParams) => request<ExportPreview>(`/api/export/preview?${qs({ ...p })}`),
  downloadExport: (p: ExportParams) => fetchFile(`/api/export.xlsx?${qs({ ...p })}`),
  startExport: (p: ExportParams) =>
    request<ExportJob>('/api/export/jobs', {
      method: 'POST',
      body: JSON.stringify({ countries: [], leagues: [], umids: [], sheets: [], ...p }),
    }),
  exportJob: (id: string) => request<ExportJob>(`/api/export/jobs/${encodeURIComponent(id)}`),
  cancelExport: (id: string) =>
    request<void>(`/api/export/jobs/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  downloadExportJob: (id: string) => fetchFile(`/api/export/jobs/${encodeURIComponent(id)}/file`),
  sofaSync: () => request<SofaSyncStatus>('/api/sofa-sync'),
  sofaSyncPlan: () => request<SofaSyncPlan>('/api/sofa-sync/plan'),
  startSofaSync: () => request<SofaSyncStatus>('/api/sofa-sync/start', { method: 'POST' }),
  stopSofaSync: () => request<SofaSyncStatus>('/api/sofa-sync/stop', { method: 'POST' }),
};
