import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { Camera, Loader2, Upload } from 'lucide-react';
import { api, errMsg } from '../../api';
import type { AssetV3, Capabilities, Category, ClaimV3 } from '../../types3';
import { AiReport, DecisionPanel } from '../../components/Report';
import { Async, Badge, ErrorBox, Field, Notice, Select, Table, TextArea, money, today, useAction, useLoad, usePageTitle } from '../../ui';

const STEPS = ['Select asset', 'Incident details', 'Upload photos', 'Submit claim', 'AI verification', 'AI report', 'Decision'];
export function Stepper({ step }: { step: number }) {
  return (
    <ol className="stepper" aria-label="Claim progress">
      {STEPS.map((s, i) => <li key={s} aria-current={i + 1 === step ? 'step' : undefined} className={i + 1 < step ? 'done' : i + 1 === step ? 'now' : ''}><span>{i + 1}</span> {s}</li>)}
    </ol>
  );
}

const INCIDENTS = ['Accidental Damage', 'Liquid Damage', 'Theft', 'Loss', 'Fire', 'Intentional Damage'];

/** Steps 1 and 2: choose the insured asset and describe the incident. Creates the claim, then continues on the claim page. */
export function NewClaim() {
  usePageTitle('Submit a claim');
  const nav = useNavigate();
  const assets = useLoad(() => api<AssetV3[]>('/v2/assets'), []);
  const cats = useLoad(() => api<Category[]>('/v2/categories'), []);
  const [step, setStep] = useState(1);
  const [aid, setAid] = useState('');
  const [f, setF] = useState({ date: today(), type: 'Accidental Damage', damage: '', desc: '', est: '' });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const { run, busy } = useAction();
  const insured = (assets.data ?? []).filter(a => a.policy);
  const asset = insured.find(a => a.id === Number(aid));
  const cat = (cats.data ?? []).find(c => c.name === asset?.category);
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF(x => ({ ...x, [k]: e.target.value }));
  const go = async (e: FormEvent) => {
    e.preventDefault();
    const er: Record<string, string> = {};
    if (!f.damage) er.damage = 'Choose the type of damage';
    if (f.desc.trim().length < 15) er.desc = 'Describe what happened in at least 15 characters';
    if (f.est && !(Number(f.est) > 0)) er.est = 'Enter a positive amount or leave blank';
    setErrors(er);
    if (Object.keys(er).length) return;
    let id = 0;
    const ok = await run(async () => {
      const c = await api<ClaimV3>('/v2/claims', { method: 'POST', body: { asset_id: Number(aid), incident_date: f.date, incident_type: f.type, damage_type: f.damage, description: f.desc, estimated_repair_cost: f.est ? Number(f.est) : undefined } });
      id = c.id;
    });
    if (ok) nav(`/student/claims/${id}`);
  };
  return (
    <>
      <h1>Submit a claim</h1>
      <Stepper step={step} />
      <Async state={assets}>{() => insured.length === 0 ? <Notice>You need an insured asset to submit a claim. <Link to="/student/assets">Register and insure an asset</Link>.</Notice> : (
        step === 1 ? (
          <section className="card"><h2 style={{ marginTop: 0 }}>Step 1: select the insured asset</h2>
            <Select label="Insured asset" value={aid} onChange={e => { setAid(e.target.value); setF(x => ({ ...x, damage: '' })); }} options={insured.map(a => ({ value: a.id, label: `${a.name} (${a.category}, ${a.policy?.policy_number})` }))} placeholder="Choose an asset" />
            <button type="button" disabled={!asset} onClick={() => setStep(2)}>Continue</button></section>
        ) : (
          <form className="card" onSubmit={e => void go(e)} noValidate aria-label="Incident details">
            <h2 style={{ marginTop: 0 }}>Step 2: what happened to your {asset?.category.toLowerCase()}?</h2>
            <div className="grid cols">
              <Field label="Incident date" type="date" max={today()} value={f.date} onChange={set('date')} required />
              <Select label="Type of incident" value={f.type} onChange={set('type')} options={INCIDENTS} hint="Theft and loss are not covered by these policies." />
              <Select label="Type of damage" value={f.damage} onChange={set('damage')} options={cat?.damage_types ?? []} placeholder="Choose the damage" error={errors.damage} required />
              <Field label="Estimated repair cost (INR), if known" type="number" min="1" value={f.est} onChange={set('est')} error={errors.est} hint="Optional. The server checks it and never pays more than the policy limit." />
            </div>
            <TextArea label="Describe the incident" value={f.desc} onChange={set('desc')} maxLength={2000} error={errors.desc} required hint="The description is compared with the photos." />
            <div className="row"><button type="button" className="secondary" onClick={() => setStep(1)}>Back</button><button type="submit" disabled={busy}>{busy ? 'Saving...' : 'Continue to photos'}</button></div>
          </form>))}</Async>
    </>
  );
}

