import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Bike, Headphones, Laptop, Smartphone, Tablet, Watch, Package, FileText } from 'lucide-react';
import { api, errMsg } from '../../api';
import { useAuth } from '../../auth';
import type { AssetV3, Category, Eligibility, EvidenceSummary, PolicyV3, Quote, Tx, ClaimV3 } from '../../types3';
import { Async, Badge, Check, ErrorBox, Field, Modal, Notice, Select, Stat, Table, TextArea, dt, money, today, useAction, useLoad, usePageTitle } from '../../ui';

const ICONS: Record<string, typeof Laptop> = { Laptop, Smartphone, Tablet, Earbuds: Headphones, Bicycle: Bike, Smartwatch: Watch };
export const CatIcon = ({ name, size = 20 }: { name: string; size?: number }) => { const I = ICONS[name] ?? Package; return <I size={size} aria-hidden="true" />; };

/* ------------------------------------------------------------ quote breakdown + purchase */
export function QuoteBreakdown({ q }: { q: Quote }) {
  return (
    <dl className="kv">
      <dt>Purchase value</dt><dd>{money(q.purchase_value)}</dd>
      <dt>Monthly premium</dt><dd>{money(q.monthly_premium)}</dd>
      <dt>Annual premium</dt><dd>{money(q.annual_premium)} <span className="hint">({q.formula.annual_premium})</span></dd>
      <dt>Maximum coverage</dt><dd>{money(q.max_coverage)}</dd>
      <dt>Estimated maximum claim</dt><dd>{money(q.estimated_max_claim)} <span className="hint">({q.formula.estimated_max_claim})</span></dd>
      <dt>Deductible</dt><dd>{q.deductible > 0 ? money(q.deductible) : 'None'}</dd>
      <dt>Policy duration</dt><dd>{q.policy_months} months{q.waiting_period_days ? `, ${q.waiting_period_days} day waiting period` : ''}</dd>
      <dt>Covered incidents</dt><dd>{q.covered_incident_types.join(', ')}</dd>
      <dt>Exclusions</dt><dd><ul>{q.exclusions.map(e => <li key={e}>{e}</li>)}</ul></dd>
    </dl>
  );
}

export function PurchaseModal({ asset, open, onClose, onDone }: { asset: AssetV3 | null; open: boolean; onClose: () => void; onDone: () => void }) {
  const [accept, setAccept] = useState(false);
  const { run, busy } = useAction();
  const nav = useNavigate();
  const quote = useLoad(() => (asset && open ? api<Eligibility>(`/v2/assets/${asset.id}/quote`) : Promise.resolve(null)), [asset?.id, open]);
  useEffect(() => { if (open) setAccept(false); }, [open]);
  const buy = async () => {
    if (!asset) return;
    const ok = await run(() => api(`/v2/assets/${asset.id}/purchase`, { method: 'POST', body: { accept_terms: accept } }), 'Policy purchased. This is a simulated purchase.');
    if (ok) { onDone(); onClose(); nav('/student/policies'); }
  };
  return (
    <Modal title={asset ? `Insure ${asset.name}` : 'Insure'} open={open} onClose={onClose}>
      <Notice kind="warn">Simulated purchase for an academic prototype. No card or bank details are collected and no money moves.</Notice>
      {asset && !asset.can_purchase && <Notice kind="warn">{asset.evidence?.reason || 'Your registration evidence must be approved by an administrator before you can buy a policy.'}</Notice>}
      <Async state={quote}>{e => e.eligible && e.quote ? (
        <>
          <QuoteBreakdown q={e.quote} />
          {e.active_policy ? <Notice>This asset already has an active policy.</Notice> : asset && !asset.can_purchase ? <div className="row"><button type="button" className="secondary" onClick={onClose}>Close</button></div> : (
            <>
              <Check label="I have read the coverage, exclusions and deductible above and accept the policy terms." checked={accept} onChange={x => setAccept(x.target.checked)} />
              <div className="row"><button type="button" disabled={!accept || busy} onClick={() => void buy()}>{busy ? 'Purchasing...' : `Pay ${money(e.quote.monthly_premium)} and activate`}</button>
                <button type="button" className="secondary" onClick={onClose}>Cancel</button></div>
            </>
          )}
        </>) : <Notice kind="error">{e.reason}</Notice>}</Async>
    </Modal>
  );
}

