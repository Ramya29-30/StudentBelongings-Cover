import { useState } from 'react';
import type { FormEvent } from 'react';
import { api } from '../../api';
import type { Role, User } from '../../types';
import { Async, Badge, Check, Field, Modal, Select, Table, dt, useAction, useLoad, usePageTitle } from '../../ui';

const ROLES: Role[] = ['student', 'assessor', 'admin'];
const USERNAME = /^[a-z0-9._-]{3,50}$/;

export default function Users() {
  usePageTitle('Users');
  const users = useLoad(() => api<User[]>('/users'), []);
  const { run, busy } = useAction();
  const [create, setCreate] = useState(false);
  const [edit, setEdit] = useState<User | null>(null);
  const [reset, setReset] = useState<User | null>(null);
  return (
    <>
      <h1>User management</h1>
      <p><button onClick={() => setCreate(true)}>Create user</button></p>
      <Async state={users}>{rows => (
        <Table caption="Users" head={['Username', 'Name', 'Email', 'Role', 'Status', 'Last sign-in', 'Actions']}>
          {rows.map(u => (
            <tr key={u.id}><td>{u.username}</td><td>{u.full_name}</td><td>{u.email ?? '-'}</td><td>{u.role}</td><td><Badge text={u.is_active === false ? 'Disabled' : 'Active'} /></td><td>{dt(u.last_login_at)}</td>
              <td className="row">
                <button className="sm secondary" onClick={() => setEdit(u)} aria-label={`Edit ${u.username}`}>Edit</button>
                <button className="sm secondary" onClick={() => setReset(u)} aria-label={`Reset password for ${u.username}`}>Reset password</button>
                <button className={`sm ${u.is_active === false ? '' : 'danger'}`} disabled={busy} aria-label={`${u.is_active === false ? 'Enable' : 'Disable'} ${u.username}`}
                  onClick={() => void run(() => api(`/users/${u.id}`, { method: 'PUT', body: { is_active: u.is_active === false } }), u.is_active === false ? 'User enabled' : 'User disabled (sessions revoked)').then(ok => ok && users.reload())}>
                  {u.is_active === false ? 'Enable' : 'Disable'}</button>
              </td></tr>
          ))}
        </Table>
      )}</Async>
      <CreateUser open={create} onClose={() => setCreate(false)} onDone={() => { setCreate(false); users.reload(); }} />
      <EditUser user={edit} onClose={() => setEdit(null)} onDone={() => { setEdit(null); users.reload(); }} />
      <ResetPw user={reset} onClose={() => setReset(null)} />
    </>
  );
}

function CreateUser({ open, onClose, onDone }: { open: boolean; onClose: () => void; onDone: () => void }) {
  const { run, busy } = useAction();
  const [f, setF] = useState({ username: '', full_name: '', email: '', role: 'student', password: '' });
  const [er, setEr] = useState<Record<string, string>>({});
  const set = (k: string) => (e: { target: { value: string } }) => setF(x => ({ ...x, [k]: e.target.value }));
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const x: Record<string, string> = {};
    if (!USERNAME.test(f.username)) x.username = '3-50 characters: lowercase letters, digits, . _ -';
    if (!f.full_name.trim()) x.full_name = 'Enter the full name';
    if (f.email && !/^\S+@\S+\.\S+$/.test(f.email)) x.email = 'Enter a valid email address';
    if (f.password.length < 12) x.password = 'Use at least 12 characters (the server also enforces its own password policy)';
    setEr(x);
    if (Object.keys(x).length) return;
    if (await run(() => api('/users', { method: 'POST', body: { ...f, email: f.email || null } }), 'User created')) { setF({ username: '', full_name: '', email: '', role: 'student', password: '' }); onDone(); }
  };
  return (
    <Modal title="Create user" open={open} onClose={onClose}>
      <form onSubmit={e => void submit(e)} noValidate aria-label="Create user">
        <Field label="Username" value={f.username} onChange={set('username')} error={er.username} autoComplete="off" required />
        <Field label="Full name" value={f.full_name} onChange={set('full_name')} error={er.full_name} required />
        <Field label="Email" type="email" value={f.email} onChange={set('email')} error={er.email} />
        <Select label="Role" value={f.role} onChange={set('role')} options={ROLES} />
        <Field label="Initial password" type="password" value={f.password} onChange={set('password')} error={er.password} autoComplete="new-password" required />
        <div className="row"><button type="submit" disabled={busy}>Create</button><button type="button" className="secondary" onClick={onClose}>Cancel</button></div>
      </form>
    </Modal>
  );
}

function EditUser({ user, onClose, onDone }: { user: User | null; onClose: () => void; onDone: () => void }) {
  const { run, busy } = useAction();
  const [f, setF] = useState({ full_name: '', email: '', role: 'student', is_active: true });
  const [seen, setSeen] = useState<number | null>(null);
  if (user && seen !== user.id) { setSeen(user.id); setF({ full_name: user.full_name, email: user.email ?? '', role: user.role, is_active: user.is_active !== false }); }
  const [er, setEr] = useState('');
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!f.full_name.trim()) { setEr('Enter the full name'); return; }
    if (f.email && !/^\S+@\S+\.\S+$/.test(f.email)) { setEr('Enter a valid email address'); return; }
    setEr('');
    if (await run(() => api(`/users/${user!.id}`, { method: 'PUT', body: { full_name: f.full_name, email: f.email || null, role: f.role, is_active: f.is_active } }), 'User updated')) { setSeen(null); onDone(); }
  };
  return (
    <Modal title={`Edit ${user?.username ?? ''}`} open={!!user} onClose={onClose}>
      <form onSubmit={e => void submit(e)} noValidate aria-label="Edit user">
        <Field label="Full name" value={f.full_name} onChange={e => setF(x => ({ ...x, full_name: e.target.value }))} required />
        <Field label="Email" type="email" value={f.email} onChange={e => setF(x => ({ ...x, email: e.target.value }))} />
        <Select label="Role" value={f.role} onChange={e => setF(x => ({ ...x, role: e.target.value }))} options={ROLES} />
        <Check label="Account active" checked={f.is_active} onChange={e => setF(x => ({ ...x, is_active: e.target.checked }))} />
        {er && <div className="alert error" role="alert">{er}</div>}
        <div className="row"><button type="submit" disabled={busy}>Save</button><button type="button" className="secondary" onClick={onClose}>Cancel</button></div>
      </form>
    </Modal>
  );
}

function ResetPw({ user, onClose }: { user: User | null; onClose: () => void }) {
  const { run, busy } = useAction();
  const [pw, setPw] = useState('');
  const [er, setEr] = useState('');
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (pw.length < 12) { setEr('Use at least 12 characters'); return; }
    setEr('');
    if (await run(() => api(`/users/${user!.id}/reset-password`, { method: 'POST', body: { new_password: pw } }), 'Password reset; the user\'s sessions were signed out')) { setPw(''); onClose(); }
  };
  return (
    <Modal title={`Reset password for ${user?.username ?? ''}`} open={!!user} onClose={onClose}>
      <form onSubmit={e => void submit(e)} noValidate aria-label="Reset password">
        <Field label="New password" type="password" value={pw} onChange={e => setPw(e.target.value)} error={er} autoComplete="new-password" required />
        <div className="row"><button type="submit" disabled={busy}>Reset password</button><button type="button" className="secondary" onClick={onClose}>Cancel</button></div>
      </form>
    </Modal>
  );
}