/** Steps 3 to 7 for an existing claim: add photos, run verification, read the report and the decision. */
export function ClaimWorkspace({ staff = false, backTo = '/student/claims' }: { staff?: boolean; backTo?: string }) {
  const { id } = useParams();
  const claim = useLoad(() => api<ClaimV3>(`/v2/claims/${id}`), [id]);
  const caps = useLoad(() => api<Capabilities>('/v2/ai/capabilities').catch(() => null), []);
  const [files, setFiles] = useState<File[]>([]);
  const [previews, setPreviews] = useState<string[]>([]);
  const [verifying, setVerifying] = useState(false);
  const [err, setErr] = useState('');
  const [reason, setReason] = useState('');
  const [inputKey, setInputKey] = useState(0);
  const { run, busy } = useAction();
  usePageTitle(claim.data ? `Claim ${claim.data.claim_number}` : 'Claim');
  useEffect(() => { const u = files.map(f => URL.createObjectURL(f)); setPreviews(u); return () => u.forEach(x => URL.revokeObjectURL(x)); }, [files]);
  const c = claim.data;
  const open = c && (c.status === 'Submitted' || c.status === 'More Evidence Required');
  const step = !c ? 3 : open ? (c.images?.length ? 4 : 3) : verifying ? 5 : c.status === 'Exceptional Review Required' || c.status === 'Rejected' || c.status === 'Settled' || c.status === 'Approved' ? 7 : 6;

  const upload = async () => {
    if (!c) return;
    setErr('');
    for (const f of files) {
      const form = new FormData(); form.set('file', f);
      try { await api(`/v2/claims/${c.id}/images`, { method: 'POST', form }); } catch (e) { setErr(`${f.name}: ${errMsg(e)}`); claim.reload(); return; }
    }
    setFiles([]); setInputKey(k => k + 1);
    claim.reload();
  };
  const verify = async () => {
    if (!c) return;
    setVerifying(true); setErr('');
    try { await api(`/v2/claims/${c.id}/verify`, { method: 'POST' }); } catch (e) { setErr(errMsg(e)); }
    setVerifying(false); claim.reload();
  };
  const decide = async (action: 'approve' | 'reject') => { if (await run(() => api(`/v2/claims/${id}/review`, { method: 'POST', body: { action, reason } }), action === 'approve' ? 'Claim approved and settled (simulated).' : 'Claim rejected.')) { setReason(''); claim.reload(); } };

  return (
    <>
      <p><Link to={backTo}>Back to claims</Link></p>
      <Async state={claim}>{x => (
        <>
          <div className="row spread"><h1 style={{ margin: 0 }}>Claim {x.claim_number}</h1><Badge text={x.status} /></div>
          {!staff && <Stepper step={step} />}
          <section className="card"><dl className="kv"><dt>Asset</dt><dd>{x.asset_name} ({x.asset_category})</dd><dt>Policy</dt><dd>{x.policy_number}</dd><dt>Incident</dt><dd>{x.incident_type} on {x.incident_date}</dd>
            <dt>Damage</dt><dd>{x.damage_type}</dd><dt>Description</dt><dd>{x.description}</dd><dt>Estimate given</dt><dd>{x.estimated_repair_cost ? money(x.estimated_repair_cost) : 'None'}</dd>
            {staff && <><dt>Student</dt><dd>{x.claimant_name}</dd></>}</dl></section>
          {caps.data?.effective_mode === 'development_simulation' && open && <Notice kind="warn">Development simulation is on: photos will be checked for quality and duplicates, but damage will be assumed from your form.</Notice>}
          {caps.data && caps.data.effective_mode === 'limited' && open && !staff && <Notice kind="info">{caps.data.note}</Notice>}
          {!staff && open && (
            <section className="card" aria-labelledby="up-h">
              <h2 id="up-h" style={{ marginTop: 0 }}>{x.status === 'More Evidence Required' ? 'More evidence is needed' : 'Step 3: upload damage photos'}</h2>
              {x.status === 'More Evidence Required' && x.decision_reason && <Notice kind="warn">{x.decision_reason}</Notice>}
              <p className="muted">Up to 5 JPEG or PNG photos, 8 MB each. Show the damaged area close up and the whole item in good light.</p>
              {(x.images ?? []).length > 0 && <div className="thumbs">{x.images?.map(im => <img key={im.id} src={`/api/v2/claims/${x.id}/images/${im.id}/file`} alt={`Uploaded ${im.original_name}`} />)}</div>}
              <Field label="Add photos" type="file" accept=".jpg,.jpeg,.png" multiple key={inputKey} onChange={e => setFiles(Array.from(e.target.files ?? []))} />
              {previews.length > 0 && <div className="thumbs">{previews.map((u, i) => <img key={u} src={u} alt={`Selected ${files[i]?.name}`} />)}</div>}
              <ErrorBox message={err} />
              <div className="row">
                <button type="button" className="secondary" disabled={!files.length || busy} onClick={() => void upload()}><Upload size={16} aria-hidden="true" /> Upload {files.length || ''} photo{files.length === 1 ? '' : 's'}</button>
                <button type="button" disabled={!(x.images ?? []).length || verifying} onClick={() => void verify()}><Camera size={16} aria-hidden="true" /> Submit claim for AI verification</button>
              </div>
            </section>)}
          {verifying && <Notice><Loader2 className="spin" size={16} aria-hidden="true" /> <span role="status">Verifying your photos and checking the policy rules. This usually takes a few seconds.</span></Notice>}
          {!verifying && !open && x.status === 'Rejected' && <Notice kind="error"><strong>Claim rejected.</strong> {x.decision_reason}</Notice>}
          {!verifying && x.status === 'Exceptional Review Required' && (x.awaiting_staff_confirmation
            ? <Notice kind="info"><strong>Waiting for a staff member to confirm.</strong> Your photos and the policy checks passed. Nothing is paid until a person confirms the claim, because the AI report is never the authority for a payout.</Notice>
            : <Notice kind="warn"><strong>Referred for manual review.</strong> A staff member will look at your claim. This is not a rejection and not a finding of fraud. {x.decision_reason}</Notice>)}
          {!verifying && x.status === 'Settled' && <Notice kind="ok"><strong>Claim approved and settled (simulated).</strong> Payable amount {money(x.payable_amount)}.</Notice>}
          {x.report && <AiReport claim={x} />}
          <DecisionPanel d={x.decision} claim={x} />
          {staff && x.status === 'Exceptional Review Required' && (
            <section className="card" aria-labelledby="rv-h"><h2 id="rv-h" style={{ marginTop: 0 }}>Exceptional review decision</h2>
              <TextArea label="Reason (shown to the student)" value={reason} onChange={e => setReason(e.target.value)} />
              <p className="hint">Approval recalculates the amount from the frozen policy terms. Hard policy failures cannot be approved.</p>
              <div className="row"><button disabled={busy || reason.trim().length < 5} onClick={() => void decide('approve')}>Approve and settle (simulated)</button>
                <button className="danger" disabled={busy || reason.trim().length < 5} onClick={() => void decide('reject')}>Reject</button></div></section>)}
          {x.history && x.history.length > 0 && (
            <details className="card"><summary>Status history</summary>
              <Table caption="Status history" head={['Status', 'Reason', 'When']}>{x.history.map((h, i) => <tr key={i}><td>{h.to}</td><td>{h.reason}</td><td>{new Date(h.at + 'Z').toLocaleString('en-IN')}</td></tr>)}</Table></details>)}
        </>)}</Async>
    </>
  );
}