/* ------------------------------------------------------------ dashboard */
interface Dash { active_policies: number; insured_assets: number; registered_assets: number; total_coverage: number; monthly_commitment: number; premium_due: { policy_id: number; policy_number: string; period: string }[]; recent_claims: ClaimV3[]; recent_transactions: Tx[] }
export function Dashboard() {
  usePageTitle('Dashboard');
  const { user } = useAuth();
  const d = useLoad(() => api<Dash>('/v2/dashboard'), []);
  const { run, busy } = useAction();
  return (
    <>
      <h1>Welcome, {user?.full_name.split(' ')[0]}</h1>
      <Async state={d}>{x => (
        <>
          <div className="grid cols">
            <Stat label="Active policies" value={x.active_policies} />
            <Stat label="Insured assets" value={x.insured_assets} />
            <Stat label="Total coverage" value={money(x.total_coverage)} />
            <Stat label="Monthly premium" value={money(x.monthly_commitment)} />
          </div>
          {x.premium_due.map(p => (
            <Notice kind="warn" key={p.policy_id}>Premium for {p.period} is due on {p.policy_number}.{' '}
              <button className="sm" disabled={busy} onClick={() => void run(() => api(`/v2/policies/${p.policy_id}/pay-premium`, { method: 'POST' }), 'Premium paid (simulated).').then(() => d.reload())}>Pay now (simulated)</button></Notice>
          ))}
          <h2>Quick actions</h2>
          <div className="row">
            <Link className="btn" to="/student/assets">Add or insure an asset</Link>
            <Link className="btn secondary" to="/student/explore">Explore plans</Link>
            <Link className="btn secondary" to="/student/claims/new">Submit a claim</Link>
          </div>
          <h2>Recent claims</h2>
          {x.recent_claims.length === 0 ? <Notice>No claims yet. If an insured item is damaged, submit a claim with photos and the system verifies the evidence.</Notice> : (
            <Table caption="Recent claims" head={['Claim', 'Asset', 'AI result', 'Status', 'Payable']} numCols={[4]}>
              {x.recent_claims.map(c => <tr key={c.id}><td><Link to={`/student/claims/${c.id}`}>{c.claim_number}</Link></td><td>{c.asset_name}</td><td>{c.ai_outcome || '-'}</td><td><Badge text={c.status} /></td><td className="num">{money(c.payable_amount)}</td></tr>)}
            </Table>)}
          <h2>Recent transactions</h2>
          {x.recent_transactions.length === 0 ? <Notice>No premium payments yet.</Notice> : (
            <Table caption="Recent transactions" head={['Reference', 'Policy', 'Period', 'Amount', 'Status']} numCols={[3]}>
              {x.recent_transactions.map(t => <tr key={t.id}><td className="mono">{t.reference}</td><td>{t.policy_number}</td><td>{t.period}</td><td className="num">{money(t.amount)}</td><td><Badge text={t.status} /></td></tr>)}
            </Table>)}
        </>)}</Async>
    </>
  );
}

