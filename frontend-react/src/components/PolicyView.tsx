import type { Policy, Terms } from '../types';
import { Badge, Table, money } from '../ui';

export function TermsView({ t }: { t: Terms }) {
  const ded = t.deductible_type === 'percent' ? `${t.deductible_value}% of the eligible amount` : money(t.deductible_value);
  return (
    <>
      <section className="card" aria-labelledby="lim-h">
        <h3 id="lim-h" style={{ marginTop: 0 }}>Coverage limits, deductible and conditions</h3>
        <dl className="kv">
          <dt>Plan</dt><dd>{t.plan_name}</dd>
          <dt>Overall limit</dt><dd>{money(t.overall_limit)}</dd>
          <dt>Default per-item limit</dt><dd>{t.default_per_item_limit == null ? 'None' : money(t.default_per_item_limit)}</dd>
          <dt>Capped at declared value</dt><dd>{t.cap_at_declared_value ? 'Yes' : 'No'}</dd>
          <dt>Deductible</dt><dd>{ded}</dd>
          <dt>Calculation order</dt><dd>{t.calc_order === 'LIMIT_THEN_DEDUCTIBLE' ? 'Limits first, then deductible' : 'Deductible first, then limits'}</dd>
          <dt>Waiting period</dt><dd>{t.waiting_period_days} day(s) from cover start</dd>
          <dt>Duplicate-claim window</dt><dd>{t.duplicate_window_days} day(s)</dd>
          <dt>Repair vs replace threshold</dt><dd>{t.repair_replace_threshold_pct}% of replacement cost</dd>
          <dt>Depreciation</dt><dd>{t.depreciation?.enabled ? `${t.depreciation.rate_per_year_pct}% a year, max ${t.depreciation.max_pct}%` : 'Not applied'}</dd>
          <dt>Covered perils</dt><dd>{t.covered_perils.join(', ')}</dd>
        </dl>
      </section>
      {Object.keys(t.per_item_limits).length > 0 && (
        <Table caption="Per-category limits" head={['Category', 'Limit']} numCols={[1]}>
          {Object.entries(t.per_item_limits).map(([k, v]) => <tr key={k}><td>{k}</td><td className="num">{money(v)}</td></tr>)}
        </Table>
      )}
      <h3>Exclusions</h3>
      {t.exclusions.length === 0 ? <p>No exclusions configured.</p> : (
        <Table caption="Policy exclusions" head={['Code', 'Exclusion', 'Clause', 'Applies to']}>
          {t.exclusions.map(e => <tr key={e.code}><td>{e.code}</td><td>{e.title}</td><td>{e.clause}</td>
            <td>{[...e.incident_types, ...e.damage_types, ...e.severities].join(', ') || 'All'}</td></tr>)}
        </Table>
      )}
      <h3>Required documents by incident type</h3>
      {Object.keys(t.required_documents).length === 0 ? <p>None required.</p> : (
        <Table caption="Required documents" head={['Incident type', 'Documents']}>
          {Object.entries(t.required_documents).map(([k, v]) => <tr key={k}><td>{k}</td><td>{v.join(', ') || '-'}</td></tr>)}
        </Table>
      )}
      {t.disabled_rules.length > 0 && <p className="muted">Disabled rules: {t.disabled_rules.join(', ')}</p>}
    </>
  );
}

export function PolicySummary({ p }: { p: Policy }) {
  return (
    <dl className="kv">
      <dt>Policy number</dt><dd>{p.policy_number}</dd>
      <dt>Policy holder</dt><dd>{p.student_name}</dd>
      <dt>Status</dt><dd><Badge text={p.status} /></dd>
      <dt>Period</dt><dd>{p.start_date} to {p.end_date}</dd>
      <dt>Activated</dt><dd>{p.activated_on ?? '-'}</dd>
      {p.cancelled_on && <><dt>Cancelled</dt><dd>{p.cancelled_on} ({p.cancellation_reason})</dd></>}
      <dt>Current version</dt><dd>{p.current_version}</dd>
    </dl>
  );
}
