import { useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../../api';
import { useAuth } from '../../auth';
import type { Claim } from '../../types';
import { Async, Badge, Stat, Table, Tabs, Panel, money, useLoad, usePageTitle } from '../../ui';
import { ClaimList } from '../student/Claims';

interface Dash { claims_by_status: Record<string, number>; awaiting_assessor: number; pending_information: number; estimated_payable_open: number; recent_claims: Claim[] }

export function AssessorDashboard() {
  usePageTitle('Dashboard');
  const { user } = useAuth();
  const d = useLoad(() => api<Dash>('/dashboard'), []);
  const mine = useLoad(() => api<Claim[]>('/claims?assigned=me'), []);
  const queue = useLoad(() => api<Claim[]>('/claims?assigned=unassigned'), []);
  const open = (mine.data ?? []).filter(c => !['Closed', 'Rejected with Reason'].includes(c.status));
  return (
    <>
      <h1>Assessor dashboard - {user?.full_name}</h1>
      <Async state={d}>{x => (
        <div className="grid cols">
          <Stat label="Awaiting assessment" value={x.awaiting_assessor} /><Stat label="Pending information" value={x.pending_information} />
          <Stat label="Assigned to me (open)" value={open.length} /><Stat label="Unassigned" value={queue.data?.length ?? '-'} />
          <Stat label="Estimated payable (open)" value={money(x.estimated_payable_open)} />
        </div>
      )}</Async>
      <h2>My assigned claims</h2>
      <Async state={mine}>{() => open.length === 0 ? <p>Nothing assigned to you. See <Link to="/assessor/claims">the claims queue</Link>.</p> : (
        <Table caption="Claims assigned to me" head={['Claim', 'Claimant', 'Item', 'Status']}>
          {open.map(c => <tr key={c.id}><td><Link to={`/assessor/claims/${c.id}`}>{c.claim_number}</Link></td><td>{c.claimant_name}</td><td>{c.asset_name}</td><td><Badge text={c.status} /></td></tr>)}
        </Table>
      )}</Async>
    </>
  );
}

export function AssessorClaims() {
  const [tab, setTab] = useState('mine');
  return (
    <>
      <h1>Claims</h1>
      <Tabs label="Claim queues" active={tab} onChange={setTab} tabs={[{ id: 'mine', label: 'Assigned to me' }, { id: 'unassigned', label: 'Unassigned' }, { id: 'all', label: 'All claims' }]} />
      <Panel id="mine" active={tab}><ClaimList base="/assessor" scope="mine" /></Panel>
      <Panel id="unassigned" active={tab}><ClaimList base="/assessor" scope="unassigned" /></Panel>
      <Panel id="all" active={tab}><ClaimList base="/assessor" scope="all" /></Panel>
    </>
  );
}
