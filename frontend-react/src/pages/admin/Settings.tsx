import { Fragment, useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { api } from '../../api';
import { Async, Check, Field, Notice, useAction, useLoad, usePageTitle } from '../../ui';

interface Cfg { editable: { maintenance_banner: string; payments_enabled: string }; environment: Record<string, string | number | boolean>;
  ai: { provider: string; configured: boolean; text_model: string | null; vision_model: string | null; vision_available: boolean; message: string } }

export default function Settings() {
  usePageTitle('System');
  const cfg = useLoad(() => api<Cfg>('/system/settings'), []);
  const { run, busy } = useAction();
  const [banner, setBanner] = useState('');
  const [pay, setPay] = useState(true);
  const [aiMsg, setAiMsg] = useState('');
  useEffect(() => { if (cfg.data) { setBanner(cfg.data.editable.maintenance_banner); setPay(cfg.data.editable.payments_enabled === 'true'); } }, [cfg.data]);
  const save = async (e: FormEvent) => { e.preventDefault(); if (await run(() => api('/system/settings', { method: 'PUT', body: { maintenance_banner: banner, payments_enabled: pay } }), 'Settings saved')) cfg.reload(); };
  const test = () => run(async () => { const r = await api<{ ok: boolean; message?: string; detail?: string }>('/ai/test-connection', { method: 'POST' }); setAiMsg(`${r.ok ? 'OK' : 'Failed'}: ${r.message ?? r.detail ?? ''}`); });
  return (
    <>
      <h1>System configuration</h1>
      <Async state={cfg}>{c => (
        <>
          <form className="card" onSubmit={e => void save(e)} aria-label="Editable settings">
            <h2 style={{ marginTop: 0 }}>Settings</h2>
            <Field label="Maintenance banner (shown to every user)" value={banner} maxLength={300} onChange={e => setBanner(e.target.value)} />
            <Check label="Payment requests enabled" checked={pay} onChange={e => setPay(e.target.checked)} />
            <button type="submit" disabled={busy}>Save settings</button>
          </form>
          <section className="card" aria-labelledby="ai-h">
            <h2 id="ai-h" style={{ marginTop: 0 }}>AI provider</h2>
            <dl className="kv"><dt>Provider</dt><dd>{c.ai.provider}</dd><dt>Configured</dt><dd>{c.ai.configured ? 'Yes' : 'No (labelled demo fallback is used)'}</dd><dt>Text model</dt><dd>{c.ai.text_model ?? '-'}</dd>
              <dt>Vision model</dt><dd>{c.ai.vision_model ?? '-'}</dd><dt>Status</dt><dd>{c.ai.message}</dd></dl>
            <button className="secondary" disabled={busy} onClick={() => void test()}>Test AI connection</button>
            {aiMsg && <div role="status"><Notice>{aiMsg}</Notice></div>}
            <p className="hint">The API key is never sent to the browser. Configure it in the server environment (.env).</p>
          </section>
          <section className="card" aria-labelledby="env-h">
            <h2 id="env-h" style={{ marginTop: 0 }}>Environment (read-only)</h2>
            <dl className="kv">{Object.entries(c.environment).map(([k, v]) => <Fragment key={k}><dt>{k.replace(/_/g, ' ')}</dt><dd>{String(v)}</dd></Fragment>)}</dl>
          </section>
        </>
      )}</Async>
    </>
  );
}
