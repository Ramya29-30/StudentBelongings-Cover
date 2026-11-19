import { api } from '../api';
import type { AuditRow, Claim } from '../types';
import { Async, Table, dt, useLoad } from '../ui';

export default function HistoryPanel({ claim }: { claim: Claim }) {
  const audit = useLoad(() => api<AuditRow[]>(`/claims/${claim.id}/audit`), [claim.id, claim.status, (claim.items ?? []).length]);
  return (
    <>
      <h3>Status history</h3>
      <Table caption="Claim status history" head={['When', 'From', 'To', 'By', 'Reason']}>
        {(claim.status_history ?? []).map((h, i) => <tr key={i}><td>{dt(h.changed_at)}</td><td>{h.from || '-'}</td><td>{h.to}</td><td>{h.changed_by}</td><td>{h.reason}</td></tr>)}
      </Table>
      <h3>Audit history</h3>
      <Async state={audit}>{rows => rows.length === 0 ? <p>No audit entries.</p> : (
        <Table caption="Claim audit history" head={['When', 'User', 'Action', 'Detail']}>
          {rows.map(a => <tr key={a.id}><td>{dt(a.created_at)}</td><td>{a.username}</td><td>{a.action.replace(/_/g, ' ')}</td><td className="mono" style={{ fontSize: '.8rem', wordBreak: 'break-word' }}>{JSON.stringify(a.detail).slice(0, 300)}</td></tr>)}
        </Table>
      )}</Async>
    </>
  );
}
