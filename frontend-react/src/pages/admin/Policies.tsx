import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { api } from '../../api';
import type { Asset, Plan, Policy, User } from '../../types';
import { Async, Badge, Check, Field, Notice, Panel, Select, Table, Tabs, TextArea, money, today, useAction, useLoad, usePageTitle } from '../../ui';
import { PolicySummary, TermsView } from '../../components/PolicyView';
import { PolicyCentre } from '../student/Policies';

export function AdminPolicies() {
  return (<><p><Link className="btn" to="/admin/policies/new">Create policy</Link></p><PolicyCentre base="/admin" /></>);
}

export function PolicyNew() {
  usePageTitle('Create policy');
  const nav = useNavigate();
  const students = useLoad(() => api<User[]>('/students'), []);
  const plans = useLoad(() => api<Plan[]>('/plans'), []);
  const [f, setF] = useState({ student_id: '', plan_id: '', start_date: today(), end_date: '' });
  const assets = useLoad(() => f.student_id ? api<Asset[]>(`/assets?owner_id=${f.student_id}`) : Promise.resolve([] as Asset[]), [f.student_id]);
  const [sel, setSel] = useState<number[]>([]);
  const [er, setEr] = useState<Record<string, string>>({});
  const { run, busy } = useAction();
  const set = (k: string) => (e: { target: { value: string } }) => { setF(x => ({ ...x, [k]: e.target.value })); if (k === 'student_id') setSel([]); };
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const x: Record<string, string> = {};
    if (!f.student_id) x.student_id = 'Choose the policy holder';
    if (!f.plan_id) x.plan_id = 'Choose a plan';
    if (!f.start_date) x.start_date = 'Enter the start date';
    if (!f.end_date) x.end_date = 'Enter the expiry date'; else if (f.start_date && f.end_date <= f.start_date) x.end_date = 'Expiry must be after the start date';
    setEr(x);
    if (Object.keys(x).length) return;
    let id = 0;
    if (await run(async () => { const p = await api<Policy>('/policies', { method: 'POST', body: { student_id: Number(f.student_id), plan_id: Number(f.plan_id), start_date: f.start_date, end_date: f.end_date, asset_ids: sel } }); id = p.id; }, 'Draft policy created')) nav(`/admin/policies/${id}`);
  };
  return (
    <>
      <h1>Create policy</h1>
      <Async state={students}>{st => (
        <form className="card" onSubmit={e => void submit(e)} noValidate aria-label="Create policy">
          <Select label="Policy holder" value={f.student_id} onChange={set('student_id')} options={st.map(s => ({ value: s.id, label: `${s.full_name} (${s.username})` }))} placeholder="Select…" error={er.student_id} required />
          <Select label="Coverage plan" value={f.plan_id} onChange={set('plan_id')} options={(plans.data ?? []).map(p => ({ value: p.id, label: p.name }))} placeholder="Select…" error={er.plan_id} required />
          <div className="grid cols"><Field label="Start date" type="date" value={f.start_date} onChange={set('start_date')} error={er.start_date} required /><Field label="Expiry date" type="date" value={f.end_date} onChange={set('end_date')} error={er.end_date} required /></div>
          {f.student_id && <fieldset><legend>Insured assets</legend>{(assets.data ?? []).length === 0 ? <p>This student has no registered assets.</p> :
            (assets.data ?? []).map(a => <Check key={a.id} label={`${a.name} (${a.category}, ${money(a.declared_value)})`} checked={sel.includes(a.id)} onChange={() => setSel(s => s.includes(a.id) ? s.filter(i => i !== a.id) : [...s, a.id])} />)}</fieldset>}
          <button type="submit" disabled={busy}>Create draft policy</button>
        </form>
      )}</Async>
    </>
  );
}

