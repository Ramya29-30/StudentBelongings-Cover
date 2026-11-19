import { useState } from 'react';
import type { FormEvent } from 'react';
import { Link } from 'react-router-dom';
import { Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { api } from '../../api';
import type { Category, PolicyV3 } from '../../types3';
import { Async, Badge, Check, ErrorBox, Field, Modal, Notice, Stat, Table, TextArea, money, useAction, useLoad, usePageTitle } from '../../ui';
import { CatIcon } from '../student/Insure';

/* ------------------------------------------------------------ overview */
interface Ov { students: number; active_policies: number; insured_assets: number; premium_revenue: number; claims_received: number; claims_approved: number; claims_rejected: number; pending_exceptional_reviews: number; more_evidence: number; pending_evidence_reviews: number }
export function Overview() {
  usePageTitle('Overview');
  const o = useLoad(() => api<Ov>('/v2/admin/overview'), []);
  return (
    <>
      <h1>Overview</h1>
      <Async state={o}>{x => (
        <>
          <div className="grid cols">
            <Stat label="Registered students" value={x.students} /><Stat label="Active policies" value={x.active_policies} /><Stat label="Insured assets" value={x.insured_assets} />
            <Stat label="Premium revenue (simulated)" value={money(x.premium_revenue)} /><Stat label="Claims received" value={x.claims_received} /><Stat label="Claims approved" value={x.claims_approved} />
            <Stat label="Claims rejected" value={x.claims_rejected} /><Stat label="Waiting for exceptional review" value={x.pending_exceptional_reviews} />
          </div>
          {x.pending_evidence_reviews > 0 && <Notice kind="warn">{x.pending_evidence_reviews} registration(s) wait for an evidence review before the student can buy a policy. <Link to="/admin/evidence">Open the evidence queue</Link>.</Notice>}
          {x.pending_exceptional_reviews > 0 && <Notice kind="warn">{x.pending_exceptional_reviews} claim(s) need an exceptional review. <Link to="/admin/reviews">Open the review queue</Link>.</Notice>}
        </>)}</Async>
    </>
  );
}

/* ------------------------------------------------------------ categories / plans */
type CatForm = Omit<Category, 'id' | 'annual_premium'>;
const EMPTY: CatForm = { name: '', description: '', min_purchase_value: 5000, monthly_premium: 50, max_coverage: 3000, deductible: 0, policy_months: 12, waiting_period_days: 0, depreciation_pct_per_year: 0, depreciation_max_pct: 0,
  exclusions: [], covered_incident_types: ['Accidental Damage', 'Liquid Damage'], excluded_damage_types: [], damage_types: [], reference_repair_costs: {}, eligibility_conditions: '', requires_serial: true, active: true };
const lines = (s: string) => s.split('\n').map(x => x.trim()).filter(Boolean);

function CategoryForm({ initial, id, onDone, onCancel }: { initial: CatForm; id?: number; onDone: () => void; onCancel: () => void }) {
  const [f, setF] = useState<CatForm>(initial);
  const [dmg, setDmg] = useState(initial.damage_types.join('\n'));
  const [excl, setExcl] = useState(initial.exclusions.join('\n'));
  const [refs, setRefs] = useState(Object.entries(initial.reference_repair_costs).map(([k, v]) => `${k}=${v}`).join('\n'));
  const [err, setErr] = useState('');
  const { run, busy } = useAction();
  const num = (k: keyof CatForm) => (e: { target: { value: string } }) => setF(x => ({ ...x, [k]: Number(e.target.value) }));
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const reference_repair_costs: Record<string, number> = {};
    for (const l of lines(refs)) { const [k, v] = l.split('='); if (!k || !(Number(v) >= 0)) { setErr(`Reference cost line "${l}" must look like "Cracked screen=3500".`); return; } reference_repair_costs[k.trim()] = Number(v); }
    setErr('');
    const body = { ...f, damage_types: lines(dmg), exclusions: lines(excl), reference_repair_costs };
    if (await run(() => api(id ? `/v2/admin/categories/${id}` : '/v2/admin/categories', { method: id ? 'PUT' : 'POST', body }), id ? 'Category updated. Issued policies keep their original terms.' : 'Category created.')) onDone();
  };
  return (
    <form onSubmit={e => void submit(e)} aria-label="Category form">
      <div className="grid cols">
        <Field label="Name" value={f.name} onChange={e => setF({ ...f, name: e.target.value })} required />
        <Field label="Minimum purchase value" type="number" min="1" value={f.min_purchase_value} onChange={num('min_purchase_value')} required />
        <Field label="Monthly premium" type="number" min="1" value={f.monthly_premium} onChange={num('monthly_premium')} required />
        <Field label="Maximum coverage" type="number" min="1" value={f.max_coverage} onChange={num('max_coverage')} required />
        <Field label="Deductible" type="number" min="0" value={f.deductible} onChange={num('deductible')} />
        <Field label="Policy duration (months)" type="number" min="1" max="60" value={f.policy_months} onChange={num('policy_months')} />
        <Field label="Waiting period (days)" type="number" min="0" value={f.waiting_period_days} onChange={num('waiting_period_days')} />
        <Field label="Depreciation % per year" type="number" min="0" max="100" value={f.depreciation_pct_per_year} onChange={num('depreciation_pct_per_year')} />
        <Field label="Depreciation cap %" type="number" min="0" max="100" value={f.depreciation_max_pct} onChange={num('depreciation_max_pct')} />
      </div>
      <Field label="Description" value={f.description} onChange={e => setF({ ...f, description: e.target.value })} />
      <TextArea label="Claimable damage types (one per line)" value={dmg} onChange={e => setDmg(e.target.value)} />
      <TextArea label="Reference repair costs (one per line, damage type=amount)" value={refs} onChange={e => setRefs(e.target.value)} hint="Used when a student gives no estimate, and to check estimates." />
      <TextArea label="Exclusions (one per line)" value={excl} onChange={e => setExcl(e.target.value)} />
      <Field label="Eligibility conditions" value={f.eligibility_conditions} onChange={e => setF({ ...f, eligibility_conditions: e.target.value })} />
      <Check label="Requires a serial number, IMEI or frame number" checked={f.requires_serial} onChange={e => setF({ ...f, requires_serial: e.target.checked })} />
      <Check label="Offered to students (untick to disable the category)" checked={f.active} onChange={e => setF({ ...f, active: e.target.checked })} />
      <ErrorBox message={err} />
      <div className="row"><button type="submit" disabled={busy}>{busy ? 'Saving...' : 'Save'}</button><button type="button" className="secondary" onClick={onCancel}>Cancel</button></div>
    </form>
  );
}