/* ------------------------------------------------------------ explore plans + calculator */
export function Explore() {
  usePageTitle('Explore plans');
  const cats = useLoad(() => api<Category[]>('/v2/categories'), []);
  const mine = useLoad(() => api<AssetV3[]>('/v2/assets'), []);
  const [cid, setCid] = useState('');
  const [price, setPrice] = useState('');
  const [res, setRes] = useState<Eligibility | null>(null);
  const [err, setErr] = useState('');
  const [buy, setBuy] = useState<AssetV3 | null>(null);
  const [aid, setAid] = useState('');
  useEffect(() => {
    setRes(null); setErr('');
    const p = Number(price);
    if (!cid || !price || !(p > 0)) return;
    const t = setTimeout(() => { api<Eligibility>('/v2/eligibility', { method: 'POST', body: { category_id: Number(cid), purchase_price: p } }).then(setRes).catch(e => setErr(errMsg(e))); }, 250);
    return () => clearTimeout(t);
  }, [cid, price]);
  const open = (mine.data ?? []).filter(a => !a.policy);
  return (
    <>
      <h1>Explore insurance plans</h1>
      <Notice kind="info">Prices and limits come from the server and can change. A policy keeps the terms it was bought with. This is an academic prototype, not a licensed insurance product.</Notice>
      <Async state={cats}>{list => (
        <div className="grid cols3">
          {list.map(c => (
            <article className="card plan" key={c.id} aria-labelledby={`c${c.id}`}>
              <h2 id={`c${c.id}`} style={{ marginTop: 0 }}><CatIcon name={c.name} /> {c.name}</h2>
              <p className="muted">{c.description}</p>
              <dl className="kv">
                <dt>Minimum value</dt><dd>{money(c.min_purchase_value)}</dd>
                <dt>Monthly premium</dt><dd>{money(c.monthly_premium)}</dd>
                <dt>Annual premium</dt><dd>{money(c.annual_premium)}</dd>
                <dt>Maximum coverage</dt><dd>{money(c.max_coverage)}</dd>
                <dt>Deductible</dt><dd>{c.deductible > 0 ? money(c.deductible) : 'None'}</dd>
              </dl>
              <p className="hint">{c.eligibility_conditions}</p>
              <details><summary>Key exclusions</summary><ul>{c.exclusions.map(e => <li key={e}>{e}</li>)}</ul></details>
            </article>))}
        </div>)}</Async>
      <section className="card" aria-labelledby="calc-h">
        <h2 id="calc-h" style={{ marginTop: 0 }}>Premium calculator</h2>
        <div className="grid cols">
          <Select label="Category" value={cid} onChange={e => setCid(e.target.value)} options={(cats.data ?? []).map(c => ({ value: c.id, label: c.name }))} placeholder="Choose a category" />
          <Field label="Purchase price (INR)" type="number" min="1" inputMode="numeric" value={price} onChange={e => setPrice(e.target.value)} />
        </div>
        <ErrorBox message={err} />
        {res && (res.eligible && res.quote ? <><Notice kind="ok">{res.reason}</Notice><QuoteBreakdown q={res.quote} /></> : <Notice kind="error">{res.reason}</Notice>)}
      </section>
      <section className="card" aria-labelledby="mine-h">
        <h2 id="mine-h" style={{ marginTop: 0 }}>Price one of my registered assets</h2>
        {open.length === 0 ? <p className="muted">You have no uninsured registered assets. <Link to="/student/assets">Register an asset</Link> to see its exact price.</p> : (
          <div className="row"><Select label="Asset" value={aid} onChange={e => setAid(e.target.value)} options={open.map(a => ({ value: a.id, label: `${a.name} (${a.category})` }))} placeholder="Choose an asset" />
            <button type="button" disabled={!aid} onClick={() => setBuy(open.find(a => a.id === Number(aid)) ?? null)}>See price and buy</button></div>)}
      </section>
      <PurchaseModal asset={buy} open={!!buy} onClose={() => setBuy(null)} onDone={() => mine.reload()} />
    </>
  );
}

/* ------------------------------------------------------------ my assets */
const MAX_MB = 8;
const PHOTO_EXT = ['.jpg', '.jpeg', '.png'];
const DOC_EXT = ['.jpg', '.jpeg', '.png', '.pdf'];
function fileProblem(f: File | null, exts: string[], what: string): string {
  if (!f) return '';
  const name = f.name.toLowerCase();
  if (!exts.some(x => name.endsWith(x))) return `${what} must be ${exts.map(x => x.slice(1).toUpperCase()).join(', ')}`;
  if (f.size > MAX_MB * 1024 * 1024) return `${what} is larger than ${MAX_MB} MB`;
  return '';
}