export function ClaimsList({ staff = false, detailBase = '/student/claims', only }: { staff?: boolean; detailBase?: string; only?: string }) {
  usePageTitle(only ? 'Exceptional reviews' : 'Claims');
  const list = useLoad(() => api<ClaimV3[]>('/v2/claims' + (only ? `?status=${encodeURIComponent(only)}` : '')), [only]);
  return (
    <>
      <div className="row spread"><h1>{only ? 'Exceptional reviews' : staff ? 'Claims' : 'My claims'}</h1>{!staff && <Link className="btn" to="/student/claims/new">New claim</Link>}</div>
      <Async state={list}>{rows => rows.length === 0 ? <Notice>{only ? 'No claims are waiting for review.' : 'No claims yet.'}</Notice> : (
        <Table caption="Claims" head={['Claim', ...(staff ? ['Student'] : []), 'Asset', 'Date', 'AI result', 'Policy decision', 'Status', 'Payable']} numCols={[staff ? 7 : 6]}>
          {rows.map(c => <tr key={c.id}><td><Link to={`${detailBase}/${c.id}`}>{c.claim_number}</Link></td>{staff && <td>{c.claimant_name}</td>}<td>{c.asset_name}</td><td>{c.incident_date}</td>
            <td>{c.ai_workflow_outcome || c.ai_outcome || '-'}</td><td>{c.decision_outcome || '-'}</td><td><Badge text={c.status} /></td><td className="num">{money(c.payable_amount)}</td></tr>)}
        </Table>)}</Async>
    </>
  );
}
