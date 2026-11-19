import { createContext, useCallback, useContext, useEffect, useId, useRef, useState } from 'react';
import type { InputHTMLAttributes, ReactNode, SelectHTMLAttributes, TextareaHTMLAttributes } from 'react';
import { errMsg } from './api';

/* ---------- formatting ---------- */
export const money = (n: number | null | undefined) => (n == null ? '-' : (Number(n) < 0 ? '-' : '') + '\u20B9' + Math.abs(Number(n)).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
export const dt = (s: string | null | undefined) => (s ? new Date(s.endsWith('Z') || s.includes('+') ? s : s + 'Z').toLocaleString('en-IN') : '-');
export const today = () => new Date().toISOString().slice(0, 10);

const OK = ['Active', 'Approved for Review', 'Assessment Completed', 'Human Verified', 'PASS', 'Paid', 'Approved', 'Closed', 'Evidence appears consistent', 'Accepted', 'Strong feature agreement'];
const BAD = ['Cancelled', 'Rejected with Reason', 'FAIL', 'Rejected', 'Failed', 'Expired'];
const WARN = ['Pending Information', 'FLAG', 'Human Corrected', 'AI Suggested', 'Requested', 'Under Assessment', 'Submitted', 'Pending review', 'More evidence requested', 'More evidence required',
  'Suspicious evidence - manual review', 'Unable to verify - manual review', 'Pending', 'Partial feature agreement', 'Weak or no feature agreement'];
export function Badge({ text }: { text: string }) {
  const cls = OK.includes(text) ? 'ok' : BAD.includes(text) ? 'bad' : WARN.includes(text) ? 'warn' : '';
  return <span className={`badge ${cls}`}>{text}</span>;
}

/* ---------- async loading ---------- */
export function useLoad<T>(fn: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let live = true;
    setLoading(true);
    fn().then(d => { if (live) { setData(d); setError(''); } }).catch(e => { if (live) setError(errMsg(e)); }).finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);
  return { data, error, loading, reload: useCallback(() => setTick(t => t + 1), []) };
}
export function Loading({ label = 'Loading' }: { label?: string }) { return <p role="status" aria-live="polite" className="muted">{label}…</p>; }
export function ErrorBox({ message }: { message: string }) { return message ? <div className="alert error" role="alert">{message}</div> : null; }
export function Async<T>({ state, children }: { state: { data: T | null; error: string; loading: boolean }; children: (d: T) => ReactNode }) {
  if (state.error) return <ErrorBox message={state.error} />;
  if (state.loading && !state.data) return <Loading />;
  return state.data ? <>{children(state.data)}</> : null;
}

/* ---------- toasts ---------- */
interface ToastCtx { ok: (m: string) => void; err: (m: string) => void }
const Toasts = createContext<ToastCtx>({ ok: () => undefined, err: () => undefined });
export const useToast = () => useContext(Toasts);
export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<{ id: number; m: string; e: boolean }[]>([]);
  const n = useRef(0);
  const push = useCallback((m: string, e: boolean) => {
    const id = ++n.current;
    setItems(x => [...x, { id, m, e }]);
    setTimeout(() => setItems(x => x.filter(i => i.id !== id)), e ? 8000 : 4000);
  }, []);
  return (
    <Toasts.Provider value={{ ok: m => push(m, false), err: m => push(m, true) }}>
      {children}
      <div className="toasts" aria-live="polite" aria-atomic="false">
        {items.map(i => <div key={i.id} className={`alert ${i.e ? 'error' : 'ok'}`} role={i.e ? 'alert' : 'status'}>{i.m}</div>)}
      </div>
    </Toasts.Provider>
  );
}
/** Run an action, toast the outcome, return whether it succeeded. */
export function useAction() {
  const t = useToast();
  const [busy, setBusy] = useState(false);
  const run = useCallback(async (fn: () => Promise<unknown>, okMsg?: string) => {
    setBusy(true);
    try { await fn(); if (okMsg) t.ok(okMsg); return true; } catch (e) { t.err(errMsg(e)); return false; } finally { setBusy(false); }
  }, [t]);
  return { run, busy };
}