function AddAsset({ cats, onDone }: { cats: Category[]; onDone: () => void }) {
  const [f, setF] = useState({ cid: '', brand: '', model: '', price: '', date: '', serial: '', desc: '' });
  const [front, setFront] = useState<File | null>(null);
  const [back, setBack] = useState<File | null>(null);
  const [inv, setInv] = useState<File | null>(null);
  const [extra, setExtra] = useState<File[]>([]);
  const [elig, setElig] = useState<Eligibility | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const { run, busy } = useAction();
  const cat = cats.find(c => c.id === Number(f.cid));
  useEffect(() => {
    setElig(null);
    const p = Number(f.price);
    if (!f.cid || !(p > 0)) return;
    const t = setTimeout(() => { api<Eligibility>('/v2/eligibility', { method: 'POST', body: { category_id: Number(f.cid), purchase_price: p } }).then(setElig).catch(() => undefined); }, 250);
    return () => clearTimeout(t);
  }, [f.cid, f.price]);
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF(x => ({ ...x, [k]: e.target.value }));
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const er: Record<string, string> = {};
    if (!f.cid) er.cid = 'Choose a category';
    if (!f.brand.trim()) er.brand = 'Enter the brand';
    if (!f.model.trim()) er.model = 'Enter the model';
    if (!(Number(f.price) > 0)) er.price = 'Enter the purchase price';
    if (!f.date) er.date = 'Enter the purchase date';
    if (cat?.requires_serial && !f.serial.trim()) er.serial = 'A serial number, IMEI or frame number is required for this category';
    if (!front) er.front = 'Upload a photograph of the front of the item (JPG or PNG)';
    else if (fileProblem(front, PHOTO_EXT, 'The front photograph')) er.front = fileProblem(front, PHOTO_EXT, 'The front photograph');
    if (!back) er.back = 'Upload a photograph of the back of the item (JPG or PNG)';
    else if (fileProblem(back, PHOTO_EXT, 'The back photograph')) er.back = fileProblem(back, PHOTO_EXT, 'The back photograph');
    if (fileProblem(inv, DOC_EXT, 'The invoice')) er.inv = fileProblem(inv, DOC_EXT, 'The invoice');
    if (extra.length > 6) er.extra = 'Attach at most 6 additional files';
    else { const bad = extra.map(x => fileProblem(x, DOC_EXT, x.name)).find(Boolean); if (bad) er.extra = bad; }
    setErrors(er);
    if (Object.keys(er).length || !front || !back) return;
    const form = new FormData();
    form.set('category_id', f.cid); form.set('brand', f.brand); form.set('model', f.model); form.set('purchase_price', f.price); form.set('purchase_date', f.date);
    form.set('serial_number', f.serial); form.set('description', f.desc); form.set('front_photo', front); form.set('back_photo', back);
    if (inv) form.set('invoice', inv);
    extra.forEach(x => form.append('extra_files', x));
    if (await run(() => api('/v2/assets', { method: 'POST', form }), 'Asset registered. An administrator reviews your evidence before you can insure it.')) onDone();
  };
  return (
    <form className="card" onSubmit={e => void submit(e)} noValidate aria-label="Register an asset">
      <h2 style={{ marginTop: 0 }}>Register an asset</h2>
      <div className="grid cols">
        <Select label="Category" value={f.cid} onChange={set('cid')} options={cats.map(c => ({ value: c.id, label: c.name }))} placeholder="Choose a category" error={errors.cid} required />
        <Field label="Brand" value={f.brand} onChange={set('brand')} error={errors.brand} required />
        <Field label="Model" value={f.model} onChange={set('model')} error={errors.model} required />
        <Field label="Purchase price (INR)" type="number" min="1" value={f.price} onChange={set('price')} error={errors.price} hint={cat ? `Minimum for ${cat.name}: ${money(cat.min_purchase_value)}` : undefined} required />
        <Field label="Purchase date" type="date" max={today()} value={f.date} onChange={set('date')} error={errors.date} required />
        <Field label={cat?.name === 'Smartphone' ? 'IMEI' : cat?.name === 'Bicycle' ? 'Frame number' : 'Serial number'} value={f.serial} onChange={set('serial')} error={errors.serial} required={!!cat?.requires_serial} />
      </div>
      {elig && (elig.eligible ? <Notice kind="ok">{elig.reason}</Notice> : <Notice kind="error">{elig.reason}</Notice>)}
      <TextArea label="Short description" maxLength={500} value={f.desc} onChange={set('desc')} />
      <Notice>An administrator reviews your photographs and invoice before you can buy a policy. If you later claim, your claim photos are compared with these, so take them in good light and show the whole item.</Notice>
      <div className="grid cols">
        <Field label="Front photograph" type="file" accept=".jpg,.jpeg,.png" onChange={e => setFront(e.target.files?.[0] ?? null)} error={errors.front} hint="The whole item, front side." required />
        <Field label="Back photograph" type="file" accept=".jpg,.jpeg,.png" onChange={e => setBack(e.target.files?.[0] ?? null)} error={errors.back} hint="The whole item, back side." required />
        <Field label="Invoice or purchase receipt" type="file" accept=".jpg,.jpeg,.png,.pdf" onChange={e => setInv(e.target.files?.[0] ?? null)} error={errors.inv} hint="Where available. Without one, an administrator needs a written reason to approve. It is not verified automatically." />
        <Field label="Additional photographs or documents" type="file" multiple accept=".jpg,.jpeg,.png,.pdf" onChange={e => setExtra(Array.from(e.target.files ?? []))} error={errors.extra} hint="Optional, up to 6: the serial or IMEI label, the box, a warranty card." />
      </div>
      <button type="submit" disabled={busy || (elig !== null && !elig.eligible)}>{busy ? 'Registering...' : 'Check eligibility and register'}</button>
    </form>
  );
}