export function Categories() {
  usePageTitle('Categories and plans');
  const cats = useLoad(() => api<Category[]>('/v2/admin/categories'), []);
  const [edit, setEdit] = useState<Category | 'new' | null>(null);
  const done = () => { setEdit(null); cats.reload(); };
  return (
    <>
      <div className="row spread"><h1>Asset categories and plans</h1><button onClick={() => setEdit('new')}>Add category</button></div>
      <Notice>Each category is one insurance plan: eligibility, premium, coverage, deductible, duration and exclusions. Changes apply to new policies only, are validated, and are recorded in the audit log.</Notice>
      <Async state={cats}>{rows => (
        <Table caption="Categories" head={['Category', 'Minimum value', 'Monthly premium', 'Maximum coverage', 'Deductible', 'Duration', 'Status', '']} numCols={[1, 2, 3, 4]}>
          {rows.map(c => <tr key={c.id}><td><CatIcon name={c.name} size={16} /> {c.name}</td><td className="num">{money(c.min_purchase_value)}</td><td className="num">{money(c.monthly_premium)}</td><td className="num">{money(c.max_coverage)}</td>
            <td className="num">{money(c.deductible)}</td><td>{c.policy_months} months</td><td><Badge text={c.active ? 'Active' : 'Cancelled'} /> {c.active ? 'Offered' : 'Disabled'}</td><td><button className="secondary sm" onClick={() => setEdit(c)}>Edit</button></td></tr>)}
        </Table>)}</Async>
      <Modal title={edit === 'new' ? 'Add category' : `Edit ${edit?.name ?? ''}`} open={edit !== null} onClose={() => setEdit(null)}>
        {edit && <CategoryForm initial={edit === 'new' ? EMPTY : { ...edit }} id={edit === 'new' ? undefined : edit.id} onDone={done} onCancel={() => setEdit(null)} />}
      </Modal>
    </>
  );
}

