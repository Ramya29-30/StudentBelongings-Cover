import { useState } from 'react';
import type { FormEvent } from 'react';
import { Link, useParams } from 'react-router-dom';
import { api } from '../api';
import { useAuth } from '../auth';
import type { Claim, User } from '../types';
import { Async, Badge, Field, Notice, Panel, Select, Tabs, TextArea, dt, money, useAction, useLoad, usePageTitle } from '../ui';
import AssessmentPanel from './AssessmentPanel';
import EvidencePanel from './EvidencePanel';
import FinancePanel from './FinancePanel';
import HistoryPanel from './HistoryPanel';
import ItemsPanel from './ItemsPanel';

type Role = 'student' | 'assessor' | 'admin';

export default function ClaimDetail({ role, base }: { role: Role; base: string }) {
  const { id } = useParams();
  const claim = useLoad(() => api<Claim>(`/claims/${id}`), [id]);
  const [tab, setTab] = useState('overview');
  usePageTitle('Claim details');
  return (
    <Async state={claim}>{c => {
      const studentOpen = role === 'student' && ['Draft', 'Pending Information'].includes(c.status);
      const evidenceOpen = role === 'student' ? ['Draft', 'Submitted', 'Pending Information'].includes(c.status) : role === 'assessor';
      const tabs = [{ id: 'overview', label: 'Overview' }, { id: 'evidence', label: 'Evidence' }, { id: 'items', label: 'Damage items' },
        { id: 'assessment', label: role === 'student' ? 'Assessment' : 'Assessment & rules' }, { id: 'finance', label: role === 'student' ? 'Payments' : 'Reserves & payments' }, { id: 'history', label: 'History' }];
      return (
        <>
          <p><Link to={`${base}/claims`}>&larr; All claims</Link></p>
          <h1>Claim {c.claim_number} <Badge text={c.status} /></h1>
          <Tabs label="Claim sections" tabs={tabs} active={tab} onChange={setTab} />
          <Panel id="overview" active={tab}><Overview claim={c} role={role} editable={studentOpen} onChange={claim.reload} /></Panel>
          <Panel id="evidence" active={tab}><EvidencePanel claim={c} canUpload={evidenceOpen} canAi={role !== 'admin' ? (role === 'assessor' || evidenceOpen) : true} onChange={claim.reload} /></Panel>
          <Panel id="items" active={tab}><ItemsPanel claim={c} role={role} onChange={claim.reload} /></Panel>
          <Panel id="assessment" active={tab}><AssessmentPanel claim={c} role={role} onChange={claim.reload} /></Panel>
          <Panel id="finance" active={tab}><FinancePanel claim={c} role={role} onChange={claim.reload} /></Panel>
          <Panel id="history" active={tab}><HistoryPanel claim={c} /></Panel>
        </>
      );
    }}</Async>
  );
}