const EVIDENCE_KINDS = [{ value: 'back_photo', label: 'Back photograph (replaces the current one)' }, { value: 'front_photo', label: 'Front photograph (replaces the current one)' },
  { value: 'invoice', label: 'Invoice or receipt (replaces the current one)' }, { value: 'extra_photo', label: 'Additional photograph' }, { value: 'document', label: 'Other document' }];

export function EvidencePanel({ assetId, onChange }: { assetId: number; onChange: () => void }) {
  const ev = useLoad(() => api<EvidenceSummary>(`/v2/assets/${assetId}/evidence`), [assetId]);
  const [kind, setKind] = useState('back_photo');
  const [file, setFile] = useState<File | null>(null);
  const [problem, setProblem] = useState('');
  const [reset, setReset] = useState(0);
  const { run, busy } = useAction();
  const upload = async () => {
    const exts = kind.endsWith('photo') ? PHOTO_EXT : DOC_EXT;
    const bad = !file ? 'Choose a file first' : fileProblem(file, exts, 'The file');
    setProblem(bad);
    if (bad || !file) return;
    const form = new FormData();
    form.set('kind', kind); form.set('file', file);
    if (await run(() => api(`/v2/assets/${assetId}/evidence`, { method: 'POST', form }), 'Evidence uploaded.')) { setFile(null); setReset(r => r + 1); ev.reload(); onChange(); }
  };
  const remove = async (id: number) => { if (await run(() => api(`/v2/assets/${assetId}/evidence/${id}`, { method: 'DELETE' }), 'File removed.')) { ev.reload(); onChange(); } };
  return (
    <section aria-label="Registration evidence">
      <h3>Registration evidence</h3>
      <Async state={ev}>{e => (
        <>
          <p><Badge text={e.status} /> {e.reason}</p>
          {e.missing_required.length > 0 && <Notice kind="warn">An administrator cannot approve this registration until you add: {e.missing_required.join(', ')}.</Notice>}
          {!e.has_invoice && <p className="hint">No invoice or receipt is attached. That is allowed, but the administrator needs a written reason to approve without one.</p>}
          <Table caption="Evidence files" head={['Type', 'File', 'Status', 'Notes', '']}>
            {e.files.map(x => (
              <tr key={x.id}>
                <td>{x.label}</td>
                <td><a href={x.file_url} target="_blank" rel="noreferrer">{x.original_name}</a></td>
                <td><Badge text={x.review_status} /></td>
                <td>{x.quality_issues.length ? x.quality_issues.join('; ') : '-'}</td>
                <td>{e.can_add && <button type="button" className="secondary sm" disabled={busy} onClick={() => void remove(x.id)} aria-label={`Remove ${x.original_name}`}>Remove</button>}</td>
              </tr>))}
          </Table>
          {e.can_add ? (
            <div className="grid cols">
              <Select label="Add evidence" value={kind} onChange={x => setKind(x.target.value)} options={EVIDENCE_KINDS} />
              <Field key={reset} label="File" type="file" accept=".jpg,.jpeg,.png,.pdf" onChange={x => { setFile(x.target.files?.[0] ?? null); setProblem(''); }} error={problem} />
              <div className="field"><button type="button" disabled={busy} onClick={() => void upload()}>{busy ? 'Uploading...' : 'Upload'}</button></div>
            </div>
          ) : <p className="hint">Evidence can no longer be changed once it is approved or rejected. Contact an administrator to correct a registration error.</p>}
        </>)}</Async>
    </section>
  );
}