/* ------------------------------------------------------------ policies */
export function PoliciesV3() {
  usePageTitle('Policies');
  const p = useLoad(() => api<PolicyV3[]>('/v2/admin/policies'), []);
  return (
    <>
      <h1>Policies</h1>
      <Async state={p}>{rows => (
        <Table caption="Policies" head={['Policy', 'Student', 'Asset', 'Monthly premium', 'Coverage', 'Start', 'Expiry', 'Status']} numCols={[3, 4]}>
          {rows.map(x => <tr key={x.id}><td>{x.policy_number}</td><td>{x.student_name}</td><td>{x.asset_name}</td><td className="num">{money(x.monthly_premium)}</td><td className="num">{money(x.max_coverage)}</td><td>{x.start_date}</td><td>{x.end_date}</td><td><Badge text={x.status} /></td></tr>)}
        </Table>)}</Async>
    </>
  );
}

/* ------------------------------------------------------------ AI analytics */
interface EvalClass { precision: number | null; recall: number | null; f1: number | null; ap50: number | null; ap50_95: number | null; tp?: number | null; fp?: number | null; fn?: number | null; instances: number | null }
interface Evaluation {
  model: string | null; model_sha256: string | null; split: string | null; images: number | null; iou_threshold: number | null; confidence_threshold: number | null; generated_at: string | null;
  dataset: { fingerprint?: string } | null; per_class: Record<string, EvalClass>; overall: { precision: number | null; recall: number | null; f1: number | null; map50: number | null; map50_95: number | null };
  confusion_matrix: { labels: string[]; matrix: number[][]; convention: string } | null; unavailable_metrics: string[]; note: string | null;
}
interface An {
  reports: number; images_analyzed: number; successful: number; uncertain: number; inconsistent: number; avg_processing_ms: number;
  damage_distribution_detected: Record<string, number>; damage_distribution_declared: Record<string, number>; modes: Record<string, number>; simulated_reports: number;
  model_metrics: Record<string, unknown> | null; model_metrics_note: string | null;
  damage_model: { available: boolean; state: string; file: string; sha256: string | null; classes: string[]; input_size: number | null; file_modified: string | null; training_metadata: Record<string, unknown> | null;
    evaluation_present: boolean; evaluation_matches_model: boolean; evaluation_note: string };
  evaluation: Evaluation | null;
  workflow_outcomes: Record<string, number>; workflow_outcomes_note: string;
  device_matching: { reports_compared: number; bands: Record<string, number>; average_best_score: number | null; scores_measured: number; serial_check: Record<string, number>; brand_model_check: Record<string, number>; calibrated: boolean; note: string;
    calibration: { generated_at: string; pairs: number; same_item_pairs: number; different_item_pairs: number; auc: number; suggested: { strong: number | null; partial: number | null }; currently_configured: { strong: number; partial: number } } | null };
  authenticity_indicators: Record<string, number>;
  manual_review: { waiting_for_staff: number; decided_by_staff: Record<string, number>; average_hours_to_decision: number | null; decisions_with_timing: number; sent_to_manual_review: number;
    approved_after_suspicious_outcome: number; rejected_after_consistent_outcome: number; auto_approval_setting: string };
  evidence_review: Record<string, number>;
  capabilities: { effective_mode: string; note: string; asset_model: { file: string; sha256: string } | null; damage_model: { file: string } | null; vision_language_model: boolean; auto_approval: string };
}
const num = (v: number | null | undefined) => (v == null ? 'Not measured' : v.toFixed(3));
const counts = (o: Record<string, number>) => Object.entries(o).map(([k, v]) => `${k}: ${v}`).join(', ') || 'none yet';

