import { Link } from 'react-router-dom';
import { api } from '../../api';
import type { Payment } from '../../types';
import { Async, Badge, Notice, Table, Tabs, Panel, dt, money, useLoad, usePageTitle } from '../../ui';
import { useState } from 'react';

interface ReserveRow { claim_id: number; claim_number: string; claim_status: string; recommended: number; approved: number; committed: number }

export default function FinanceOverview({ base }: { base: string }) {
  usePageTitle('Reserves and payments');
  const [tab, setTab] = useState('reserves');
  const res = useLoad(() => api<ReserveRow[]>('/reserves'), []);
  const pay = useLoad(() => api<{ notice: string; payments: Payment[] }>('/payments'), []);
  return (
    <>
      <h1>Reserves &amp; payments</h1>
      <Notice kind="warn">SIMULATED payment workflow: no bank, card or payment gateway is contacted and no money is moved.</Notice>
      <Tabs label="Finance sections" active={tab} onChange={setTab} tabs={[{ id: 'reserves', label: 'Reserves' }, { id: 'payments', label: 'Payments' }]} />
      <Panel id="reserves" active={tab}>
        <Async state={res}>{rows => rows.length === 0 ? <p>No reserves recommended yet.</p> : (
          <>
            <Table caption="Claim reserves" head={['Claim', 'Claim status', 'Recommended', 'Approved', 'Committed', 'Remaining']} numCols={[2, 3, 4, 5]}>
              {rows.map(r => <tr key={r.claim_id}><td><Link to={`${base}/claims/${r.claim_id}`}>{r.claim_number}</Link></td><td><Badge text={r.claim_status} /></td><td className="num">{money(r.recommended)}</td>
                <td className="num">{money(r.approved)}</td><td className="num">{money(r.committed)}</td><td className="num">{money(r.approved - r.committed)}</td></tr>)}
            </Table>
            <p className="muted">Open a claim and use the "Reserves &amp; payments" tab to act on it.</p>
          </>
        )}</Async>
      </Panel>
      <Panel id="payments" active={tab}>
        <Async state={pay}>{d => d.payments.length === 0 ? <p>No payments.</p> : (
          <Table caption="All payments (simulated)" head={['Reference', 'Claim', 'Amount', 'Status', 'Requested by', 'Requested', 'Decided by']} numCols={[2]}>
            {d.payments.map(p => <tr key={p.id}><td>{p.reference}</td><td><Link to={`${base}/claims/${p.claim_id}`}>{p.claim_number}</Link></td><td className="num">{money(p.amount)}</td><td><Badge text={p.status} /></td>
              <td>{p.requested_by}</td><td>{dt(p.requested_at)}</td><td>{p.decided_by ?? '-'}</td></tr>)}
          </Table>
        )}</Async>
      </Panel>
    </>
  );
}