export function Assets() {
  usePageTitle('My assets');
  const assets = useLoad(() => api<AssetV3[]>('/v2/assets'), []);
  const cats = useLoad(() => api<Category[]>('/v2/categories'), []);
  const [adding, setAdding] = useState(false);
  const [buy, setBuy] = useState<AssetV3 | null>(null);
  const [view, setView] = useState<AssetV3 | null>(null);
  return (
    <>
      <div className="row spread"><h1>My assets</h1><button onClick={() => setAdding(a => !a)} aria-expanded={adding}>{adding ? 'Close form' : 'Add an asset'}</button></div>
      {adding && cats.data && <AddAsset cats={cats.data} onDone={() => { setAdding(false); assets.reload(); }} />}
      <Async state={assets}>{list => list.length === 0 ? <Notice>You have not registered any assets. Add a laptop, smartphone, tablet, earbuds, bicycle or smartwatch to see its premium.</Notice> : (
        <div className="grid cols3">
          {list.map(a => (
            <article className="card asset" key={a.id} aria-labelledby={`a${a.id}`}>
              {a.has_photo && <img className="thumb" src={`/api/v2/assets/${a.id}/file/photo`} alt={`Photograph of ${a.name}`} loading="lazy" />}
              <h2 id={`a${a.id}`} style={{ marginTop: 0 }}><CatIcon name={a.category} /> {a.name}</h2>
              <dl className="kv">
                <dt>Category</dt><dd>{a.category}</dd>
                <dt>Purchase price</dt><dd>{money(a.purchase_price)}</dd>
                <dt>Eligibility</dt><dd><Badge text={a.eligibility_status === 'Eligible' ? 'Approved' : a.eligibility_status} /> {a.eligibility_status}</dd>
                <dt>Insurance</dt><dd>{a.policy ? <Badge text="Active" /> : <span className="badge">Not insured</span>}</dd>
                {a.policy && <><dt>Policy</dt><dd>{a.policy.policy_number}</dd><dt>Maximum coverage</dt><dd>{money(a.policy.max_coverage)}</dd></>}
                <dt>Invoice</dt><dd>{a.invoice_status}</dd>
                <dt>Evidence review</dt><dd><Badge text={a.evidence_status} /></dd>
              </dl>
              <div className="row">
                <button className="secondary sm" onClick={() => setView(a)}>{a.can_purchase ? 'Details' : 'Evidence and details'}</button>
                {!a.policy && (a.can_purchase ? <button className="sm" onClick={() => setBuy(a)}>Insure this asset</button> : <span className="hint">Waiting for evidence approval</span>)}
              </div>
            </article>))}
        </div>)}</Async>
      <PurchaseModal asset={buy} open={!!buy} onClose={() => setBuy(null)} onDone={() => assets.reload()} />
      <Modal title={view?.name ?? 'Asset'} open={!!view} onClose={() => setView(null)}>
        {view && <>
          <dl className="kv"><dt>Brand and model</dt><dd>{view.brand} {view.model_name}</dd><dt>Serial, IMEI or frame no.</dt><dd className="mono">{view.serial_number || '-'}</dd><dt>Purchase date</dt><dd>{view.purchase_date}</dd>
            <dt>Purchase price</dt><dd>{money(view.purchase_price)} (declared by you, not verified)</dd><dt>Eligibility result</dt><dd>{view.eligibility_reason}</dd><dt>Description</dt><dd>{view.description || '-'}</dd></dl>
          <p className="hint">Insured values cannot be edited after purchase. Contact an administrator to correct a registration error.</p>
          <EvidencePanel assetId={view.id} onChange={() => assets.reload()} />
          <div className="row">{view.has_invoice && <a className="btn secondary" href={`/api/v2/assets/${view.id}/file/invoice`} target="_blank" rel="noreferrer"><FileText size={16} aria-hidden="true" /> Open invoice</a>}
            <button className="secondary" onClick={() => setView(null)}>Close</button></div></>}
      </Modal>
    </>
  );
}

