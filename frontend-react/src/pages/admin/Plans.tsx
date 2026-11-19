import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { api } from '../../api';
import { useAuth } from '../../auth';
import type { Exclusion, Plan } from '../../types';
import { Async, Check, Field, Notice, Select, Table, TextArea, money, useAction, useLoad, usePageTitle } from '../../ui';

export function PlanList({ base = '/admin' }: { base?: string }) {
  usePageTitle('Plans');
  const plans = useLoad(() => api<Plan[]>('/plans'), []);
  return (
    <>
      <h1>Plans &amp; exclusions</h1>
      {base === '/admin' && <p><Link className="btn" to="/admin/plans/new">Create plan</Link></p>}
      <Async state={plans}>{rows => (
        <Table caption="Coverage plans" head={['Plan', 'Overall limit', 'Deductible', 'Waiting period', 'Exclusions', 'Perils']} numCols={[1]}>
          {rows.map(p => <tr key={p.id}><td><Link to={`${base}/plans/${p.id}`}>{p.name}</Link></td><td className="num">{money(p.overall_limit)}</td>
            <td>{p.deductible_type === 'percent' ? `${p.deductible_value}%` : money(p.deductible_value)}</td><td>{p.waiting_period_days} d</td><td>{p.exclusions.length}</td><td>{p.covered_perils.join(', ')}</td></tr>)}
        </Table>
      )}</Async>
    </>
  );
}

const RULES = Array.from({ length: 13 }, (_, i) => `POL-${String(i + 1).padStart(3, '0')}`);
interface F {
  name: string; description: string; covered_perils: string[]; overall_limit: string; default_per_item_limit: string; per_item_limits: Record<string, string>; cap_at_declared_value: boolean;
  deductible_type: string; deductible_value: string; calc_order: string; dep_enabled: boolean; dep_rate: string; dep_max: string; dep_applies: string; waiting_period_days: string;
  required_documents: Record<string, string[]>; duplicate_window_days: string; repair_replace_threshold_pct: string; disabled_rules: string[]; wording: string; exclusions: Exclusion[];
}
const empty: F = { name: '', description: '', covered_perils: [], overall_limit: '', default_per_item_limit: '', per_item_limits: {}, cap_at_declared_value: true, deductible_type: 'fixed', deductible_value: '0',
  calc_order: 'LIMIT_THEN_DEDUCTIBLE', dep_enabled: false, dep_rate: '10', dep_max: '50', dep_applies: 'replace', waiting_period_days: '0', required_documents: {}, duplicate_window_days: '0',
  repair_replace_threshold_pct: '70', disabled_rules: [], wording: '', exclusions: [] };
const fromPlan = (p: Plan): F => ({ name: p.name, description: p.description, covered_perils: p.covered_perils, overall_limit: String(p.overall_limit), default_per_item_limit: p.default_per_item_limit == null ? '' : String(p.default_per_item_limit),
  per_item_limits: Object.fromEntries(Object.entries(p.per_item_limits).map(([k, v]) => [k, String(v)])), cap_at_declared_value: p.cap_at_declared_value, deductible_type: p.deductible_type, deductible_value: String(p.deductible_value),
  calc_order: p.calc_order, dep_enabled: !!p.depreciation?.enabled, dep_rate: String(p.depreciation?.rate_per_year_pct ?? 10), dep_max: String(p.depreciation?.max_pct ?? 50), dep_applies: p.depreciation?.applies_to ?? 'replace',
  waiting_period_days: String(p.waiting_period_days), required_documents: p.required_documents, duplicate_window_days: String(p.duplicate_window_days), repair_replace_threshold_pct: String(p.repair_replace_threshold_pct),
  disabled_rules: p.disabled_rules, wording: p.wording, exclusions: p.exclusions });

