import { useState } from 'react';
import { api } from '../api';
import type { AISuggestion, Claim, Evaluation } from '../types';
import { Badge, ErrorBox, Loading, Notice, Table, money, useAction, useLoad } from '../ui';
import AiResult from './AiResult';

export default function AssessmentPanel({ claim, role, onChange }: { claim: Claim; role: 'student' | 'assessor' | 'admin'; onChange: () => void }) {
  const ev = useLoad(() => api<Evaluation>(`/claims/${claim.id}/evaluation`).catch(() => null), [claim.id, claim.status, claim.estimated_payable, (claim.items ?? []).length]);
  const { run, busy } = useAction();
  const [ai, setAi] = useState<AISuggestion | null>(null);
  const evaluate = () => run(() => api(`/claims/${claim.id}/evaluate`, { method: 'POST' }), 'Rules re-evaluated').then(ok => { if (ok) { ev.reload(); onChange(); } });
  const explain = () => run(async () => setAi(await api<AISuggestion>(`/ai/claims/${claim.id}/explain`, { method: 'POST', body: {} })));
  const staff = role !== 'student';
  return (
    <>
      <Notice kind="info">This is an estimate prepared by the rules engine. It is a recommendation, not a settlement. A human assessor makes the final decision.</Notice>
      <div className="row">
        {staff && claim.status !== 'Draft' && <button className="secondary" disabled={busy} onClick={() => void evaluate()}>Re-run rules and calculation</button>}
        <button className="secondary" disabled={busy || claim.status === 'Draft'} onClick={() => void explain()}>Explain this assessment in plain language</button>
      </div>
      {claim.status === 'Draft' && <p className="muted">The assessment appears after the claim is submitted.</p>}
      {ai && <AiResult s={ai} />}
      {ev.error ? <ErrorBox message={ev.error} /> : ev.loading && !ev.data ? <Loading /> : ev.data ? <Detail e={ev.data} staff={staff} claim={claim} /> : claim.status !== 'Draft' ? <p>No assessment has been run yet.</p> : null}
    </>
  );
}

function Detail({ e, staff, claim }: { e: Evaluation; staff: boolean; claim: Claim }) {
  if (!e.run) return null;
  const s = e.calculation_summary;
  return (
    <>
      {e.stale && <Notice kind="warn">Claim data has changed since this evaluation. Re-run it to refresh.</Notice>}
      <section className="card" aria-labelledby="rec-h">
        <h3 id="rec-h" style={{ marginTop: 0 }}>Recommendation (policy version v{e.policy_version})</h3>
        <p><Badge text={e.recommendation} /></p>
        <ul>{e.recommendation_reasons.map(r => <li key={r}>{r}</li>)}</ul>
        <p>Estimated payable: <strong>{money(e.estimated_payable)}</strong></p>
        {claim.decision_reason && <p>Assessor decision reason: {claim.decision_reason}</p>}
      </section>
      {s && (
        <>
          <h3>Calculation summary</h3>
          <dl className="kv card">
            <dt>Gross claimed</dt><dd>{money(s.gross_total)}</dd><dt>Excluded</dt><dd>{money(s.excluded_total)}</dd><dt>Depreciation</dt><dd>{money(s.depreciation_total)}</dd>
            <dt>Eligible subtotal</dt><dd>{money(s.eligible_subtotal)}</dd><dt>Deductible applied</dt><dd>{money(s.deductible_applied)}</dd><dt>Estimated payable</dt><dd><strong>{money(s.estimated_payable)}</strong></dd>
          </dl>
          {s.flags.length > 0 && <Notice kind="warn">{s.flags.join(' ')}</Notice>}
        </>
      )}
      <h3>Itemised calculation</h3>
      <Table caption="Itemised calculation lines" head={['#', 'Step', 'Amount', 'Running total', 'Rule', 'Note']} numCols={[0, 2, 3]}>
        {e.calculation_lines.map(l => <tr key={l.seq}><td className="num">{l.seq}</td><td>{l.label}</td><td className="num">{money(l.amount)}</td><td className="num">{money(l.running_total)}</td><td>{l.rule_ref}</td><td>{l.note}</td></tr>)}
      </Table>
      {staff ? (
        <>
          <h3>Rule execution trace</h3>
          <Table caption="Rule execution trace" head={['Rule', 'Name', 'Outcome', 'Reason', 'Policy clause', 'Follow-up']}>
            {e.rule_results.map((r, i) => <tr key={i}><td>{r.rule_id}</td><td>{r.rule_name}</td><td><Badge text={r.outcome} /></td><td>{r.reason}</td><td>{r.clause}</td><td>{r.follow_up}</td></tr>)}
          </Table>
        </>
      ) : (
        <>
          <h3>How the rules applied to your claim</h3>
          <Table caption="Rules applied" head={['Check', 'Result', 'Why']}>
            {e.rule_results.map((r, i) => <tr key={i}><td>{r.rule_name}</td><td><Badge text={r.outcome} /></td><td>{r.reason}{r.follow_up ? ` ${r.follow_up}` : ''}</td></tr>)}
          </Table>
        </>
      )}
    </>
  );
}