/* ------------------------------------------------------------ policies */
export function Policies() {
  usePageTitle('My policies');
  const pol = useLoad(() => api<PolicyV3[]>('/v2/policies'), []);
  const { run, busy } = useAction();
  return (
    <>
      <h1>My policies</h1>
      <Async state={pol}>{list => list.length === 0 ? <Notice>You have no policies yet. <Link to="/student/assets">Insure an asset</Link>.</Notice> : (
        <div className="grid cols3">{list.map(p => (
          <article className="card" key={p.id} aria-labelledby={`p${p.id}`}>
            <div className="row spread"><h2 id={`p${p.id}`} style={{ margin: 0 }}>{p.policy_number}</h2><Badge text={p.status} /></div>
            <dl className="kv">
              <dt>Insured asset</dt><dd>{p.category && <CatIcon name={p.category} size={16} />} {p.asset_name}</dd>
              <dt>Start date</dt><dd>{p.start_date}</dd><dt>End date</dt><dd>{p.end_date}</dd>
              <dt>Monthly premium</dt><dd>{money(p.monthly_premium)}</dd><dt>Maximum coverage</dt><dd>{money(p.max_coverage)}</dd>
              <dt>Deductible</dt><dd>{p.deductible > 0 ? money(p.deductible) : 'None'}</dd><dt>Premiums paid</dt><dd>{money(p.premiums_paid)}</dd>
            </dl>
            {p.next_premium_due && <Notice kind="warn">Premium for {p.next_premium_due} is due. <button className="sm" disabled={busy} onClick={() => void run(() => api(`/v2/policies/${p.id}/pay-premium`, { method: 'POST' }), 'Premium paid (simulated).').then(() => pol.reload())}>Pay (simulated)</button></Notice>}
            <details><summary>Policy terms</summary>
              <p>Covered incidents: {p.terms?.covered_incident_types.join(', ')}. Waiting period: {p.terms?.waiting_period_days} days. Duration: {p.terms?.policy_months} months.</p>
              <ul>{p.terms?.exclusions.map(e => <li key={e}>{e}</li>)}</ul></details>
          </article>))}</div>)}</Async>
    </>
  );
}

/* ------------------------------------------------------------ payments */
export function Payments() {
  usePageTitle('Payment history');
  const tx = useLoad(() => api<Tx[]>('/v2/payments'), []);
  return (
    <>
      <h1>Payment history</h1>
      <Notice kind="warn">All payments are simulated. This prototype never collects card or bank details.</Notice>
      <Async state={tx}>{list => list.length === 0 ? <Notice>No payments yet.</Notice> : (
        <Table caption="Premium payments" head={['Transaction', 'Policy', 'Cover month', 'Amount', 'Paid on', 'Status']} numCols={[3]}>
          {list.map(t => <tr key={t.id}><td className="mono">{t.reference}</td><td>{t.policy_number}</td><td>{t.period}</td><td className="num">{money(t.amount)}</td><td>{dt(t.paid_at)}</td><td><Badge text={t.status} /> simulated</td></tr>)}
        </Table>)}</Async>
    </>
  );
}

/* ------------------------------------------------------------ profile */
export function Profile() {
  usePageTitle('Profile and settings');
  const { user } = useAuth();
  const [cur, setCur] = useState(''); const [nw, setNw] = useState(''); const [again, setAgain] = useState('');
  const [err, setErr] = useState('');
  const { run, busy } = useAction();
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (nw !== again) { setErr('The new passwords do not match.'); return; }
    setErr('');
    if (await run(() => api('/auth/change-password', { method: 'POST', body: { current_password: cur, new_password: nw } }), 'Password changed. Other sessions were signed out.')) { setCur(''); setNw(''); setAgain(''); }
  };
  return (
    <>
      <h1>Profile and settings</h1>
      <section className="card" aria-labelledby="pf"><h2 id="pf" style={{ marginTop: 0 }}>Your details</h2>
        <dl className="kv"><dt>Name</dt><dd>{user?.full_name}</dd><dt>Username</dt><dd>{user?.username}</dd><dt>Email</dt><dd>{user?.email ?? '-'}</dd></dl></section>
      <form className="card" onSubmit={e => void submit(e)} aria-label="Change password">
        <h2 style={{ marginTop: 0 }}>Change password</h2>
        <Field label="Current password" type="password" autoComplete="current-password" value={cur} onChange={e => setCur(e.target.value)} required />
        <Field label="New password" type="password" autoComplete="new-password" value={nw} onChange={e => setNw(e.target.value)} hint="At least 8 characters and not a common password." required />
        <Field label="Repeat new password" type="password" autoComplete="new-password" value={again} onChange={e => setAgain(e.target.value)} required />
        <ErrorBox message={err} />
        <button type="submit" disabled={busy || !cur || !nw}>Change password</button>
      </form>
    </>
  );
}
