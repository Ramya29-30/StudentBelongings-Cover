import { render } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { vi } from 'vitest';
import App from '../App';
import { AuthProvider } from '../auth';
import { ToastProvider } from '../ui';

type Handler = unknown | ((body: any, url: string) => unknown | { __status: number; body: unknown });
export const calls: { method: string; path: string; body: any }[] = [];

/** Route table: "GET /path" -> JSON (or function). Unknown routes return 404 so a missing mock fails loudly. */
export function mockApi(routes: Record<string, Handler>) {
  calls.length = 0;
  vi.stubGlobal('fetch', vi.fn(async (url: string, init: RequestInit = {}) => {
    const method = init.method ?? 'GET';
    const path = String(url).replace(/^\/api/, '').split('?')[0];
    let body: any = undefined;
    if (typeof init.body === 'string') body = JSON.parse(init.body);
    else if (init.body instanceof FormData) body = Object.fromEntries((init.body as FormData).entries());
    calls.push({ method, path, body });
    const key = Object.keys(routes).find(k => k === `${method} ${path}`);
    if (!key) return { ok: false, status: 404, json: async () => ({ detail: `no mock for ${method} ${path}` }) };
    const h = routes[key];
    const out = typeof h === 'function' ? (h as (b: unknown, u: string) => unknown)(body, String(url)) : h;
    if (out && typeof out === 'object' && '__status' in (out as object)) { const o = out as { __status: number; body: unknown }; return { ok: o.__status < 400, status: o.__status, json: async () => o.body }; }
    return { ok: true, status: 200, json: async () => out };
  }));
}

export const user = (role: 'student' | 'admin' | 'assessor', name = 'Riya Menon') => ({ id: 1, username: 'riya', full_name: name, role, email: 'riya@example.edu', csrf_token: 'tok', expires_at: '2099-01-01T00:00:00' });
export const base = (role: 'student' | 'admin' | 'assessor') => ({ 'GET /auth/me': user(role), 'GET /meta': {}, 'GET /public-config': { banner: '', demo_mode: false } });

export function renderApp(path: string) {
  return render(<MemoryRouter initialEntries={[path]}><AuthProvider><ToastProvider><App /></ToastProvider></AuthProvider></MemoryRouter>);
}
