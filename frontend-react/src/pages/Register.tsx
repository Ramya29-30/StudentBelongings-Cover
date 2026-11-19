import { useState } from 'react';
import type { FormEvent } from 'react';
import { Link, Navigate } from 'react-router-dom';
import { api, errMsg } from '../api';
import { useAuth } from '../auth';
import { ErrorBox, Field, Notice, usePageTitle } from '../ui';
import AuthShell from '../components/AuthShell';
import { SiteFooter } from './Legal';

export default function Register() {
  usePageTitle('Create an account');
  const { user, signIn } = useAuth();
  const [f, setF] = useState({ full_name: '', username: '', email: '', college: '', password: '', again: '' });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  if (user) return <Navigate to={`/${user.role}`} replace />;
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF(x => ({ ...x, [k]: e.target.value }));
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const er: Record<string, string> = {};
    if (!f.full_name.trim()) er.full_name = 'Enter your name';
    if (!/^[a-z0-9._-]{3,50}$/i.test(f.username)) er.username = 'Use 3 to 50 letters, digits, dot, dash or underscore';
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(f.email)) er.email = 'Enter a valid email address';
    if (f.password.length < 8) er.password = 'Use at least 8 characters';
    if (f.password !== f.again) er.again = 'The passwords do not match';
    setErrors(er);
    if (Object.keys(er).length) return;
    setBusy(true); setError('');
    try {
      await api('/auth/register', { method: 'POST', body: { username: f.username, full_name: f.full_name, email: f.email, college: f.college, password: f.password }, quiet401: true });
      await signIn(f.username.toLowerCase(), f.password);
    } catch (x) { setError(errMsg(x)); } finally { setBusy(false); }
  };
  return (
    <AuthShell heading="Protect what you carry to class" blurb="Create a student account to register your belongings, see transparent prices and try the full claim journey.">
      <h1 style={{ margin: 0 }}>Create your account</h1>
      <Notice kind="warn">Academic prototype. Policies, payments and claim settlements are simulated. This is not a licensed insurance product.</Notice>
      <form className="card" onSubmit={e => void submit(e)} noValidate aria-label="Create an account">
        <Field label="Full name" autoComplete="name" value={f.full_name} onChange={set('full_name')} error={errors.full_name} required />
        <Field label="Username" autoComplete="username" value={f.username} onChange={set('username')} error={errors.username} required />
        <Field label="Email" type="email" autoComplete="email" value={f.email} onChange={set('email')} error={errors.email} required />
        <Field label="College" value={f.college} onChange={set('college')} />
        <Field label="Password" type="password" autoComplete="new-password" value={f.password} onChange={set('password')} error={errors.password} required />
        <Field label="Repeat password" type="password" autoComplete="new-password" value={f.again} onChange={set('again')} error={errors.again} required />
        <ErrorBox message={error} />
        <button type="submit" disabled={busy}>{busy ? 'Creating...' : 'Create account'}</button>
      </form>
      <p>Already registered? <Link to="/login">Sign in</Link></p>
      <SiteFooter />
    </AuthShell>
  );
}
