import type { AISuggestion } from '../types';
import { Notice } from '../ui';

const list = (v: unknown): string[] => (Array.isArray(v) ? v.map(String) : []);

/** Renders any AI/demo suggestion with an unmistakable label. AI output is never presented as a decision. */
export default function AiResult({ s }: { s: AISuggestion }) {
  const c = s.content as Record<string, any>;
  return (
    <section className="card" aria-label={`${s.label}: ${s.kind}`}>
      <Notice kind={s.is_ai ? 'info' : 'warn'}><strong>{s.label}.</strong> {s.status_note}{s.is_ai ? ` Provider: ${s.provider} / ${s.model}.` : ''} Unverified: a person must check it.</Notice>
      {s.kind === 'explanation' && <><p style={{ whiteSpace: 'pre-wrap' }}>{String(c.explanation ?? '')}</p>{list(c.key_points).length > 0 && <ul>{list(c.key_points).map(p => <li key={p}>{p}</li>)}</ul>}</>}
      {s.kind === 'image_description' && (
        <dl className="kv">
          <dt>Visible damage</dt><dd>{String(c.visible_description ?? '')}</dd>
          <dt>Likely components</dt><dd>{list(c.likely_components).join(', ') || '-'}</dd>
          <dt>Suggested damage / severity</dt><dd>{String(c.suggested_damage_type)} / {String(c.suggested_severity)}</dd>
          <dt>Suggested action</dt><dd>{String(c.suggested_repair_action)}</dd>
          <dt>Confidence</dt><dd>{String(c.confidence)}</dd>
          <dt>Missing information</dt><dd>{list(c.missing_information).join('; ') || '-'}</dd>
        </dl>
      )}
      {s.kind === 'quotation' && (
        <>
          <table><caption className="sr-only">Extracted quotation lines (unverified)</caption><thead><tr><th scope="col">Description</th><th scope="col" className="num">Amount</th></tr></thead>
            <tbody>{(c.line_items ?? []).map((l: { description: string; amount: number | null }, i: number) => <tr key={i}><td>{l.description}</td><td className="num">{l.amount ?? '-'}</td></tr>)}</tbody></table>
          <p>Total stated on document: {c.total_stated ?? 'not found'}</p>
        </>
      )}
      {s.kind === 'assessment' && (c.suggested_items ?? []).length > 0 && <p>{(c.suggested_items as unknown[]).length} suggested item(s). Review them in the Damage items tab.</p>}
      {list(c.caveats).length > 0 && <p className="muted">Caveats: {list(c.caveats).join('; ')}</p>}
      {s.verify_notice && <p className="muted">{s.verify_notice}</p>}
    </section>
  );
}
