import { createContext, useCallback, useContext, useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { api, login as apiLogin, setCsrf, setUnauthorizedHandler } from './api';
import type { Meta, Role, Session } from './types';

interface AuthState { user: Session | null; ready: boolean; meta: Meta | null; notice: string; signIn: (u: string, p: string) => Promise<void>; signOut: () => Promise<void> }
const Ctx = createContext<AuthState>(null as unknown as AuthState);
export const useAuth = () => useContext(Ctx);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<Session | null>(null);
  const [meta, setMeta] = useState<Meta | null>(null);
  const [ready, setReady] = useState(false);
  const [notice, setNotice] = useState('');

  const loadMeta = useCallback(() => api<Meta>('/meta').then(setMeta).catch(() => undefined), []);

  useEffect(() => {
    setUnauthorizedHandler(() => { setUser(u => { if (u) setNotice('Your session has expired. Please sign in again.'); return null; }); setMeta(null); });
    // Restore the session from the HttpOnly cookie. The server returns a fresh CSRF token; no credential is ever readable by JS.
    api<Session>('/auth/me', { quiet401: true }).then(me => { setCsrf(me.csrf_token); setUser(me); return loadMeta(); }).catch(() => undefined).finally(() => setReady(true));
  }, [loadMeta]);

  const signIn = useCallback(async (u: string, p: string) => { const s = await apiLogin(u, p); setNotice(''); setUser(s); await loadMeta(); }, [loadMeta]);
  const signOut = useCallback(async () => {
    try { await api('/auth/logout', { method: 'POST', quiet401: true }); } catch { /* already signed out */ }
    setCsrf(''); setUser(null); setMeta(null); setNotice('');
  }, []);
  return <Ctx.Provider value={{ user, ready, meta, notice, signIn, signOut }}>{children}</Ctx.Provider>;
}

/** Client-side route guard. This is a usability layer only: the backend enforces roles on every endpoint. */
export function RequireRole({ role, children }: { role: Role; children: ReactNode }) {
  const { user, ready } = useAuth();
  const loc = useLocation();
  if (!ready) return <p role="status">Loading…</p>;
  if (!user) return <Navigate to="/login" replace state={{ from: loc.pathname }} />;
  if (user.role !== role) return <Navigate to={`/${user.role}`} replace state={{ denied: true }} />;
  return <>{children}</>;
}