function EvaluationCard({ m }: { m: An }) {
  const ev = m.evaluation;
  return (
    <section className="card" aria-labelledby="ev-h">
      <h2 id="ev-h" style={{ marginTop: 0 }}>Damage model evaluation</h2>
      {!ev ? <Notice>Not measured. No labelled evaluation has been run, so precision, recall, F1 and mAP are unavailable. They appear here after you run <code>ai_training/evaluate_damage_model.py</code> on a labelled split.</Notice> : (
        <>
          {!m.damage_model.evaluation_matches_model && <Notice kind="warn">{m.damage_model.available ? 'This evaluation was measured on a different model file than the one installed, so it says nothing about the installed model.' : 'No damage model is installed. This evaluation belongs to a model that is not in use.'}</Notice>}
          <dl className="kv">
            <dt>Measured on</dt><dd>{ev.split ?? '-'} split, {ev.images ?? '-'} images ({ev.generated_at ?? 'date unknown'})</dd>
            <dt>Model file SHA-256</dt><dd className="mono">{ev.model_sha256 ?? '-'}</dd>
            <dt>Dataset fingerprint</dt><dd className="mono">{ev.dataset?.fingerprint ?? 'not recorded'}</dd>
            <dt>Thresholds</dt><dd>IoU {ev.iou_threshold ?? '-'}, confidence {ev.confidence_threshold ?? '-'} (precision, recall, F1 and confusion matrix); mAP uses all detections</dd>
          </dl>
          <Table caption="Per-class results" head={['Class', 'Instances', 'Precision', 'Recall', 'F1', 'AP@0.5', 'AP@0.5:0.95']} numCols={[1, 2, 3, 4, 5, 6]}>
            {Object.entries(ev.per_class).map(([k, v]) => <tr key={k}><td>{k}</td><td className="num">{v.instances ?? '-'}</td><td className="num">{num(v.precision)}</td><td className="num">{num(v.recall)}</td><td className="num">{num(v.f1)}</td><td className="num">{num(v.ap50)}</td><td className="num">{num(v.ap50_95)}</td></tr>)}
            <tr><th scope="row">All classes</th><td className="num">-</td><td className="num">{num(ev.overall.precision)}</td><td className="num">{num(ev.overall.recall)}</td><td className="num">{num(ev.overall.f1)}</td><td className="num">{num(ev.overall.map50)}</td><td className="num">{num(ev.overall.map50_95)}</td></tr>
          </Table>
          {ev.confusion_matrix ? (
            <Table caption="Confusion matrix (rows are the true class, columns the predicted class)" head={['True \\ predicted', ...ev.confusion_matrix.labels]} numCols={ev.confusion_matrix.labels.map((_, i) => i + 1)}>
              {ev.confusion_matrix.matrix.map((row, i) => <tr key={i}><th scope="row">{ev.confusion_matrix?.labels[i]}</th>{row.map((c, j) => <td className="num" key={j}>{c}</td>)}</tr>)}
            </Table>) : <p className="muted">Confusion matrix: not available in this evaluation file.</p>}
          {ev.unavailable_metrics.length > 0 && <p className="hint">Unavailable in this file: {ev.unavailable_metrics.join(', ')}.</p>}
          {ev.note && <p className="hint">{ev.note}</p>}
        </>)}
    </section>
  );
}