export function PlanEditor({ isNew = false }: { isNew?: boolean }) {
  const { id } = useParams();
  const nav = useNavigate();
  const { meta } = useAuth();
  usePageTitle(isNew ? 'Create plan' : 'Edit plan');
  const plan = useLoad(() => (isNew ? Promise.resolve(null) : api<Plan>(`/plans/${id}`)), [id]);
  const [f, setF] = useState<F>(empty);
  const [er, setEr] = useState<Record<string, string>>({});
  const { run, busy } = useAction();
  useEffect(() => { if (plan.data) setF(fromPlan(plan.data)); }, [plan.data]);
  const set = <K extends keyof F>(k: K, v: F[K]) => setF(x => ({ ...x, [k]: v }));
  const tog = (list: string[], v: string) => (list.includes(v) ? list.filter(i => i !== v) : [...list, v]);
  const num = (s: string) => Number(s);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const x: Record<string, string> = {};
    if (!f.name.trim()) x.name = 'Enter a plan name';
    if (f.covered_perils.length === 0) x.perils = 'Select at least one covered peril';
    if (!(num(f.overall_limit) > 0)) x.overall_limit = 'Enter an overall limit greater than 0';
    if (f.default_per_item_limit !== '' && !(num(f.default_per_item_limit) > 0)) x.dpl = 'Must be greater than 0 or blank';
    if (!(num(f.deductible_value) >= 0)) x.ded = 'Enter 0 or more';
    if (f.deductible_type === 'percent' && num(f.deductible_value) > 100) x.ded = 'A percentage deductible cannot exceed 100';
    if (!(num(f.repair_replace_threshold_pct) > 0 && num(f.repair_replace_threshold_pct) <= 100)) x.thr = 'Enter a percentage between 1 and 100';
    if (f.exclusions.some(ex => !ex.code.trim() || !ex.title.trim())) x.excl = 'Every exclusion needs a code and a title';
    if (new Set(f.exclusions.map(ex => ex.code)).size !== f.exclusions.length) x.excl = 'Exclusion codes must be unique';
    setEr(x);
    if (Object.keys(x).length) return;
    const body = {
      name: f.name, description: f.description, covered_perils: f.covered_perils, overall_limit: num(f.overall_limit), default_per_item_limit: f.default_per_item_limit === '' ? null : num(f.default_per_item_limit),
      per_item_limits: Object.fromEntries(Object.entries(f.per_item_limits).filter(([, v]) => v !== '').map(([k, v]) => [k, num(v)])), cap_at_declared_value: f.cap_at_declared_value,
      deductible_type: f.deductible_type, deductible_value: num(f.deductible_value), calc_order: f.calc_order,
      depreciation: f.dep_enabled ? { enabled: true, rate_per_year_pct: num(f.dep_rate), max_pct: num(f.dep_max), applies_to: f.dep_applies } : {},
      waiting_period_days: num(f.waiting_period_days), required_documents: f.required_documents, duplicate_window_days: num(f.duplicate_window_days),
      repair_replace_threshold_pct: num(f.repair_replace_threshold_pct), disabled_rules: f.disabled_rules, wording: f.wording, exclusions: f.exclusions,
    };
    let nid = id;
    if (await run(async () => { const r = await (isNew ? api<Plan>('/plans', { method: 'POST', body }) : api<Plan>(`/plans/${id}`, { method: 'PUT', body })); nid = String(r.id); },
      isNew ? 'Plan created' : 'Plan saved. Existing policies keep their terms until re-issued.')) nav(`/admin/plans/${nid}`);
  };
  const setEx = (i: number, patch: Partial<Exclusion>) => set('exclusions', f.exclusions.map((e, j) => (j === i ? { ...e, ...patch } : e)));
  return (
    <>
      <p><Link to="/admin/plans">&larr; All plans</Link></p>
      <h1>{isNew ? 'Create plan' : `Edit plan: ${plan.data?.name ?? ''}`}</h1>
      <Async state={{ ...plan, data: isNew ? ({} as Plan) : plan.data }}>{() => (
        <form onSubmit={e => void submit(e)} noValidate aria-label="Plan editor">
          {!isNew && <Notice>Saving a plan does not change existing policies. Use "Re-issue" on a policy to apply new terms as a new version.</Notice>}
          <fieldset className="card"><legend>General</legend>
            <Field label="Plan name" value={f.name} onChange={e => set('name', e.target.value)} error={er.name} maxLength={80} required />
            <TextArea label="Description" value={f.description} onChange={e => set('description', e.target.value)} />
            <fieldset><legend>Covered perils {er.perils && <span className="field-error" role="alert">{er.perils}</span>}</legend>
              {(meta?.incident_types ?? []).map(t => <Check key={t} label={t} checked={f.covered_perils.includes(t)} onChange={() => set('covered_perils', tog(f.covered_perils, t))} />)}</fieldset>
          </fieldset>
          <fieldset className="card"><legend>Limits and deductible</legend>
            <div className="grid cols">
              <Field label="Overall limit (INR)" type="number" min="1" step="0.01" value={f.overall_limit} onChange={e => set('overall_limit', e.target.value)} error={er.overall_limit} required />
              <Field label="Default per-item limit (INR)" type="number" min="1" step="0.01" value={f.default_per_item_limit} onChange={e => set('default_per_item_limit', e.target.value)} error={er.dpl} hint="Blank = none" />
              <Select label="Deductible type" value={f.deductible_type} onChange={e => set('deductible_type', e.target.value)} options={['fixed', 'percent']} />
              <Field label={f.deductible_type === 'percent' ? 'Deductible (%)' : 'Deductible (INR)'} type="number" min="0" step="0.01" value={f.deductible_value} onChange={e => set('deductible_value', e.target.value)} error={er.ded} />
              <Select label="Calculation order" value={f.calc_order} onChange={e => set('calc_order', e.target.value)} options={['LIMIT_THEN_DEDUCTIBLE', 'DEDUCTIBLE_THEN_LIMIT']} />
            </div>
            <Check label="Cap payment at declared value of the asset" checked={f.cap_at_declared_value} onChange={e => set('cap_at_declared_value', e.target.checked)} />
            <h3>Per-category limits (INR, blank = none)</h3>
            <div className="grid cols">{(meta?.asset_categories ?? []).map(c => <Field key={c} label={c} type="number" min="1" value={f.per_item_limits[c] ?? ''} onChange={e => set('per_item_limits', { ...f.per_item_limits, [c]: e.target.value })} />)}</div>
          </fieldset>
          <fieldset className="card"><legend>Conditions</legend>
            <div className="grid cols">
              <Field label="Waiting period (days)" type="number" min="0" value={f.waiting_period_days} onChange={e => set('waiting_period_days', e.target.value)} />
              <Field label="Duplicate-claim window (days)" type="number" min="0" value={f.duplicate_window_days} onChange={e => set('duplicate_window_days', e.target.value)} />
              <Field label="Repair vs replace threshold (%)" type="number" min="1" max="100" value={f.repair_replace_threshold_pct} onChange={e => set('repair_replace_threshold_pct', e.target.value)} error={er.thr} />
            </div>
            <Check label="Apply depreciation" checked={f.dep_enabled} onChange={e => set('dep_enabled', e.target.checked)} />
            {f.dep_enabled && <div className="grid cols"><Field label="Rate per year (%)" type="number" min="0" value={f.dep_rate} onChange={e => set('dep_rate', e.target.value)} /><Field label="Maximum (%)" type="number" min="0" max="100" value={f.dep_max} onChange={e => set('dep_max', e.target.value)} />
              <Select label="Applies to" value={f.dep_applies} onChange={e => set('dep_applies', e.target.value)} options={['replace', 'all']} /></div>}
            <fieldset><legend>Disabled rules (switch a rule off for this plan)</legend><div className="row">{RULES.map(r => <Check key={r} label={r} checked={f.disabled_rules.includes(r)} onChange={() => set('disabled_rules', tog(f.disabled_rules, r))} />)}</div></fieldset>
          </fieldset>
          <fieldset className="card"><legend>Required documents by incident type</legend>
            {(meta?.incident_types ?? []).map(t => (
              <fieldset key={t}><legend>{t}</legend><div className="row">{(meta?.doc_types ?? []).map(d => <Check key={d} label={d} checked={(f.required_documents[t] ?? []).includes(d)}
                onChange={() => set('required_documents', { ...f.required_documents, [t]: tog(f.required_documents[t] ?? [], d) })} />)}</div></fieldset>
            ))}
          </fieldset>
          <fieldset className="card"><legend>Exclusions</legend>
            {er.excl && <div className="field-error" role="alert">{er.excl}</div>}
            {f.exclusions.map((ex, i) => (
              <div key={i} className="card" role="group" aria-label={`Exclusion ${i + 1}`}>
                <div className="grid cols"><Field label="Code" value={ex.code} maxLength={20} onChange={e => setEx(i, { code: e.target.value })} /><Field label="Title" value={ex.title} onChange={e => setEx(i, { title: e.target.value })} /></div>
                <Field label="Policy clause" value={ex.clause} maxLength={300} onChange={e => setEx(i, { clause: e.target.value })} />
                <fieldset><legend>Incident types</legend><div className="row">{(meta?.incident_types ?? []).map(t => <Check key={t} label={t} checked={ex.incident_types.includes(t)} onChange={() => setEx(i, { incident_types: tog(ex.incident_types, t) })} />)}</div></fieldset>
                <fieldset><legend>Damage types</legend><div className="row">{(meta?.damage_types ?? []).map(t => <Check key={t} label={t} checked={ex.damage_types.includes(t)} onChange={() => setEx(i, { damage_types: tog(ex.damage_types, t) })} />)}</div></fieldset>
                <fieldset><legend>Severities</legend><div className="row">{(meta?.severities ?? []).map(t => <Check key={t} label={t} checked={ex.severities.includes(t)} onChange={() => setEx(i, { severities: tog(ex.severities, t) })} />)}</div></fieldset>
                <button type="button" className="danger sm" onClick={() => set('exclusions', f.exclusions.filter((_, j) => j !== i))}>Remove exclusion {i + 1}</button>
              </div>
            ))}
            <button type="button" className="secondary" onClick={() => set('exclusions', [...f.exclusions, { code: '', title: '', clause: '', incident_types: [], damage_types: [], severities: [] }])}>Add exclusion</button>
          </fieldset>
          <fieldset className="card"><legend>Policy wording</legend><TextArea label="Wording shown to policy holders" value={f.wording} onChange={e => set('wording', e.target.value)} style={{ minHeight: '10rem' }} /></fieldset>
          <button type="submit" disabled={busy}>{isNew ? 'Create plan' : 'Save plan'}</button>
        </form>
      )}</Async>
    </>
  );
}
