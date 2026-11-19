import { useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { api } from '../api';
import type { Claim, Finance, Payment } from '../types';
import { Async, Badge, Field, Notice, Table, TextArea, dt, money, num, useAction, useLoad } from '../ui';

// crypto.randomUUID needs a secure context (https or localhost); fall back for plain-http LAN access.
const newKey = () => (typeof crypto !== 'undefined' && 'randomUUID' in crypto ? crypto.randomUUID() : `k-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`);

export default function FinancePanel({ claim, role, onChange }: { claim: Claim; role: 'student' | 'assessor' | 'admin'; onChange: () => void }) {
  const fin = useLoad(() => api<Finance>(`/claims/${claim.id}/finance`), [claim.id, claim.status]);
  const { run, busy } = useAction();
  const refresh = () => { fin.reload(); onChange(); };
  const [amt, setAmt] = useState('');
  const [reason, setReason] = useState('');
  const [er, setEr] = useState('');
  const [pay, setPay] = useState({ amount: '', payee_name: '', notes: '' });
  const [payErr, setPayErr] = useState('');
  // One key per payment form: a double-click or network retry replays safely; a later deliberate identical request gets a duplicate error.
  const payKey = useRef(newKey());
  const [decision, setDecision] = useState<Record<number, string>>({});

  const recommend = async (useEstimate: boolean) => {
    if (!useEstimate && !(Number(amt) >= 0 && amt !== '')) { setEr('Enter an amount of 0 or more, or use the estimate'); return; }
    setEr('');
    if (await run(() => api(`/claims/${claim.id}/reserve/recommend`, { method: 'POST', body: useEstimate ? { use_estimate: true, reason } : { amount: num(amt), reason } }), 'Reserve recommendation saved')) refresh();
  };
  const approve = async () => {
    if (!(Number(amt) > 0)) { setEr('Enter an approved reserve greater than 0'); return; }
    setEr('');
    if (await run(() => api(`/claims/${claim.id}/reserve/approve`, { method: 'POST', body: { amount: num(amt), reason } }), 'Reserve approved')) refresh();
  };
  const release = async () => { if (await run(() => api(`/claims/${claim.id}/reserve/release`, { method: 'POST', body: { reason } }), 'Reserve released')) refresh(); };
  const requestPay = async (e: FormEvent) => {
    e.preventDefault();
    if (!(Number(pay.amount) > 0)) { setPayErr('Enter an amount greater than 0'); return; }
    setPayErr('');
    // The idempotency key makes a double-click or retry a no-op instead of a second payment.
    const key = payKey.current;
    if (await run(() => api(`/claims/${claim.id}/payments`, { method: 'POST', body: { amount: Number(pay.amount), payee_name: pay.payee_name, notes: pay.notes, idempotency_key: key } }), 'Payment requested (simulated)')) { payKey.current = newKey(); setPay({ amount: '', payee_name: '', notes: '' }); refresh(); }
  };
  const act = (p: Payment, what: 'approve' | 'reject' | 'cancel' | 'simulate-settlement', body: object = {}) => async () => {
    const r = decision[p.id] ?? '';
    if ((what === 'reject' || what === 'cancel') && !r.trim()) { setPayErr('A reason is required to reject or cancel a payment'); return; }
    setPayErr('');
    if (await run(() => api(`/payments/${p.id}/${what}`, { method: 'POST', body: { reason: r, ...body } }), `Payment ${what.replace('-', ' ')} done`)) refresh();
  };
  return (
    <Async state={fin}>{f => (
      <>
        <Notice kind="warn">{f.notice}</Notice>
        {role !== 'student' && (
          <section className="card" aria-labelledby="res-h">
            <h3 id="res-h" style={{ marginTop: 0 }}>Reserve</h3>
            <dl className="kv"><dt>Estimated payable</dt><dd>{money(f.estimated_payable)}</dd><dt>Recommended reserve</dt><dd>{money(f.recommended_reserve)}</dd>
              <dt>Approved reserve</dt><dd>{money(f.approved_reserve)}</dd><dt>Committed payments</dt><dd>{money(f.committed)}</dd><dt>Remaining</dt><dd>{money(f.remaining_reserve)}</dd></dl>
            <Field label="Amount (INR)" type="number" min="0" step="0.01" value={amt} onChange={e => setAmt(e.target.value)} error={er} />
            <Field label="Reason" value={reason} onChange={e => setReason(e.target.value)} hint="Required when changing an existing recommendation or approval." />
            <div className="row">
              {role === 'assessor' && <><button className="secondary" disabled={busy} onClick={() => void recommend(true)}>Recommend the estimated payable</button><button disabled={busy} onClick={() => void recommend(false)}>Recommend this amount</button></>}
              {role === 'admin' && <><button disabled={busy} onClick={() => void approve()}>Approve reserve</button><button className="secondary" disabled={busy} onClick={() => void release()}>Release reserve (closed / rejected claims)</button></>}
            </div>
            {role === 'assessor' && <p className="hint">Reserves are approved by an administrator.</p>}
            {(f.history ?? []).length > 0 && <Table caption="Reserve history" head={['When', 'Action', 'Old', 'New', 'By', 'Reason']} numCols={[2, 3]}>
              {(f.history ?? []).map((h, i) => <tr key={i}><td>{dt(h.at)}</td><td>{h.action} ({h.field})</td><td className="num">{money(h.old)}</td><td className="num">{money(h.new)}</td><td>{h.by}</td><td>{h.reason}</td></tr>)}</Table>}
          </section>
        )}
        <h3>Payments</h3>
        {payErr && <div className="alert error" role="alert">{payErr}</div>}
        {f.payments.length === 0 ? <p>No payments.</p> : (
          <Table caption="Payments (simulated)" head={['Reference', 'Amount', 'Payee', 'Status', 'Requested by', 'History', ...(role === 'student' ? [] : ['Actions'])]} numCols={[1]}>
            {f.payments.map(p => (
              <tr key={p.id}>
                <td>{p.reference}</td><td className="num">{money(p.amount)}</td><td>{p.payee_name}</td><td><Badge text={p.status} /></td><td>{p.requested_by}</td>
                <td><ul style={{ margin: 0, paddingLeft: '1rem' }}>{p.events.map((e, i) => <li key={i}>{e.from || 'new'} → {e.to} ({e.by ?? 'system'}, {dt(e.at)}){e.reason ? `: ${e.reason}` : ''}</li>)}</ul></td>
                {role !== 'student' && <td>
                  {['Requested', 'Approved'].includes(p.status) && <Field label="Reason" value={decision[p.id] ?? ''} onChange={e => setDecision(d => ({ ...d, [p.id]: e.target.value }))} />}
                  <div className="row">
                    {role === 'admin' && p.status === 'Requested' && <><button className="sm" disabled={busy} onClick={() => void act(p, 'approve')()}>Approve</button><button className="sm danger" disabled={busy} onClick={() => void act(p, 'reject')()}>Reject</button></>}
                    {role === 'admin' && p.status === 'Approved' && <><button className="sm" disabled={busy} onClick={() => void act(p, 'simulate-settlement', { outcome: 'paid' })()}>Simulate: paid</button><button className="sm secondary" disabled={busy} onClick={() => void act(p, 'simulate-settlement', { outcome: 'failed' })()}>Simulate: failed</button></>}
                    {role === 'assessor' && p.status === 'Requested' && <button className="sm secondary" disabled={busy} onClick={() => void act(p, 'cancel')()}>Cancel request</button>}
                  </div>
                </td>}
              </tr>
            ))}
          </Table>
        )}
        {role === 'assessor' && claim.status === 'Approved for Review' && (
          <form className="card" onSubmit={e => void requestPay(e)} noValidate aria-label="Request payment">
            <h3 style={{ marginTop: 0 }}>Request a payment (simulated)</h3>
            <Field label="Amount (INR)" type="number" min="0.01" step="0.01" value={pay.amount} onChange={e => setPay(x => ({ ...x, amount: e.target.value }))} required />
            <Field label="Payee name" value={pay.payee_name} onChange={e => setPay(x => ({ ...x, payee_name: e.target.value }))} maxLength={120} />
            <TextArea label="Notes" value={pay.notes} onChange={e => setPay(x => ({ ...x, notes: e.target.value }))} maxLength={1000} />
            <button type="submit" disabled={busy}>Request payment</button>
            <p className="hint">An administrator other than you must approve it (four-eyes rule). Duplicate identical requests are rejected.</p>
          </form>
        )}
      </>
    )}</Async>
  );
}