export function AiAnalytics() {
  usePageTitle('AI verification analytics');
  const a = useLoad(() => api<An>('/v2/ai/analytics'), []);
  return (
    <>
      <h1>AI verification analytics</h1>
      <Async state={a}>{x => {
        const dist = Object.entries(Object.keys(x.damage_distribution_detected).length ? x.damage_distribution_detected : x.damage_distribution_declared).map(([name, value]) => ({ name, value }));
        const wf = x.workflow_outcomes;
        const dm = x.damage_model;
        const md = x.device_matching;
        const mr = x.manual_review;
        return (
          <>
            {x.capabilities.note && <Notice kind="warn">{x.capabilities.note}</Notice>}
            <div className="grid cols">
              <Stat label="Images analysed" value={x.images_analyzed} /><Stat label="Evidence appears consistent" value={wf['Evidence appears consistent'] ?? 0} /><Stat label="More evidence required" value={wf['More evidence required'] ?? 0} />
              <Stat label="Suspicious, manual review" value={wf['Suspicious evidence - manual review'] ?? 0} /><Stat label="Unable to verify, manual review" value={wf['Unable to verify - manual review'] ?? 0} /><Stat label="Average processing time" value={`${x.avg_processing_ms} ms`} />
            </div>
            <p className="hint">{x.workflow_outcomes_note} These counts describe what the software reported, not whether it was right.</p>
            <section className="card"><h2 style={{ marginTop: 0 }}>Damage model</h2>
              <Notice kind={dm.available ? 'ok' : 'warn'}>{dm.state}</Notice>
              <dl className="kv">
                <dt>Availability</dt><dd>{dm.available ? 'Available' : 'Not available'}</dd>
                <dt>File</dt><dd>{dm.file}{dm.file_modified ? ` (modified ${dm.file_modified})` : ''}</dd>
                <dt>Model version (SHA-256)</dt><dd className="mono">{dm.sha256 ?? 'No model file loaded'}</dd>
                <dt>Classes</dt><dd>{dm.classes.length ? dm.classes.join(', ') : '-'}</dd>
                <dt>Input size</dt><dd>{dm.input_size ?? '-'}</dd>
                <dt>Training record</dt><dd>{dm.training_metadata ? Object.entries(dm.training_metadata).filter(([k]) => k !== 'classes' && k !== 'notes').map(([k, v]) => `${k}: ${String(v)}`).join('; ') : 'No training record found'}</dd>
                <dt>Evaluation</dt><dd>{dm.evaluation_note || '-'}</dd>
              </dl></section>
            <EvaluationCard m={x} />
            <section className="card"><h2 style={{ marginTop: 0 }}>Registered-device matching</h2>
              <Notice kind="warn">{md.note}</Notice>
              <dl className="kv"><dt>Claims compared</dt><dd>{md.reports_compared}</dd><dt>Results by band</dt><dd>{counts(md.bands)}</dd>
                <dt>Average best score</dt><dd>{md.average_best_score == null ? 'Not available (no comparison has run)' : `${md.average_best_score} over ${md.scores_measured} comparisons (uncalibrated)`}</dd>
                <dt>Serial or IMEI text check</dt><dd>{counts(md.serial_check)}</dd><dt>Brand and model text check</dt><dd>{counts(md.brand_model_check)}</dd>
                <dt>Calibrated on labelled pairs</dt><dd>{md.calibration ? `Yes: ${md.calibration.pairs} pairs (${md.calibration.same_item_pairs} same item, ${md.calibration.different_item_pairs} different), AUC ${md.calibration.auc}, measured ${md.calibration.generated_at}. Suggested thresholds ${md.calibration.suggested.strong ?? 'none'} strong, ${md.calibration.suggested.partial ?? 'none'} partial; configured ${md.calibration.currently_configured.strong} and ${md.calibration.currently_configured.partial}.` : 'No'}</dd></dl></section>
            <section className="card"><h2 style={{ marginTop: 0 }}>Manual review</h2>
              <dl className="kv"><dt>Waiting for a staff member</dt><dd>{mr.waiting_for_staff}</dd><dt>Sent to manual review by the checks</dt><dd>{mr.sent_to_manual_review}</dd>
                <dt>Decided by staff</dt><dd>{counts(mr.decided_by_staff)}</dd>
                <dt>Average time to decision</dt><dd>{mr.average_hours_to_decision == null ? 'Not enough data' : `${mr.average_hours_to_decision} hours (${mr.decisions_with_timing} decisions)`}</dd>
                <dt>Approved by staff after a suspicious outcome</dt><dd>{mr.approved_after_suspicious_outcome}</dd><dt>Rejected after a consistent outcome</dt><dd>{mr.rejected_after_consistent_outcome}</dd>
                <dt>Automatic approval</dt><dd>{mr.auto_approval_setting === 'off' ? 'Off: a person confirms every claim before any payout' : `${mr.auto_approval_setting} (only with a trained, evaluated model and no risk indicators)`}</dd></dl></section>
            <section className="card"><h2 style={{ marginTop: 0 }}>Registration evidence review</h2>
              <dl className="kv">{Object.entries(x.evidence_review).map(([k, v]) => <><dt key={k + 'k'}>{k}</dt><dd key={k + 'v'}>{v}</dd></>)}</dl>
              <Link className="btn secondary" to="/admin/evidence">Open the review queue</Link></section>
            <section className="card"><h2 style={{ marginTop: 0 }}>Authenticity indicators raised</h2>
              <p>{counts(x.authenticity_indicators)}</p><p className="hint">Indicators prompt a human review. Missing camera metadata is never counted.</p></section>
            <section className="card"><h2 style={{ marginTop: 0 }}>Configuration in use</h2>
              <dl className="kv"><dt>Effective mode</dt><dd><code>{x.capabilities.effective_mode}</code></dd><dt>Asset detector</dt><dd>{x.capabilities.asset_model ? `${x.capabilities.asset_model.file} (sha256 ${x.capabilities.asset_model.sha256})` : 'not installed'}</dd>
                <dt>Vision-language model</dt><dd>{x.capabilities.vision_language_model ? 'configured' : 'not configured'}</dd>
                <dt>Reports by mode</dt><dd>{Object.entries(x.modes).map(([k, v]) => `${k}: ${v}`).join(', ') || '-'}</dd><dt>Simulated reports</dt><dd>{x.simulated_reports}</dd></dl></section>
            <section className="card"><h2 style={{ marginTop: 0 }}>Damage category distribution</h2>
              {dist.length === 0 ? <p className="muted">No data yet.</p> : (
                <div style={{ height: 260 }} role="img" aria-label={`Bar chart of damage categories: ${dist.map(d => `${d.name} ${d.value}`).join(', ')}`}><ResponsiveContainer><BarChart data={dist}><CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="name" /><YAxis allowDecimals={false} /><Tooltip /><Bar dataKey="value" fill="#0b5cad" /></BarChart></ResponsiveContainer></div>)}
              <p className="hint">{Object.keys(x.damage_distribution_detected).length ? 'Counts of damage detected by a model.' : 'No model detections exist, so this shows the damage types students declared.'}</p></section>
          </>);
      }}</Async>
    </>
  );
}

