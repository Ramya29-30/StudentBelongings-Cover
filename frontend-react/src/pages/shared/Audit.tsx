import { useState } from 'react';
import { api } from '../../api';
import type { AuditRow } from '../../types';
import { Async, Select, Table, dt, useLoad, usePageTitle } from '../../ui';

const TYPES = ['claim', 'claim_item', 'policy', 'plan', 'user', 'reserve', 'payment', 'ai_suggestion', 'system', 'asset', 'catalogue'];
export default function AuditPage() {
  usePageTitle('Audit history');
  const [type, setType] = useState('');
  const [limit, setLimit] = useState('100');
  const rows = useLoad(() => api<AuditRow[]>(`/audit?limit=${limit}${type ? `&entity_type=${type}` : ''}`), [type, limit]);
  return (
    <>
      <h1>Audit history</h1>
      <p className="muted">Every create, change, decision, reserve and payment action is recorded with the user and time.</p>
      <div className="row">
        <div><Select label="Entity type" value={type} onChange={e => setType(e.target.value)} options={TYPES} placeholder="All" /></div>
        <div><Select label="Rows" value={limit} onChange={e => setLimit(e.target.value)} options={['50', '100', '250', '500']} /></div>
      </div>
      <Async state={rows}>{r => r.length === 0 ? <p>No entries.</p> : (
        <Table caption="Audit log" head={['When', 'User', 'Entity', 'Action', 'Detail']}>
          {r.map(a => <tr key={a.id}><td>{dt(a.created_at)}</td><td>{a.username}</td><td>{a.entity_type} #{a.entity_id}</td><td>{a.action.replace(/_/g, ' ')}</td>
            <td className="mono" style={{ fontSize: '.8rem', wordBreak: 'break-word' }}>{JSON.stringify(a.detail).slice(0, 240)}</td></tr>)}
        </Table>
      )}</Async>
    </>
  );
}
