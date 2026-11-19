import { useState } from 'react';
import type { FormEvent } from 'react';
import { api, evidenceUrl } from '../api';
import { useAuth } from '../auth';
import type { AISuggestion, Claim } from '../types';
import { Field, Notice, Select, Table, dt, useAction } from '../ui';
import AiResult from './AiResult';

const ALLOWED = '.jpg,.jpeg,.png,.webp,.gif,.pdf,.txt,.csv';

export default function EvidencePanel({ claim, canUpload, canAi, onChange }: { claim: Claim; canUpload: boolean; canAi: boolean; onChange: () => void }) {
  const { meta, user } = useAuth();
  const { run, busy } = useAction();
  const [fileKey, setFileKey] = useState(0);
  const [docType, setDocType] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [er, setEr] = useState<Record<string, string>>({});
  const [ai, setAi] = useState<AISuggestion | null>(null);
  const maxMb = 8;

  const upload = async (e: FormEvent) => {
    e.preventDefault();
    const x: Record<string, string> = {};
    if (!docType) x.doc = 'Choose the document type';
    if (!file) x.file = 'Choose a file to upload';
    else if (file.size > maxMb * 1024 * 1024) x.file = `File is larger than ${maxMb} MB`;
    else if (!ALLOWED.split(',').includes('.' + (file.name.split('.').pop() ?? '').toLowerCase())) x.file = `Allowed types: ${ALLOWED}`;
    setEr(x);
    if (Object.keys(x).length || !file) return;
    const fd = new FormData();
    fd.append('doc_type', docType); fd.append('file', file);
    if (await run(() => api(`/claims/${claim.id}/evidence`, { method: 'POST', form: fd }), 'Evidence uploaded')) { setFile(null); setDocType(''); setFileKey(k => k + 1); onChange(); }
  };
  const describe = (id: number) => run(async () => setAi(await api<AISuggestion>(`/ai/claims/${claim.id}/describe-image`, { method: 'POST', body: { evidence_id: id } })));
  const extract = (id: number) => run(async () => setAi(await api<AISuggestion>(`/ai/claims/${claim.id}/extract-quotation`, { method: 'POST', body: { evidence_id: id } })));
  const ev = claim.evidence ?? [];
  return (
    <>
      {ev.length === 0 ? <p>No evidence uploaded yet.</p> : (
        <Table caption="Uploaded evidence" head={['File', 'Type', 'Size', 'Uploaded', 'Actions']} numCols={[2]}>
          {ev.map(e => (
            <tr key={e.id}>
              <td>{e.original_name}</td><td>{e.doc_type}</td><td className="num">{Math.max(1, Math.round(e.size_bytes / 1024))} KB</td><td>{dt(e.uploaded_at)}</td>
              <td className="row">
                <a href={evidenceUrl(claim.id, e.id)} target="_blank" rel="noreferrer" aria-label={`Open ${e.original_name} in a new tab`}>Open</a>
                {canAi && e.content_type.startsWith('image/') && <button className="secondary sm" disabled={busy} onClick={() => void describe(e.id)} aria-label={`Describe damage in ${e.original_name} with AI`}>AI describe</button>}
                {canAi && ['repair_quote', 'proof_of_purchase', 'other'].includes(e.doc_type) && <button className="secondary sm" disabled={busy} onClick={() => void extract(e.id)} aria-label={`Extract quotation lines from ${e.original_name} with AI`}>AI extract quotation</button>}
              </td>
            </tr>
          ))}
        </Table>
      )}
      {ai && <AiResult s={ai} />}
      {canUpload ? (
        <form className="card" onSubmit={e => void upload(e)} noValidate aria-label="Upload evidence">
          <h3 style={{ marginTop: 0 }}>Upload evidence</h3>
          <Select label="Document type" value={docType} onChange={e => setDocType(e.target.value)} options={meta?.doc_types ?? []} placeholder="Select…" error={er.doc} required />
          <Field key={fileKey} label="File" type="file" accept={ALLOWED} onChange={e => setFile(e.target.files?.[0] ?? null)} error={er.file} hint={`Photos, PDF, TXT or CSV, up to ${maxMb} MB. The server checks file contents, not just the name.`} required />
          <button type="submit" disabled={busy}>Upload</button>
        </form>
      ) : user?.role === 'student' ? <Notice>Evidence can no longer be added at this stage.</Notice> : null}
    </>
  );
}
