import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { api } from '../api';
import { useAuth } from '../auth';
import type { AISuggestion, CatalogueEntry, Claim, ClaimItem } from '../types';
import { Badge, Check, Field, Modal, Notice, Select, Table, TextArea, money, num, useAction, useLoad } from '../ui';
import AiResult from './AiResult';

const blank = { component: '', damage_type: '', severity: 'Moderate', repair_action: 'Inspect Further', parts_cost: '', labour_cost: '', catalogue_entry_id: '', confidence: 'Unknown', notes: '', decision_reason: '', evidence_refs: [] as number[] };
type Form = typeof blank;

/** Student view: declare damage (unpriced), remove own unverified lines. Assessor view: full item assessment. */
export default function ItemsPanel({ claim, role, onChange }: { claim: Claim; role: 'student' | 'assessor' | 'admin'; onChange: () => void }) {
  const items = claim.items ?? [];
  const open = ['Draft', 'Pending Information'].includes(claim.status);
  const assessing = ['Submitted', 'Under Assessment', 'Pending Information', 'Assessment Completed'].includes(claim.status);
  return (
    <>
      {role === 'student' && <Notice>You can describe the damage here. Repair prices and the final assessment are always entered and verified by an assessor.</Notice>}
      <ItemTable claim={claim} items={items} role={role} editable={role === 'assessor' && assessing} studentRemovable={role === 'student' && open} onChange={onChange} />
      {role === 'student' && open && <StudentItemForm claim={claim} onChange={onChange} />}
      {role === 'assessor' && assessing && <AssessorTools claim={claim} onChange={onChange} />}
    </>
  );
}

function ItemTable({ claim, items, role, editable, studentRemovable, onChange }: { claim: Claim; items: ClaimItem[]; role: string; editable: boolean; studentRemovable: boolean; onChange: () => void }) {
  const { run, busy } = useAction();
  const [edit, setEdit] = useState<ClaimItem | null>(null);
  const showPrice = role !== 'student';
  if (items.length === 0) return <p>No damage items recorded yet.</p>;
  return (
    <>
      <Table caption="Damage items" head={['Component', 'Damage', 'Severity', 'Action', ...(showPrice ? ['Parts', 'Labour'] : []), 'Verification', 'Notes', ...(editable || studentRemovable ? ['Actions'] : [])]} numCols={showPrice ? [4, 5] : []}>
        {items.map(i => (
          <tr key={i.id}>
            <td>{i.component}</td><td>{i.damage_type}</td><td>{i.severity}</td><td>{i.repair_action}</td>
            {showPrice && <><td className="num">{money(i.parts_cost)}</td><td className="num">{money(i.labour_cost)}</td></>}
            <td><Badge text={i.verification_status} /></td><td>{i.notes}</td>
            {(editable || studentRemovable) && (
              <td className="row">
                {editable && <><button className="sm secondary" onClick={() => setEdit(i)} aria-label={`Edit ${i.component}`}>Edit / correct</button>
                  {i.verification_status !== 'Human Verified' && i.verification_status !== 'Human Corrected' && <button className="sm" disabled={busy} onClick={() => void run(() => api(`/items/${i.id}/verify`, { method: 'POST' }), 'Item verified').then(ok => ok && onChange())} aria-label={`Verify ${i.component}`}>Verify</button>}
                  <button className="sm danger" disabled={busy} onClick={() => { if (confirm(`Delete damage item "${i.component}"?`)) void run(() => api(`/items/${i.id}`, { method: 'DELETE' }), 'Item deleted').then(ok => ok && onChange()); }} aria-label={`Delete ${i.component}`}>Delete</button></>}
                {studentRemovable && i.verification_status === 'Student Declared' && <button className="sm danger" disabled={busy} onClick={() => void run(() => api(`/claims/${claim.id}/student-items/${i.id}`, { method: 'DELETE' }), 'Item removed').then(ok => ok && onChange())} aria-label={`Remove ${i.component}`}>Remove</button>}
              </td>
            )}
          </tr>
        ))}
      </Table>
      {edit && <ItemModal claim={claim} item={edit} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); onChange(); }} />}
    </>
  );
}