/* ------------------------------------------------------------ finance */
interface Month { month: string; premium_income: number; claim_payouts: number; expected_claims: number; operating_expenses: number; ai_technology_expenses: number; risk_reserve: number; expected_surplus: number; actual_surplus: number; assumed_items: string[] }
interface Fin { disclaimer: string; assumptions: Record<string, number>; months: Month[]; totals: Record<string, number>; warnings: string[]; distribution: { name: string; amount: number }[]; assumed_values_used: boolean; formula: string;
  policy_breakdown: { category: string; active_policies: number; monthly_premium: number; annualized_premium: number; premiums_collected: number; claims_paid: number; net: number }[];
  counts: { active_policies: number; insured_students: number; insured_assets: number; monthly_premium_collection: number; annualized_premium_income: number; claims_submitted: number; claims_approved: number; claims_rejected: number; claims_in_review: number; total_payouts: number } }
interface Scen { premium_income: number; rows: { name: string; amount: number }[]; surplus: number; margin_pct: number | null; loss_ratio_pct: number | null; break_even_loss_ratio_pct: number | null; warnings: string[]; disclaimer: string }
const COLORS = ['#0b5cad', '#8a5a00', '#5b4b8a', '#146c2e', '#55606c'];

function Scenario() {
  const [v, setV] = useState({ students: 1000, avg_monthly_premium: 79, expected_claims: 40000, operating_expenses: 12000, ai_technology_expenses: 5000, risk_reserve: 10000 });
  const [res, setRes] = useState<Scen | null>(null);
  const { run, busy } = useAction();
  const n = (k: keyof typeof v) => (e: { target: { value: string } }) => setV(x => ({ ...x, [k]: Number(e.target.value) }));
  const calc = async (e?: FormEvent) => { e?.preventDefault(); await run(async () => setRes(await api<Scen>('/v2/finance/scenario', { method: 'POST', body: v }))); };
  return (
    <section className="card" aria-labelledby="sc-h">
      <h2 id="sc-h" style={{ marginTop: 0 }}>Scenario calculator</h2>
      <p className="muted">Starts with the sample from the project brief: 1,000 students at an average premium of {money(79)}. Change any assumption.</p>
      <form onSubmit={e => void calc(e)} aria-label="Scenario inputs">
        <div className="grid cols">
          <Field label="Students" type="number" min="0" value={v.students} onChange={n('students')} /><Field label="Average monthly premium" type="number" min="0" value={v.avg_monthly_premium} onChange={n('avg_monthly_premium')} />
          <Field label="Expected claims (per month)" type="number" min="0" value={v.expected_claims} onChange={n('expected_claims')} /><Field label="Operating expenses" type="number" min="0" value={v.operating_expenses} onChange={n('operating_expenses')} />
          <Field label="AI and technology expenses" type="number" min="0" value={v.ai_technology_expenses} onChange={n('ai_technology_expenses')} /><Field label="Risk reserve allocation" type="number" min="0" value={v.risk_reserve} onChange={n('risk_reserve')} />
        </div>
        <button type="submit" disabled={busy}>Calculate</button>
      </form>
      {res && (
        <div aria-live="polite">
          {res.warnings.map(w => <Notice kind="error" key={w}>{w}</Notice>)}
          <Table caption="Scenario result" head={['Item', 'Amount per month']} numCols={[1]}>{res.rows.map(r => <tr key={r.name}><td>{r.name}</td><td className="num">{money(r.amount)}</td></tr>)}</Table>
          <p>Margin {res.margin_pct ?? '-'}%. Expected loss ratio {res.loss_ratio_pct ?? '-'}%. Break-even loss ratio {res.break_even_loss_ratio_pct ?? '-'}% (the share of premium that can go to claims before the surplus is zero).</p>
          <p className="hint">{res.disclaimer}</p>
        </div>)}
    </section>
  );
}

