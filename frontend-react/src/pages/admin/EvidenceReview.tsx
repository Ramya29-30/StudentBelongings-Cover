import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { api } from '../../api';
import type { AssetV3, EvidenceQueueRow, EvidenceSummary } from '../../types3';
import { Async, Badge, Check, Notice, Select, Table, TextArea, dt, money, useAction, useLoad, usePageTitle } from '../../ui';

const STATUSES = ['Pending review', 'More evidence requested', 'Approved', 'Rejected'];

export function EvidenceQueue() {
  usePageTitle('Evidence review');
  const [status, setStatus] = useState('');
  const q = useLoad(() => api<EvidenceQueueRow[]>('/v2/admin/evidence-reviews' + (status ? `?status=${encodeURIComponent(status)}` : '')), [status]);
  return (
    <>
      <h1>Registration evidence review</h1>
      <p className="muted">A student can buy a policy only after you approve the photographs and invoice of the registered item. Automatic observations are prompts for you, not findings.</p>
      <Select label="Show" value={status} onChange={e => setStatus(e.target.value)} options={[{ value: '', label: 'All registrations' }, ...STATUSES.map(s => ({ value: s, label: s }))]} />
      <Async state={q}>{rows => rows.length === 0 ? <Notice>No registrations match.</Notice> : (
        <Table caption="Registrations" head={['Item', 'Student', 'Declared value', 'Submitted', 'Status', 'Files', 'Observations', '']} numCols={[2, 5]}>
          {rows.map(r => (
            <tr key={r.id}>
              <td>{r.name} ({r.category})</td><td>{r.owner}</td><td className="num">{money(r.purchase_price)}</td><td>{dt(r.created_at)}</td>
              <td><Badge text={r.evidence_status} />{r.insured ? ' (insured)' : ''}</td>
              <td className="num">{r.files}{r.missing_required.length ? ` (missing: ${r.missing_required.join(', ')})` : ''}</td>
              <td>{r.flags.high} high, {r.flags.medium} medium, {r.flags.low} low</td>
              <td><Link to={`/admin/evidence/${r.id}`}>Review<span className="sr-only"> {r.name}</span></Link></td>
            </tr>))}
        </Table>)}</Async>
    </>
  );
}

interface Detail extends AssetV3 { owner_name: string; evidence: EvidenceSummary; review_history: { at: string; by: string; decision: string; from: string; to: string; note: string }[] }