function StudentItemForm({ claim, onChange }: { claim: Claim; onChange: () => void }) {
  const { meta } = useAuth();
  const { run, busy } = useAction();
  const [f, setF] = useState({ component: '', damage_type: '', severity: 'Moderate', notes: '' });
  const [er, setEr] = useState<Record<string, string>>({});
  const set = (k: string) => (e: { target: { value: string } }) => setF(x => ({ ...x, [k]: e.target.value }));
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const x: Record<string, string> = {};
    if (!f.component.trim()) x.component = 'Name the damaged part, e.g. Screen';
    if (!f.damage_type) x.damage_type = 'Choose the type of damage';
    setEr(x);
    if (Object.keys(x).length) return;
    if (await run(() => api(`/claims/${claim.id}/student-items`, { method: 'POST', body: f }), 'Damage item added')) { setF({ component: '', damage_type: '', severity: 'Moderate', notes: '' }); onChange(); }
  };
  return (
    <form className="card" onSubmit={e => void submit(e)} noValidate aria-label="Add damage item">
      <h3 style={{ marginTop: 0 }}>Add a damage item</h3>
      <div className="grid cols">
        <Field label="Damaged part" value={f.component} onChange={set('component')} error={er.component} maxLength={80} required />
        <Select label="Type of damage" value={f.damage_type} onChange={set('damage_type')} options={meta?.damage_types ?? []} placeholder="Select…" error={er.damage_type} required />
        <Select label="Severity" value={f.severity} onChange={set('severity')} options={meta?.severities ?? []} />
      </div>
      <TextArea label="Notes" value={f.notes} onChange={set('notes')} maxLength={1000} />
      <button type="submit" disabled={busy}>Add item</button>
    </form>
  );
}

function ItemModal({ claim, item, onClose, onSaved }: { claim: Claim; item: ClaimItem | null; onClose: () => void; onSaved: () => void }) {
  const { meta } = useAuth();
  const { run, busy } = useAction();
  const cat = useLoad(() => api<CatalogueEntry[]>(`/catalogue?category=${encodeURIComponent(claim.asset_category)}`), [claim.asset_category]);
  const [f, setF] = useState<Form>(blank);
  const [er, setEr] = useState<Record<string, string>>({});
  useEffect(() => {
    setF(item ? { component: item.component, damage_type: item.damage_type, severity: item.severity, repair_action: item.repair_action, parts_cost: item.parts_cost == null ? '' : String(item.parts_cost),
      labour_cost: item.labour_cost == null ? '' : String(item.labour_cost), catalogue_entry_id: item.catalogue_entry_id ? String(item.catalogue_entry_id) : '', confidence: item.confidence, notes: item.notes,
      decision_reason: item.decision_reason, evidence_refs: item.evidence_refs } : blank);
  }, [item]);
  const set = (k: keyof Form) => (e: { target: { value: string } }) => setF(x => ({ ...x, [k]: e.target.value }));
  const save = async (e: FormEvent) => {
    e.preventDefault();
    const x: Record<string, string> = {};
    if (!f.component.trim()) x.component = 'Enter the component';
    if (!f.damage_type) x.damage_type = 'Choose the damage type';
    for (const k of ['parts_cost', 'labour_cost'] as const) if (f[k] !== '' && !(Number(f[k]) >= 0)) x[k] = 'Enter 0 or more';
    if (item && item.ai_suggestion_id && !f.decision_reason.trim()) x.decision_reason = 'Record why you accept or change the AI suggestion';
    setEr(x);
    if (Object.keys(x).length) return;
    const body = { ...f, parts_cost: num(f.parts_cost), labour_cost: num(f.labour_cost), catalogue_entry_id: f.catalogue_entry_id ? Number(f.catalogue_entry_id) : null, ai_suggestion_id: item?.ai_suggestion_id ?? null };
    const ok = await run(() => item ? api(`/items/${item.id}`, { method: 'PUT', body }) : api(`/claims/${claim.id}/items`, { method: 'POST', body }), item ? 'Item saved and marked human-verified' : 'Item added');
    if (ok) onSaved();
  };
  const toggleEv = (id: number) => setF(x => ({ ...x, evidence_refs: x.evidence_refs.includes(id) ? x.evidence_refs.filter(i => i !== id) : [...x.evidence_refs, id] }));
  return (
    <Modal title={item ? `Edit damage item: ${item.component}` : 'Add damage item'} open onClose={onClose}>
      <form onSubmit={e => void save(e)} noValidate aria-label="Damage item">
        <Field label="Component" value={f.component} onChange={set('component')} error={er.component} maxLength={80} required />
        <Select label="Damage type" value={f.damage_type} onChange={set('damage_type')} options={meta?.damage_types ?? []} placeholder="Select…" error={er.damage_type} required />
        <Select label="Severity" value={f.severity} onChange={set('severity')} options={meta?.severities ?? []} />
        <Select label="Repair action" value={f.repair_action} onChange={set('repair_action')} options={meta?.repair_actions ?? []} />
        <Select label="Catalogue price (optional)" value={f.catalogue_entry_id} onChange={set('catalogue_entry_id')} placeholder="None - enter prices manually"
          options={(cat.data ?? []).filter(c => c.active).map(c => ({ value: c.id, label: `${c.component} / ${c.action} (${money(c.parts_cost + c.labour_cost)})` }))} hint="Leave parts and labour blank to use the catalogue price." />
        <div className="grid cols"><Field label="Parts cost (INR)" type="number" min="0" step="0.01" value={f.parts_cost} onChange={set('parts_cost')} error={er.parts_cost} />
          <Field label="Labour cost (INR)" type="number" min="0" step="0.01" value={f.labour_cost} onChange={set('labour_cost')} error={er.labour_cost} /></div>
        <Select label="Confidence" value={f.confidence} onChange={set('confidence')} options={meta?.confidence ?? []} />
        {(claim.evidence ?? []).length > 0 && <fieldset><legend>Supporting evidence</legend>{(claim.evidence ?? []).map(ev => <Check key={ev.id} label={`${ev.original_name} (${ev.doc_type})`} checked={f.evidence_refs.includes(ev.id)} onChange={() => toggleEv(ev.id)} />)}</fieldset>}
        <TextArea label="Notes" value={f.notes} onChange={set('notes')} />
        <TextArea label="Decision reason" value={f.decision_reason} onChange={set('decision_reason')} error={er.decision_reason} />
        <div className="row"><button type="submit" disabled={busy}>Save</button><button type="button" className="secondary" onClick={onClose}>Cancel</button></div>
      </form>
    </Modal>
  );
}

