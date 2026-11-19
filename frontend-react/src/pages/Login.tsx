import { useState } from 'react';
import type { FormEvent } from 'react';
import { Link, Navigate, useLocation } from 'react-router-dom';
import { api, errMsg } from '../api';
import { useAuth } from '../auth';
import { ErrorBox, Field, Notice, useLoad, usePageTitle } from '../ui';
import AuthShell from '../components/AuthShell';
import { SiteFooter } from './Legal';

interface Demo { username: string; password: string; role: string; label: string }

export default function Login() {
  usePageTitle('Sign in');
  const { user, signIn, notice } = useAuth();
  const loc = useLocation();
  const [username, setU] = useState('');
  const [password, setP] = useState('');
  const [errors, setErrors] = useState<{ username?: string; password?: string }>({});
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const demo = useLoad(() => api<Demo[]>('/auth/demo-accounts').catch(() => [] as Demo[]), []);
  if (user) return <Navigate to={`/${user.role}`} replace />;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const er: typeof errors = {};
    if (!username.trim()) er.username = 'Enter your username';
    if (!password) er.password = 'Enter your password';
    setErrors(er);
    if (Object.keys(er).length) return;
    setBusy(true); setError('');
    try { await signIn(username, password); } catch (x) { setError(errMsg(x)); } finally { setBusy(false); }
  };
  const denied = (loc.state as { denied?: boolean } | null)?.denied;
  return (
    <AuthShell heading="Welcome back" blurb="Sign in to manage your belongings, policies and claims, and to ask CoverMate AI about your cover.">
      <div><h1 style={{ margin: 0 }}>Sign in</h1>
      <p className="muted" style={{ margin: '.2rem 0 0' }}>Academic prototype for student personal belongings insurance.</p></div>
      {notice && <Notice kind="warn">{notice}</Notice>}
      {denied && <Notice kind="warn">You do not have access to that page.</Notice>}
      <form className="card" onSubmit={e => void submit(e)} noValidate aria-label="Sign in">
        <Field label="Username" name="username" autoComplete="username" value={username} onChange={e => setU(e.target.value)} error={errors.username} required />
        <Field label="Password" name="password" type="password" autoComplete="current-password" value={password} onChange={e => setP(e.target.value)} error={errors.password} required />
        <ErrorBox message={error} />
        <button type="submit" disabled={busy}>{busy ? 'Signing in…' : 'Sign in'}</button>
      </form>
      <p>New student? <Link to="/register">Create an account</Link></p>
      {demo.data && demo.data.length > 0 && (
        <section className="card" aria-labelledby="demo-h">
          <h2 id="demo-h" style={{ marginTop: 0 }}>Demo accounts (development only)</h2>
          <ul>{demo.data.map(d => <li key={d.username}>{d.label}: <code>{d.username}</code> / <code>{d.password}</code>{' '}
            <button className="secondary sm" type="button" onClick={() => { setU(d.username); setP(d.password); }}>Fill</button></li>)}</ul>
        </section>
      )}
      <SiteFooter />
    </AuthShell>
  );
}
