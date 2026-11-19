import { Link } from 'react-router-dom';
import { api } from '../../api';
import type { Claim } from '../../types';
import { Async, Badge, Notice, Stat, Table, money, useLoad, usePageTitle } from '../../ui';

interface Overview { claims_by_status: Record<string, number>; claims_total: number; unassigned_open: number; aging_over_7_days: Claim[];
  reserves: { recommended: number; approved: number; paid_simulated: number }; payments_by_status: Record<string, number>; payment_mode: string;
  security: { active_sessions: number; failed_logins_24h: number; active_users: number } }

export default function AdminDashboard() {
  usePageTitle('Dashboard');
  const o = useLoad(() => api<Overview>('/admin/overview'), []);
  return (
    <>
      <h1>Administrator dashboard</h1>
      <Async state={o}>{d => (
        <>
          <div className="grid cols">
            <Stat label="Claims" value={d.claims_total} /><Stat label="Unassigned open claims" value={d.unassigned_open} />
            <Stat label="Recommended reserves" value={money(d.reserves.recommended)} /><Stat label="Approved reserves" value={money(d.reserves.approved)} />
            <Stat label="Paid (simulated)" value={money(d.reserves.paid_simulated)} />
            <Stat label="Payments awaiting approval" value={d.payments_by_status.Requested ?? 0} />
          </div>
          <Notice kind="warn">Payments are {d.payment_mode}: no money moves.</Notice>
          <h2>Claims by status</h2>
          <Table caption="Claims by status" head={['Status', 'Claims']} numCols={[1]}>
            {Object.entries(d.claims_by_status).map(([k, v]) => <tr key={k}><td><Badge text={k} /></td><td className="num">{v}</td></tr>)}
          </Table>
          <h2>Open claims older than 7 days</h2>
          {d.aging_over_7_days.length === 0 ? <p>None.</p> : (
            <Table caption="Aging claims" head={['Claim', 'Claimant', 'Status', 'Submitted']}>
              {d.aging_over_7_days.map(c => <tr key={c.id}><td><Link to={`/admin/claims/${c.id}`}>{c.claim_number}</Link></td><td>{c.claimant_name}</td><td><Badge text={c.status} /></td><td>{c.submitted_at?.slice(0, 10)}</td></tr>)}
            </Table>
          )}
          <h2>Security</h2>
          <dl className="kv card"><dt>Active users</dt><dd>{d.security.active_users}</dd><dt>Active sessions</dt><dd>{d.security.active_sessions}</dd><dt>Failed sign-ins (24h)</dt><dd>{d.security.failed_logins_24h}</dd></dl>
        </>
      )}</Async>
    </>
  );
}
