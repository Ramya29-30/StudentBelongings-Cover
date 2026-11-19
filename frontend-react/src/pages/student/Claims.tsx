import { useEffect, useMemo, useState } from 'react';
import type { FormEvent } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { api } from '../../api';
import { useAuth } from '../../auth';
import type { Asset, Claim, Policy } from '../../types';
import { Async, Badge, Field, Select, Table, TextArea, money, today, useAction, useLoad, usePageTitle } from '../../ui';

export function ClaimList({ base, scope = 'all' }: { base: string; scope?: 'all' | 'mine' | 'unassigned' }) {
  usePageTitle('Claims');
  const { meta } = useAuth();
  const [status, setStatus] = useState('');
  const q = useMemo(() => { const p = new URLSearchParams(); if (status) p.set('status', status); if (scope === 'mine') p.set('assigned', 'me'); if (scope === 'unassigned') p.set('assigned', 'unassigned'); const s = p.toString(); return '/claims' + (s ? '?' + s : ''); }, [status, scope]);
  const list = useLoad(() => api<Claim[]>(q), [q]);
  const showClaimant = base !== '/student';
  return (
    <>
      <div style={{ maxWidth: 280 }}><Select label="Filter by status" value={status} onChange={e => setStatus(e.target.value)} options={meta?.claim_statuses ?? []} placeholder="All statuses" /></div>
      <Async state={list}>{rows => rows.length === 0 ? <p>No claims match.</p> : (
        <Table caption="Claims" head={['Claim', ...(showClaimant ? ['Claimant'] : []), 'Policy', 'Item', 'Incident', 'Date', 'Estimated payable', 'Status']} numCols={[showClaimant ? 6 : 5]}>
          {rows.map(c => <tr key={c.id}><td><Link to={`${base}/claims/${c.id}`}>{c.claim_number}</Link></td>{showClaimant && <td>{c.claimant_name}</td>}<td>{c.policy_number}</td><td>{c.asset_name}</td>
            <td>{c.incident_type}</td><td>{c.incident_date}</td><td className="num">{money(c.estimated_payable)}</td><td><Badge text={c.status} /></td></tr>)}
        </Table>
      )}</Async>
    </>
  );
}

export function StudentClaims() {
  return (<><h1>Claim Centre</h1><p><Link className="btn" to="/student/claims/new">Register a new claim</Link></p><ClaimList base="/student" /></>);
}

export function NewClaim() {
  usePageTitle('New claim');
  const { meta } = useAuth();
  const nav = useNavigate();
  const policies = useLoad(() => api<Policy[]>('/policies'), []);
  const assets = useLoad(() => api<Asset[]>('/assets'), []);
  const { run, busy } = useAction();
  const [f, setF] = useState({ policy_id: '', asset_id: '', incident_date: '', incident_type: '', incident_location: '', description: '' });
  const [er, setEr] = useState<Record<string, string>>({});
  const [elig, setElig] = useState<{ rule_id: string; outcome: string; reason: string }[] | null>(null);
  const set = (k: string) => (e: { target: { value: string } }) => setF(x => ({ ...x, [k]: e.target.value }));
  const active = (policies.data ?? []).filter(p => p.status === 'Active');
  const insured = (assets.data ?? []);
  useEffect(() => { setElig(null); }, [f.policy_id, f.asset_id, f.incident_date, f.incident_type]);

  const validate = () => {
    const x: Record<string, string> = {};
    if (!f.policy_id) x.policy_id = 'Choose a policy';
    if (!f.asset_id) x.asset_id = 'Choose the item that was affected';
    if (!f.incident_date) x.incident_date = 'Enter the incident date'; else if (f.incident_date > today()) x.incident_date = 'The incident date cannot be in the future';
    if (!f.incident_type) x.incident_type = 'Choose what happened';
    if (f.description.length > 4000) x.description = 'Keep the description under 4000 characters';
    setEr(x);
    return Object.keys(x).length === 0;
  };
  const check = () => { if (!validate()) return; void run(async () => { const r = await api<{ results?: typeof elig }>(`/policies/${f.policy_id}/eligibility`, { method: 'POST', body: { asset_id: Number(f.asset_id), incident_date: f.incident_date, incident_type: f.incident_type } }); setElig((r as any).results ?? (Array.isArray(r) ? r : [])); }); };
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!validate()) return;
    let id = 0;
    if (await run(async () => { const c = await api<Claim>('/claims', { method: 'POST', body: { ...f, policy_id: Number(f.policy_id), asset_id: Number(f.asset_id) } }); id = c.id; }, 'Draft claim created. Add evidence, then submit it.')) nav(`/student/claims/${id}`);
  };
  return (
    <>
      <h1>Register a claim</h1>
      <Async state={policies}>{() => active.length === 0 ? <div className="alert warn">You have no active policy, so a claim cannot be registered.</div> : (
        <form className="card" onSubmit={e => void submit(e)} noValidate aria-label="Register claim">
          <Select label="Policy" value={f.policy_id} onChange={set('policy_id')} options={active.map(p => ({ value: p.id, label: `${p.policy_number} - ${p.plan_name}` }))} placeholder="Select…" error={er.policy_id} required />
          <Select label="Affected item" value={f.asset_id} onChange={set('asset_id')} options={insured.map(a => ({ value: a.id, label: `${a.name} (${a.category})` }))} placeholder="Select…" error={er.asset_id} required />
          <Field label="Incident date" type="date" max={today()} value={f.incident_date} onChange={set('incident_date')} error={er.incident_date} required />
          <Select label="What happened" value={f.incident_type} onChange={set('incident_type')} options={meta?.incident_types ?? []} placeholder="Select…" error={er.incident_type} required />
          <Field label="Where did it happen" value={f.incident_location} onChange={set('incident_location')} maxLength={200} />
          <TextArea label="Describe the incident" value={f.description} onChange={set('description')} error={er.description} maxLength={4000} />
          <div className="row">
            <button type="button" className="secondary" onClick={check} disabled={busy}>Check eligibility first</button>
            <button type="submit" disabled={busy}>Create draft claim</button>
          </div>
          {elig && <ul aria-label="Eligibility results">{elig.map(r => <li key={r.rule_id}><Badge text={r.outcome} /> <strong>{r.rule_id}</strong> {r.reason}</li>)}</ul>}
        </form>
      )}</Async>
    </>
  );
}
