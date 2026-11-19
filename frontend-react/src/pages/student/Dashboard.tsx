import { Link } from 'react-router-dom';
import { api } from '../../api';
import type { Claim, Policy } from '../../types';
import { Async, Badge, Stat, Table, money, useLoad, usePageTitle } from '../../ui';
import { useAuth } from '../../auth';

interface Dash { assets: number; insured_value: number; policies_by_status: Record<string, number>; claims_by_status: Record<string, number>; open_claims: number;
  pending_information: number; awaiting_assessor: number; recent_claims: Claim[]; recent_policies: Policy[] }

export default function StudentDashboard() {
  usePageTitle('Dashboard');
  const { user } = useAuth();
  const s = useLoad(() => api<Dash>('/dashboard'), []);
  return (
    <>
      <h1>Welcome, {user?.full_name}</h1>
      <Async state={s}>{d => (
        <>
          <div className="grid cols">
            <Stat label="Assets" value={d.assets} />
            <Stat label="Declared value" value={money(d.insured_value)} />
            <Stat label="Active policies" value={d.policies_by_status.Active ?? 0} />
            <Stat label="Open claims" value={d.open_claims} />
          </div>
          {d.pending_information > 0 && <div className="alert warn" role="status">{d.pending_information} claim(s) need more information from you. <Link to="/student/claims">Open Claim Centre</Link></div>}
          <h2>Recent claims</h2>
          {d.recent_claims.length === 0 ? <p>No claims yet. <Link to="/student/claims/new">Register a claim</Link>.</p> : (
            <Table caption="Recent claims" head={['Claim', 'Item', 'Incident', 'Status']}>
              {d.recent_claims.map(c => <tr key={c.id}><td><Link to={`/student/claims/${c.id}`}>{c.claim_number}</Link></td><td>{c.asset_name}</td><td>{c.incident_type}</td><td><Badge text={c.status} /></td></tr>)}
            </Table>
          )}
          <h2>Your policies</h2>
          <Table caption="Recent policies" head={['Policy', 'Plan', 'Period', 'Status']}>
            {d.recent_policies.map(p => <tr key={p.id}><td><Link to={`/student/policies/${p.id}`}>{p.policy_number}</Link></td><td>{p.plan_name}</td><td>{p.start_date} to {p.end_date}</td><td><Badge text={p.status} /></td></tr>)}
          </Table>
        </>
      )}</Async>
    </>
  );
}