export function FinanceV3() {
  usePageTitle('Financial performance');
  const [months, setMonths] = useState(6);
  const f = useLoad(() => api<Fin>(`/v2/finance/summary?months=${months}`), [months]);
  return (
    <>
      <h1>Financial performance</h1>
      <Async state={f}>{x => (
        <>
          <Notice kind="warn">{x.disclaimer}{x.assumed_values_used ? ' Months without recorded expenses use the percentage assumptions below and are marked.' : ''}</Notice>
          {x.warnings.map(w => <Notice kind="error" key={w}>{w}</Notice>)}
          <div className="grid cols">
            <Stat label="Active policies" value={x.counts.active_policies} /><Stat label="Insured students" value={x.counts.insured_students} /><Stat label="Insured assets" value={x.counts.insured_assets} />
            <Stat label="Monthly premium collection" value={money(x.counts.monthly_premium_collection)} /><Stat label="Annualised premium income" value={money(x.counts.annualized_premium_income)} />
            <Stat label="Claims submitted" value={x.counts.claims_submitted} /><Stat label="Approved" value={x.counts.claims_approved} /><Stat label="Rejected" value={x.counts.claims_rejected} />
            <Stat label="Total claim payouts" value={money(x.counts.total_payouts)} />
          </div>
          <div className="row"><label htmlFor="mo">Period</label><select id="mo" value={months} onChange={e => setMonths(Number(e.target.value))}>{[3, 6, 12].map(m => <option key={m} value={m}>Last {m} months</option>)}</select></div>
          <section className="card"><h2 style={{ marginTop: 0 }}>Revenue and expenses</h2>
            <p className="muted">{x.formula}</p>
            <Table caption="Monthly financial performance" head={['Month', 'Premium income', 'Claim payouts', 'Expected claims', 'Operating', 'AI and technology', 'Risk reserve', 'Expected surplus', 'Actual surplus']} numCols={[1, 2, 3, 4, 5, 6, 7, 8]}>
              {x.months.map(m => <tr key={m.month}><td>{m.month}{m.assumed_items.length > 0 ? ' *' : ''}</td><td className="num">{money(m.premium_income)}</td><td className="num">{money(m.claim_payouts)}</td><td className="num">{money(m.expected_claims)}</td><td className="num">{money(m.operating_expenses)}</td>
                <td className="num">{money(m.ai_technology_expenses)}</td><td className="num">{money(m.risk_reserve)}</td><td className="num">{money(m.expected_surplus)}</td><td className="num">{money(m.actual_surplus)}</td></tr>)}
              <tr><th scope="row">Total</th><td className="num">{money(x.totals.premium_income)}</td><td className="num">{money(x.totals.claim_payouts)}</td><td className="num">{money(x.totals.expected_claims)}</td><td className="num">{money(x.totals.operating_expenses)}</td><td className="num">{money(x.totals.ai_technology_expenses)}</td><td className="num">{money(x.totals.risk_reserve)}</td><td className="num">{money(x.totals.expected_surplus)}</td><td className="num">{money(x.totals.actual_surplus)}</td></tr>
            </Table>
            <p className="hint">* uses percentage assumptions: expected claims {x.assumptions.expected_loss_ratio_pct}%, operating {x.assumptions.operating_pct}%, AI and technology {x.assumptions.ai_tech_pct}%, risk reserve {x.assumptions.reserve_pct}% of premium income.</p>
          </section>
          <div className="grid cols2">
            <section className="card"><h2 style={{ marginTop: 0 }}>Revenue vs expenses</h2>
              <div style={{ height: 260 }} role="img" aria-label="Line chart of premium income against total expected costs by month"><ResponsiveContainer><LineChart data={x.months.map(m => ({ month: m.month, Income: m.premium_income, Costs: +(m.expected_claims + m.operating_expenses + m.ai_technology_expenses + m.risk_reserve).toFixed(2) }))}><CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="month" /><YAxis /><Tooltip /><Legend /><Line type="monotone" dataKey="Income" stroke="#0b5cad" strokeWidth={2} /><Line type="monotone" dataKey="Costs" stroke="#a4161a" strokeWidth={2} strokeDasharray="5 3" /></LineChart></ResponsiveContainer></div></section>
            <section className="card"><h2 style={{ marginTop: 0 }}>Where premium income goes</h2>
              <div style={{ height: 260 }} role="img" aria-label={`Pie chart of premium distribution: ${x.distribution.map(d => `${d.name} ${d.amount}`).join(', ')}`}><ResponsiveContainer><PieChart><Pie data={x.distribution} dataKey="amount" nameKey="name" outerRadius={90} label>{x.distribution.map((d, i) => <Cell key={d.name} fill={COLORS[i % COLORS.length]} />)}</Pie><Tooltip /><Legend /></PieChart></ResponsiveContainer></div></section>
            <section className="card"><h2 style={{ marginTop: 0 }}>Premium collection</h2>
              <div style={{ height: 240 }} role="img" aria-label="Bar chart of premium collected per month"><ResponsiveContainer><BarChart data={x.months}><CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="month" /><YAxis /><Tooltip /><Bar dataKey="premium_income" name="Premium income" fill="#0b5cad" /></BarChart></ResponsiveContainer></div></section>
            <section className="card"><h2 style={{ marginTop: 0 }}>Claims payout</h2>
              <div style={{ height: 240 }} role="img" aria-label="Bar chart of claim payouts per month"><ResponsiveContainer><BarChart data={x.months}><CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="month" /><YAxis /><Tooltip /><Bar dataKey="claim_payouts" name="Claim payouts" fill="#8a5a00" /></BarChart></ResponsiveContainer></div></section>
          </div>
          <section className="card"><h2 style={{ marginTop: 0 }}>Policy-wise revenue</h2>
            <Table caption="Revenue by category" head={['Category', 'Active policies', 'Monthly premium', 'Annualised', 'Premiums collected', 'Claims paid', 'Net']} numCols={[1, 2, 3, 4, 5, 6]}>
              {x.policy_breakdown.map(r => <tr key={r.category}><td>{r.category}</td><td className="num">{r.active_policies}</td><td className="num">{money(r.monthly_premium)}</td><td className="num">{money(r.annualized_premium)}</td><td className="num">{money(r.premiums_collected)}</td><td className="num">{money(r.claims_paid)}</td><td className="num">{money(r.net)}</td></tr>)}
            </Table></section>
          <Scenario />
        </>)}</Async>
    </>
  );
}