function AssessorTools({ claim, onChange }: { claim: Claim; onChange: () => void }) {
  const { run, busy } = useAction();
  const [adding, setAdding] = useState(false);
  const [ai, setAi] = useState<AISuggestion | null>(null);
  const suggest = () => run(async () => setAi(await api<AISuggestion>(`/ai/claims/${claim.id}/suggest-assessment`, { method: 'POST', body: {} })));
  const accept = (idx: number) => run(() => api(`/ai/suggestions/${ai!.id}/accept-item?index=${idx}`, { method: 'POST' }), 'Added as "AI Suggested". Verify or correct it before completing the assessment.').then(ok => ok && onChange());
  const sug = (ai?.content.suggested_items ?? []) as { component: string; damage_type: string; severity: string; repair_action: string; confidence: string; rationale?: string }[];
  return (
    <>
      <div className="row"><button onClick={() => setAdding(true)}>Add damage item</button><button className="secondary" disabled={busy} onClick={() => void suggest()}>Get AI assessment suggestions</button></div>
      {adding && <ItemModal claim={claim} item={null} onClose={() => setAdding(false)} onSaved={() => { setAdding(false); onChange(); }} />}
      {ai && <><AiResult s={ai} />
        {sug.length > 0 && <Table caption="AI suggested items (unverified)" head={['Component', 'Damage', 'Severity', 'Action', 'Confidence', 'Rationale', '']}>
          {sug.map((s, i) => <tr key={i}><td>{s.component}</td><td>{s.damage_type}</td><td>{s.severity}</td><td>{s.repair_action}</td><td>{s.confidence}</td><td>{s.rationale}</td>
            <td><button className="sm secondary" disabled={busy || ai.accepted} onClick={() => void accept(i)} aria-label={`Add suggested item ${s.component} for verification`}>Add for verification</button></td></tr>)}
        </Table>}</>}
    </>
  );
}