export function EvidenceReviewDetail() {
  const { id } = useParams();
  usePageTitle('Review registration evidence');
  const d = useLoad(() => api<Detail>(`/v2/admin/assets/${id}/evidence-review`), [id]);
  const [decision, setDecision] = useState('approve');
  const [note, setNote] = useState('');
  const [missingOk, setMissingOk] = useState(false);
  const { run, busy } = useAction();
  const submit = async () => {
    const ok = await run(() => api(`/v2/admin/assets/${id}/evidence-review`, { method: 'POST', body: { decision, note, accept_missing_invoice: missingOk } }),
      decision === 'approve' ? 'Evidence approved. The student can now buy a policy.' : decision === 'reject' ? 'Registration rejected.' : 'More evidence requested.');
    if (ok) { setNote(''); setMissingOk(false); d.reload(); }
  };
  return (
    <>
      <p><Link to="/admin/evidence">Back to the queue</Link></p>
      <Async state={d}>{x => {
        const ev = x.evidence;
        const insured = !!x.policy;
        const needNote = decision !== 'approve' || (decision === 'approve' && !ev.has_invoice);
        return (
          <>
            <div className="row spread"><h1 style={{ margin: 0 }}>{x.name}</h1><Badge text={x.evidence_status} /></div>
            <section className="card">
              <dl className="kv">
                <dt>Student</dt><dd>{x.owner_name}</dd><dt>Category</dt><dd>{x.category}</dd><dt>Brand and model</dt><dd>{x.brand} {x.model_name}</dd>
                <dt>Serial, IMEI or frame no.</dt><dd className="mono">{x.serial_number || '-'}</dd>
                {ev.identifier_note && <><dt>Identifier note</dt><dd>{ev.identifier_note}</dd></>}
                <dt>Purchase date</dt><dd>{x.purchase_date}</dd><dt>Declared value</dt><dd>{money(x.purchase_price)} (declared by the student, not verified)</dd><dt>Description</dt><dd>{x.description || '-'}</dd>
              </dl>
            </section>
            <section className="card" aria-labelledby="files-h">
              <h2 id="files-h" style={{ marginTop: 0 }}>Evidence files</h2>
              {ev.missing_required.length > 0 && <Notice kind="warn">Required and missing: {ev.missing_required.join(', ')}. You cannot approve until the student adds them.</Notice>}
              {!ev.has_invoice && <Notice>No invoice or receipt was provided. You may still approve, with a written reason.</Notice>}
              <div className="grid cols">
                {ev.files.map(f => (
                  <article className="card" key={f.id} aria-label={f.label}>
                    <h3 style={{ marginTop: 0 }}>{f.label}</h3>
                    {f.is_image ? <a href={f.file_url} target="_blank" rel="noreferrer"><img className="thumb" src={f.file_url} alt={`${f.label}: ${f.original_name}`} loading="lazy" /></a>
                      : <p><a href={f.file_url} target="_blank" rel="noreferrer">Open {f.original_name}</a></p>}
                    <dl className="kv"><dt>File</dt><dd>{f.original_name}</dd><dt>Status</dt><dd><Badge text={f.review_status} /></dd>
                      {f.is_image && <><dt>Size</dt><dd>{f.width} x {f.height} pixels</dd></>}
                      {f.exif && Object.keys(f.exif).length > 0 && <><dt>Camera data</dt><dd>{[f.exif.Make, f.exif.Model, f.exif.Software, f.exif.DateTimeOriginal].filter(Boolean).join(', ') || 'present'}</dd></>}
                      {f.sha256 && <><dt>SHA-256</dt><dd className="mono">{f.sha256.slice(0, 16)}</dd></>}</dl>
                    {(f.flags ?? []).length > 0 ? <ul>{(f.flags ?? []).map((fl, i) => <li key={i}><Badge text={fl.severity} /> {fl.text}</li>)}</ul> : <p className="hint">No automatic observations.</p>}
                  </article>))}
              </div>
              <p className="hint">Observations are generated automatically (image quality, duplicates, metadata). Missing camera data is normal and is not listed as a concern.</p>
            </section>
            <section className="card" aria-labelledby="dec-h">
              <h2 id="dec-h" style={{ marginTop: 0 }}>Your decision</h2>
              {insured ? <Notice>This asset already has an active policy, so its evidence can no longer be re-reviewed.</Notice> : (
                <>
                  {x.evidence_status !== 'Pending review' && <Notice>Current status: {x.evidence_status}.{ev.note ? ` Note: ${ev.note}` : ''} You can change the decision until a policy is bought.</Notice>}
                  <Select label="Decision" value={decision} onChange={e => setDecision(e.target.value)}
                    options={[{ value: 'approve', label: 'Approve: the student may buy a policy' }, { value: 'request_more', label: 'Request more evidence' }, { value: 'reject', label: 'Reject the registration' }]} />
                  {decision === 'approve' && !ev.has_invoice && <Check label="Approve without an invoice or receipt (explain why in the note)" checked={missingOk} onChange={e => setMissingOk(e.target.checked)} />}
                  <TextArea label={needNote ? 'Note (shown to the student, required)' : 'Note (shown to the student, optional)'} maxLength={500} value={note} onChange={e => setNote(e.target.value)} />
                  <button type="button" disabled={busy || (needNote && note.trim().length < 5) || (decision === 'approve' && !ev.has_invoice && !missingOk)} onClick={() => void submit()}>{busy ? 'Saving...' : 'Save decision'}</button>
                </>)}
            </section>
            {x.review_history.length > 0 && (
              <Table caption="Review history" head={['When', 'By', 'Decision', 'Change', 'Note']}>
                {x.review_history.map((h, i) => <tr key={i}><td>{dt(h.at)}</td><td>{h.by}</td><td>{h.decision}</td><td>{h.from} to {h.to}</td><td>{h.note || '-'}</td></tr>)}
              </Table>)}
          </>);
      }}</Async>
    </>
  );
}
