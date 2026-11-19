import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { api } from '../../api';
import type { AISuggestion, Policy } from '../../types';
import { Async, Badge, Panel, Table, Tabs, money, useAction, useLoad, usePageTitle } from '../../ui';
import { PolicySummary, TermsView } from '../../components/PolicyView';
import AiResult from '../../components/AiResult';

export function PolicyCentre({ base = '/student' }: { base?: string }) {
  usePageTitle('Policy Centre');
  const list = useLoad(() => api<Policy[]>('/policies'), []);
  return (
    <>
      <h1>Policy Centre</h1>
      <Async state={list}>{rows => rows.length === 0 ? <p>No policies found.</p> : (
        <Table caption="Policies" head={['Policy', 'Holder', 'Plan', 'Period', 'Assets', 'Version', 'Status']}>
          {rows.map(p => <tr key={p.id}><td><Link to={`${base}/policies/${p.id}`}>{p.policy_number}</Link></td><td>{p.student_name}</td><td>{p.plan_name}</td>
            <td>{p.start_date} to {p.end_date}</td><td>{p.asset_count}</td><td>v{p.current_version}</td><td><Badge text={p.status} /></td></tr>)}
        </Table>
      )}</Async>
    </>
  );
}

export function PolicyDetails({ base = '/student' }: { base?: string }) {
  const { id } = useParams();
  const s = useLoad(() => api<Policy>(`/policies/${id}`), [id]);
  const [tab, setTab] = useState('cover');
  usePageTitle('Policy details');
  const { run, busy } = useAction();
  const [ai, setAi] = useState<AISuggestion | null>(null);
  const explain = () => run(async () => { setAi(await api<AISuggestion>(`/ai/policies/${id}/explain`, { method: 'POST', body: {} })); });
  return (
    <Async state={s}>{p => {
      const cur = p.versions?.[p.versions.length - 1];
      return (
        <>
          <p><Link to={`${base}/policies`}>&larr; All policies</Link></p>
          <h1>Policy {p.policy_number}</h1>
          <Tabs label="Policy sections" active={tab} onChange={setTab} tabs={[{ id: 'cover', label: 'Cover & conditions' }, { id: 'assets', label: 'Insured assets' }, { id: 'versions', label: 'Versions' }, { id: 'wording', label: 'Wording' }]} />
          <Panel id="cover" active={tab}>
            <div className="card"><PolicySummary p={p} /></div>
            {cur && <TermsView t={cur.terms} />}
            <div className="card">
              <button className="secondary" onClick={() => void explain()} disabled={busy}>Explain this policy in plain language</button>
              {ai && <AiResult s={ai} />}
            </div>
          </Panel>
          <Panel id="assets" active={tab}>
            <Table caption="Insured assets" head={['Name', 'Category', 'Declared value', 'Added']} numCols={[2]}>
              {(p.assets ?? []).map(a => <tr key={a.id}><td>{a.name}</td><td>{a.category}</td><td className="num">{money(a.declared_value)}</td><td>{a.added_on ?? '-'}</td></tr>)}
            </Table>
          </Panel>
          <Panel id="versions" active={tab}>
            <p>Each change to an active policy creates a new version. A claim is always assessed against the version in force on the incident date.</p>
            <Table caption="Policy versions" head={['Version', 'Effective from', 'Plan', 'Reason', 'Assets']}>
              {(p.versions ?? []).map(v => <tr key={v.version}><td>v{v.version}</td><td>{v.effective_from}</td><td>{v.plan_name}</td><td>{v.reason}</td><td>{v.insured_asset_ids.length}</td></tr>)}
            </Table>
          </Panel>
          <Panel id="wording" active={tab}><pre className="card" style={{ whiteSpace: 'pre-wrap' }}>{p.wording || 'No wording available.'}</pre></Panel>
        </>
      );
    }}</Async>
  );
}