function Overview({ claim: c, role, editable, onChange }: { claim: Claim; role: Role; editable: boolean; onChange: () => void }) {
  const { meta } = useAuth();
  const { run, busy } = useAction();
  const [reason, setReason] = useState('');
  const [er, setEr] = useState('');
  const [f, setF] = useState({ incident_date: c.incident_date, incident_type: c.incident_type, incident_location: c.incident_location, description: c.description });
  const [notes, setNotes] = useState(c.assessor_notes);
  const [assignee, setAssignee] = useState('');
  const assessors = useLoad(() => role === 'admin' ? api<User[]>('/users').then(u => u.filter(x => x.role === 'assessor' && x.is_active !== false)) : Promise.resolve([] as User[]), [role]);
  const transitions = (c.allowed_transitions ?? []).filter(t => !(role === 'student' && t === 'Submitted'));
  const needsReason = (t: string) => ['Pending Information', 'Approved for Review', 'Rejected with Reason'].includes(t);

  const save = async (e: FormEvent) => { e.preventDefault(); if (f.incident_date > new Date().toISOString().slice(0, 10)) { setEr('The incident date cannot be in the future'); return; } setEr(''); if (await run(() => api(`/claims/${c.id}`, { method: 'PUT', body: f }), 'Claim updated')) onChange(); };
  const submit = async () => { if (await run(() => api(`/claims/${c.id}/submit`, { method: 'POST' }), 'Claim submitted for assessment')) onChange(); };
  const move = async (to: string) => {
    if (needsReason(to) && !reason.trim()) { setEr(`A reason is required to move the claim to "${to}"`); return; }
    setEr('');
    if (await run(() => api(`/claims/${c.id}/status`, { method: 'POST', body: { to, reason } }), `Claim moved to ${to}`)) { setReason(''); onChange(); }
  };
  const assign = async (self: boolean) => {
    if (!self && !assignee) { setEr('Choose an assessor'); return; }
    setEr('');
    if (await run(() => api(`/claims/${c.id}/assign`, { method: 'POST', body: self ? {} : { assessor_id: Number(assignee) } }), 'Claim assigned')) onChange();
  };
  const saveNotes = () => run(() => api(`/claims/${c.id}/assessment`, { method: 'PUT', body: { assessor_notes: notes } }), 'Notes saved').then(ok => ok && onChange());
  const locked = c.status === 'Draft' || c.status === 'Closed';
  return (
    <>
      <section className="card" aria-labelledby="sum-h">
        <h2 id="sum-h" style={{ marginTop: 0 }}>Summary</h2>
        <dl className="kv">
          <dt>Policy</dt><dd>{c.policy_number}{c.policy_version_used ? ` (v${c.policy_version_used} applied)` : ''}</dd>
          <dt>Claimant</dt><dd>{c.claimant_name}</dd><dt>Item</dt><dd>{c.asset_name} ({c.asset_category})</dd>
          <dt>Incident</dt><dd>{c.incident_type} on {c.incident_date}{c.incident_location ? `, ${c.incident_location}` : ''}</dd>
          <dt>Description</dt><dd>{c.description || '-'}</dd><dt>Created</dt><dd>{dt(c.created_at)}</dd><dt>Submitted</dt><dd>{dt(c.submitted_at)}</dd>
          <dt>Estimated payable</dt><dd>{money(c.estimated_payable)}</dd>
          {c.decision_reason && <><dt>Decision reason</dt><dd>{c.decision_reason}</dd></>}
        </dl>
        {c.status === 'Pending Information' && role === 'student' && <Notice kind="warn">The assessor needs more information. Add evidence or details, then submit again.</Notice>}
      </section>
      {editable && (
        <form className="card" onSubmit={e => void save(e)} noValidate aria-label="Edit claim">
          <h3 style={{ marginTop: 0 }}>Edit claim details</h3>
          <Field label="Incident date" type="date" value={f.incident_date} onChange={e => setF(x => ({ ...x, incident_date: e.target.value }))} required />
          <Select label="What happened" value={f.incident_type} onChange={e => setF(x => ({ ...x, incident_type: e.target.value }))} options={meta?.incident_types ?? []} />
          <Field label="Location" value={f.incident_location} onChange={e => setF(x => ({ ...x, incident_location: e.target.value }))} />
          <TextArea label="Description" value={f.description} maxLength={4000} onChange={e => setF(x => ({ ...x, description: e.target.value }))} />
          <div className="row"><button type="submit" disabled={busy}>Save changes</button></div>
        </form>
      )}
      {role === 'student' && editable && <div className="card"><button disabled={busy} onClick={() => void submit()}>{c.status === 'Draft' ? 'Submit claim for assessment' : 'Re-submit with more information'}</button><p className="hint">On submission the policy rules run automatically against the policy version in force on the incident date.</p></div>}
      {role === 'assessor' && (
        <section className="card" aria-labelledby="as-h">
          <h3 id="as-h" style={{ marginTop: 0 }}>Assessment workflow</h3>
          {!c.assessor_id && !locked && <p>This claim is unassigned. <button className="secondary sm" disabled={busy} onClick={() => void assign(true)}>Assign to me</button></p>}
          {transitions.length > 0 && (
            <>
              <Field label="Reason (required for Pending Information, Approve, Reject)" value={reason} onChange={e => setReason(e.target.value)} />
              <div className="row">{transitions.map(t => <button key={t} disabled={busy} className={t.startsWith('Reject') ? 'danger' : ''} onClick={() => void move(t)}>Move to: {t}</button>)}</div>
              <p className="hint">Completing an assessment re-runs the rules and is blocked while items are unverified or unpriced. Approval is a recommendation only: no money moves until an administrator approves a reserve and a payment.</p>
            </>
          )}
          <TextArea label="Assessor notes" value={notes} onChange={e => setNotes(e.target.value)} />
          <button className="secondary" disabled={busy} onClick={() => void saveNotes()}>Save notes</button>
        </section>
      )}
      {role === 'admin' && !locked && (
        <section className="card" aria-labelledby="ad-h">
          <h3 id="ad-h" style={{ marginTop: 0 }}>Assignment</h3>
          <p>Currently assigned to: {c.assessor_id ? `assessor #${c.assessor_id}` : 'nobody'}</p>
          <Select label="Assign to assessor" value={assignee} onChange={e => setAssignee(e.target.value)} placeholder="Select…" options={(assessors.data ?? []).map(u => ({ value: u.id, label: `${u.full_name} (${u.username})` }))} />
          <button disabled={busy} onClick={() => void assign(false)}>Assign</button>
        </section>
      )}
      {er && <div className="alert error" role="alert">{er}</div>}
      {role === 'admin' && <p className="muted">Administrators monitor claims and manage reserves and payments. Assessment decisions are made by assessors.</p>}
    </>
  );
}
