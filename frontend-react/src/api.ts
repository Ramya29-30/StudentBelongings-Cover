import type { Session } from './types';

/** Thin typed fetch wrapper. Browser auth = HttpOnly session cookie (set by the server) + X-CSRF-Token on writes. No secrets live in JS. */
export class ApiError extends Error {
  constructor(message: string, public status: number, public requestId?: string) { super(message); }
}

let csrf = '';
let onUnauthorized: () => void = () => undefined;
export const setCsrf = (t: string) => { csrf = t; };
export const setUnauthorizedHandler = (fn: () => void) => { onUnauthorized = fn; };

function messageFrom(data: any, status: number): string {
  const d = data?.detail;
  if (Array.isArray(d)) return d.map((e: any) => `${(e.loc ?? []).slice(1).join('.')}: ${e.msg}`).join('; ');
  return typeof d === 'string' ? d : `Request failed (HTTP ${status})`;
}

export async function api<T = any>(path: string, opts: { method?: string; body?: unknown; form?: FormData; quiet401?: boolean } = {}): Promise<T> {
  const method = opts.method ?? 'GET';
  const headers: Record<string, string> = {};
  let body: BodyInit | undefined;
  if (opts.form) body = opts.form;
  else if (opts.body !== undefined) { headers['Content-Type'] = 'application/json'; body = JSON.stringify(opts.body); }
  if (method !== 'GET' && csrf) headers['X-CSRF-Token'] = csrf;
  let res: Response;
  try {
    res = await fetch('/api' + path, { method, headers, body, credentials: 'same-origin' });
  } catch {
    throw new ApiError('Cannot reach the server. Check that the backend is running.', 0);
  }
  if (res.status === 204) return null as T;
  const data = await res.json().catch(() => ({}));
  if (res.status === 401 && !opts.quiet401) onUnauthorized();
  if (!res.ok) throw new ApiError(messageFrom(data, res.status), res.status, data?.error?.request_id);
  return data as T;
}

export const login = async (username: string, password: string): Promise<Session> => {
  const r = await api<{ user: any; csrf_token: string; expires_at: string }>('/auth/login', { method: 'POST', body: { username, password }, quiet401: true });
  setCsrf(r.csrf_token);
  return { ...r.user, csrf_token: r.csrf_token, expires_at: r.expires_at };
};
/** POST that returns the raw streaming Response (used by CoverMate AI's server-sent events). Same cookie + CSRF rules as api(). */
export async function apiStream(path: string, body: unknown): Promise<Response> {
  let res: Response;
  try {
    res = await fetch('/api' + path, { method: 'POST', headers: { 'Content-Type': 'application/json', ...(csrf ? { 'X-CSRF-Token': csrf } : {}) }, body: JSON.stringify(body), credentials: 'same-origin' });
  } catch {
    throw new ApiError('Cannot reach the server. Check that the backend is running.', 0);
  }
  if (res.status === 401) onUnauthorized();
  if (!res.ok) { const data = await res.json().catch(() => ({})); throw new ApiError(messageFrom(data, res.status), res.status); }
  return res;
}
export const evidenceUrl = (claimId: number, evId: number) => `/api/claims/${claimId}/evidence/${evId}/file`;
export const errMsg = (e: unknown) => (e instanceof Error ? e.message : String(e));