/* ---------- form controls (label always programmatically associated) ---------- */
interface FieldProps { label: string; hint?: string; error?: string }
export function Field({ label, hint, error, ...p }: FieldProps & InputHTMLAttributes<HTMLInputElement>) {
  const id = useId();
  return (
    <div className="field">
      <label htmlFor={id}>{label}{p.required ? <span aria-hidden="true"> *</span> : null}</label>
      <input id={id} {...p} aria-invalid={error ? true : undefined} aria-describedby={[hint ? id + 'h' : '', error ? id + 'e' : ''].join(' ').trim() || undefined} />
      {hint && <div className="hint" id={id + 'h'}>{hint}</div>}
      {error && <div className="field-error" id={id + 'e'} role="alert">{error}</div>}
    </div>
  );
}
export function TextArea({ label, hint, error, ...p }: FieldProps & TextareaHTMLAttributes<HTMLTextAreaElement>) {
  const id = useId();
  return (
    <div className="field">
      <label htmlFor={id}>{label}{p.required ? <span aria-hidden="true"> *</span> : null}</label>
      <textarea id={id} {...p} aria-invalid={error ? true : undefined} aria-describedby={[hint ? id + 'h' : '', error ? id + 'e' : ''].join(' ').trim() || undefined} />
      {hint && <div className="hint" id={id + 'h'}>{hint}</div>}
      {error && <div className="field-error" id={id + 'e'} role="alert">{error}</div>}
    </div>
  );
}
export function Select({ label, hint, error, options, placeholder, ...p }: FieldProps & SelectHTMLAttributes<HTMLSelectElement> & { options: (string | { value: string | number; label: string })[]; placeholder?: string }) {
  const id = useId();
  return (
    <div className="field">
      <label htmlFor={id}>{label}{p.required ? <span aria-hidden="true"> *</span> : null}</label>
      <select id={id} {...p} aria-invalid={error ? true : undefined} aria-describedby={[hint ? id + 'h' : '', error ? id + 'e' : ''].join(' ').trim() || undefined}>
        {placeholder !== undefined && <option value="">{placeholder}</option>}
        {options.map(o => typeof o === 'string' ? <option key={o} value={o}>{o}</option> : <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
      {hint && <div className="hint" id={id + 'h'}>{hint}</div>}
      {error && <div className="field-error" id={id + 'e'} role="alert">{error}</div>}
    </div>
  );
}
export function Check({ label, ...p }: { label: string } & InputHTMLAttributes<HTMLInputElement>) {
  const id = useId();
  return <div className="field row"><input id={id} type="checkbox" {...p} /><label htmlFor={id} style={{ margin: 0, fontWeight: 400 }}>{label}</label></div>;
}

/* ---------- tabs (roving tabindex, arrow keys) ---------- */
export function Tabs({ tabs, active, onChange, label }: { tabs: { id: string; label: string }[]; active: string; onChange: (id: string) => void; label: string }) {
  const onKey = (e: React.KeyboardEvent, i: number) => {
    const d = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : 0;
    if (!d) return;
    e.preventDefault();
    const nx = tabs[(i + d + tabs.length) % tabs.length].id;
    onChange(nx);
    setTimeout(() => document.getElementById('tab-' + nx)?.focus(), 0);
  };
  return (
    <div className="tabs" role="tablist" aria-label={label}>
      {tabs.map((t, i) => (
        <button key={t.id} id={'tab-' + t.id} role="tab" aria-selected={active === t.id} aria-controls={'panel-' + t.id} tabIndex={active === t.id ? 0 : -1}
          onClick={() => onChange(t.id)} onKeyDown={e => onKey(e, i)}>{t.label}</button>
      ))}
    </div>
  );
}
export const Panel = ({ id, active, children }: { id: string; active: string; children: ReactNode }) =>
  active === id ? <div role="tabpanel" id={'panel-' + id} aria-labelledby={'tab-' + id}>{children}</div> : null;

/* ---------- modal built on native <dialog> (focus trap + Esc handled by the browser) ---------- */
export function Modal({ title, open, onClose, children }: { title: string; open: boolean; onClose: () => void; children: ReactNode }) {
  const ref = useRef<HTMLDialogElement>(null);
  const id = useId();
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal();
    if (!open && d.open) d.close();
  }, [open]);
  return (
    <dialog ref={ref} aria-labelledby={id} onClose={onClose}>
      <h2 id={id} style={{ marginTop: 0 }}>{title}</h2>
      {open && children}
    </dialog>
  );
}

/* ---------- small helpers ---------- */
export function Table({ caption, head, children, numCols = [] }: { caption: string; head: string[]; children: ReactNode; numCols?: number[] }) {
  return (
    <div className="table-wrap" tabIndex={0} role="region" aria-label={caption}>
      <table>
        <caption className="sr-only">{caption}</caption>
        <thead><tr>{head.map((h, i) => <th scope="col" key={h + i} className={numCols.includes(i) ? 'num' : ''}>{h}</th>)}</tr></thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );
}
export const Stat = ({ label, value }: { label: string; value: ReactNode }) => <div className="card"><div className="muted">{label}</div><div className="stat">{value}</div></div>;
export const Notice = ({ kind = 'info', children }: { kind?: 'info' | 'warn' | 'ok' | 'error'; children: ReactNode }) => <div className={`alert ${kind}`} role={kind === 'error' ? 'alert' : undefined}>{children}</div>;
export const num = (v: string): number | null => (v.trim() === '' ? null : Number(v));
export const usePageTitle = (t: string) => { useEffect(() => { document.title = `${t} - StudentBelongings Cover`; }, [t]); };