export function PolicyAdmin() {
  const { id } = useParams();
  usePageTitle('Policy administration');
  const pol = useLoad(() => api<Policy>(`/policies/${id}`), [id]);
  const plans = useLoad(() => api<Plan[]>('/plans'), []);
  const [tab, setTab] = useState('overview');
  const { run, busy } = useAction();
  const [er, setEr] = useState('');
  const [edit, setEdit] = useState({ plan_id: '', start_date: '', end_date: '', effective_from: '', reason: 'Policy terms updated' });
  const [tr, setTr] = useState({ reason: '', on_date: '' });
  const [reissue, setReissue] = useState({ effective_from: '', reason: 'Re-issued with current plan terms' });
  const [addAsset, setAddAsset] = useState('');
  useEffect(() => { const d = pol.data; if (d) setEdit(e => ({ ...e, plan_id: String(d.plan_id), start_date: d.start_date, end_date: d.end_date })); }, [pol.data]);
  const owner = useLoad(() => pol.data ? api<Asset[]>(`/assets?owner_id=${pol.data.student_id}`) : Promise.resolve([] as Asset[]), [pol.data?.student_id]);
  return (
    <Async state={pol}>{p => {
      const after = () => pol.reload();
      const cur = p.versions?.[p.versions.length - 1];
      const canEdit = p.status === 'Draft' || p.status === 'Active';
      const saveEdit = async (e: FormEvent) => {
        e.preventDefault();
        if (edit.end_date <= edit.start_date) { setEr('Expiry must be after the start date'); return; }
        if (p.status === 'Active' && edit.effective_from && edit.effective_from < today()) { setEr('A new version of an active policy cannot be back-dated'); return; }
        setEr('');
        const body: Record<string, unknown> = { plan_id: Number(edit.plan_id), end_date: edit.end_date, reason: edit.reason };
        if (p.status === 'Draft') body.start_date = edit.start_date;
        if (edit.effective_from) body.effective_from = edit.effective_from;
        if (await run(() => api(`/policies/${p.id}`, { method: 'PUT', body }), p.status === 'Active' ? 'Saved as a new policy version' : 'Draft updated')) after();
      };
      const transition = async (to: string) => {
        if (to === 'Cancelled' && !tr.reason.trim()) { setEr('A cancellation reason is required'); return; }
        setEr('');
        if (await run(() => api(`/policies/${p.id}/transition`, { method: 'POST', body: { to, reason: tr.reason, on_date: tr.on_date || null } }), `Policy ${to === 'Active' ? 'activated' : to.toLowerCase()}`)) after();
      };
      const nextStates = p.status === 'Draft' ? ['Active', 'Cancelled'] : p.status === 'Active' ? ['Cancelled'] : [];
      const linked = new Set((p.assets ?? []).map(a => a.id));
      return (
        <>
          <p><Link to="/admin/policies">&larr; All policies</Link></p>
          <h1>Policy {p.policy_number} <Badge text={p.status} /></h1>
          <Tabs label="Policy administration" active={tab} onChange={setTab} tabs={[{ id: 'overview', label: 'Overview & lifecycle' }, { id: 'edit', label: 'Edit / new version' }, { id: 'assets', label: 'Insured assets' }, { id: 'versions', label: 'Versions' }, { id: 'terms', label: 'Terms in force' }]} />
          {er && <div className="alert error" role="alert">{er}</div>}
          <Panel id="overview" active={tab}>
            <div className="card"><PolicySummary p={p} /></div>
            {nextStates.length > 0 && (
              <section className="card" aria-labelledby="lc-h"><h2 id="lc-h" style={{ marginTop: 0 }}>Lifecycle</h2>
                <Field label="Reason (required to cancel)" value={tr.reason} onChange={e => setTr(x => ({ ...x, reason: e.target.value }))} maxLength={300} />
                <Field label="Cancellation date (optional, defaults to today)" type="date" value={tr.on_date} onChange={e => setTr(x => ({ ...x, on_date: e.target.value }))} />
                <div className="row">{nextStates.map(s => <button key={s} className={s === 'Cancelled' ? 'danger' : ''} disabled={busy} onClick={() => void transition(s)}>{s === 'Active' ? 'Activate policy' : 'Cancel policy'}</button>)}</div>
                <p className="hint">Activation needs at least one insured asset and a future expiry date. Cancelled and expired policies are final.</p>
              </section>
            )}
          </Panel>
          <Panel id="edit" active={tab}>
            {!canEdit ? <Notice>A {p.status} policy cannot be edited.</Notice> : (
              <form className="card" onSubmit={e => void saveEdit(e)} noValidate aria-label="Edit policy">
                {p.status === 'Active' && <Notice>Changing an active policy creates a new version. Existing claims keep the version in force on their incident date.</Notice>}
                <Select label="Coverage plan" value={edit.plan_id} onChange={e => setEdit(x => ({ ...x, plan_id: e.target.value }))} options={(plans.data ?? []).map(pl => ({ value: pl.id, label: pl.name }))} />
                <Field label="Start date" type="date" value={edit.start_date} disabled={p.status === 'Active'} onChange={e => setEdit(x => ({ ...x, start_date: e.target.value }))} hint={p.status === 'Active' ? 'The start date of an active policy cannot be changed.' : undefined} />
                <Field label="Expiry date" type="date" value={edit.end_date} onChange={e => setEdit(x => ({ ...x, end_date: e.target.value }))} />
                <Field label="New version effective from" type="date" min={p.status === 'Active' ? today() : undefined} value={edit.effective_from} onChange={e => setEdit(x => ({ ...x, effective_from: e.target.value }))} hint="Leave blank for today (active) or the start date (draft)." />
                <TextArea label="Reason for change" value={edit.reason} onChange={e => setEdit(x => ({ ...x, reason: e.target.value }))} />
                <button type="submit" disabled={busy}>Save</button>
              </form>
            )}
            {p.status === 'Active' && (
              <div className="card"><h3 style={{ marginTop: 0 }}>Re-issue with current plan terms</h3>
                <p>Use this after editing the plan so this policy picks up the new terms as a new version.</p>
                <Field label="Effective from" type="date" min={today()} value={reissue.effective_from} onChange={e => setReissue(x => ({ ...x, effective_from: e.target.value }))} />
                <Field label="Reason" value={reissue.reason} onChange={e => setReissue(x => ({ ...x, reason: e.target.value }))} />
                <button className="secondary" disabled={busy} onClick={() => void run(() => api(`/policies/${p.id}/reissue`, { method: 'POST', body: { effective_from: reissue.effective_from || null, reason: reissue.reason } }), 'Re-issued as a new version').then(ok => ok && after())}>Re-issue</button></div>
            )}
          </Panel>
          <Panel id="assets" active={tab}>
            <Table caption="Insured assets" head={['Asset', 'Category', 'Value', canEdit ? 'Action' : 'Added']} numCols={[2]}>
              {(p.assets ?? []).map(a => <tr key={a.id}><td>{a.name}</td><td>{a.category}</td><td className="num">{money(a.declared_value)}</td>
                <td>{canEdit ? <button className="sm danger" disabled={busy} aria-label={`Remove ${a.name}`} onClick={() => void run(() => api(`/policies/${p.id}/assets/${a.id}`, { method: 'DELETE' }), 'Asset removed').then(ok => ok && after())}>Remove</button> : a.added_on}</td></tr>)}
            </Table>
            {canEdit && <div className="card"><Select label="Add an asset" value={addAsset} onChange={e => setAddAsset(e.target.value)} placeholder="Select…" options={(owner.data ?? []).filter(a => !linked.has(a.id)).map(a => ({ value: a.id, label: `${a.name} (${a.category})` }))} />
              <button disabled={busy || !addAsset} onClick={() => void run(() => api(`/policies/${p.id}/assets`, { method: 'POST', body: { asset_id: Number(addAsset) } }), 'Asset added').then(ok => { if (ok) { setAddAsset(''); after(); } })}>Add asset</button></div>}
          </Panel>
          <Panel id="versions" active={tab}>
            <Table caption="Policy versions" head={['Version', 'Effective from', 'Plan', 'Reason', 'Assets', 'Deductible', 'Overall limit']} numCols={[5, 6]}>
              {(p.versions ?? []).map(v => <tr key={v.version}><td>v{v.version}</td><td>{v.effective_from}</td><td>{v.plan_name}</td><td>{v.reason}</td><td>{v.insured_asset_ids.length}</td>
                <td className="num">{v.terms.deductible_type === 'percent' ? `${v.terms.deductible_value}%` : money(v.terms.deductible_value)}</td><td className="num">{money(v.terms.overall_limit)}</td></tr>)}
            </Table>
          </Panel>
          <Panel id="terms" active={tab}>{cur ? <TermsView t={cur.terms} /> : <p>No version.</p>}</Panel>
        </>
      );
    }}</Async>
  );
}
