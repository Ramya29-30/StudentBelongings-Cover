import { useState } from 'react';
import { AlertTriangle, CheckCircle2, CircleHelp, ImageOff, ShieldAlert } from 'lucide-react';
import type { ClaimV3, Decision, DeviceMatch, Report } from '../types3';
import { Badge, Notice, Table, dt, money } from '../ui';

const pct = (c: number | null | undefined) => (c == null ? 'not available' : `${Math.round(c * 100)}%`);

export function OutcomeBadge({ text }: { text: string }) {
  const ok = text === 'Evidence Supported' || text === 'Evidence appears consistent';
  const bad = text.startsWith('Evidence Inconsistent') || text.startsWith('Suspicious evidence');
  const Icon = ok ? CheckCircle2 : bad ? ShieldAlert : CircleHelp;
  return <span className={`badge ${ok ? 'ok' : bad ? 'bad' : 'warn'}`}><Icon size={14} aria-hidden="true" /> {text}</span>;
}

export function ImageWithBoxes({ src, alt, boxes }: { src: string; alt: string; boxes: { box: number[]; label: string }[] }) {
  return (
    <figure className="shot">
      <div className="shot-frame">
        <img src={src} alt={alt} loading="lazy" />
        {boxes.map((b, i) => (
          <div key={i} className="box" style={{ left: `${b.box[0] * 100}%`, top: `${b.box[1] * 100}%`, width: `${(b.box[2] - b.box[0]) * 100}%`, height: `${(b.box[3] - b.box[1]) * 100}%` }}><span>{b.label}</span></div>
        ))}
      </div>
    </figure>
  );
}

export function SimulationBanner({ report }: { report: Report }) {
  if (!report.is_simulated) return null;
  return <Notice kind="warn"><strong>Development simulation.</strong> No model analysed these photos. Asset and damage were assumed from the claim form so the workflow can be demonstrated. Image quality, duplicate and metadata checks are real. This mode is not available in production.</Notice>;
}

function VerificationSummary({ r }: { r: Report }) {
  const m = r.summary;
  if (!m) return null;
  const f = m.authenticity_flags;
  return (
    <div>
      <h3>Verification summary</h3>
      <dl className="kv">
        <dt>Expected device present</dt><dd>{m.expected_device_present.status ?? 'Not run'}</dd>
        <dt>Visible damage detected</dt><dd>{m.visible_damage.types.length ? `${m.visible_damage.types.join(', ')}${m.visible_damage.top_confidence != null ? ` (${pct(m.visible_damage.top_confidence)})` : ''}` : m.visible_damage.status}</dd>
        <dt>Description matches the image</dt><dd>{m.description_matches}</dd>
        <dt>Registered device comparison</dt><dd>{m.registered_device_match.band ?? 'Not run'}{m.registered_device_match.used_for_routing === false ? ' (shown for information, not used in the decision)' : ''}</dd>
        <dt>Authenticity flags</dt><dd>{f.high} high, {f.medium} medium, {f.low} low</dd>
      </dl>
      <p className="hint">{m.note}</p>
    </div>
  );
}

const CHECK_BADGE: Record<string, string> = { Matches: 'Accepted', Differs: 'Suspicious evidence - manual review', 'Not checked': 'Pending', 'Not legible': 'Pending' };

function DeviceMatchPanel({ d }: { d: DeviceMatch }) {
  return (
    <div>
      <h3>Comparison with the registered photographs</h3>
      <p><Badge text={d.band} /> {d.best_score != null ? `Score ${d.best_score.toFixed(2)} out of 1.` : ''}</p>
      <p>{d.conclusion}</p>
      {d.supporting_evidence.length > 0 && <ul>{d.supporting_evidence.map(x => <li key={x}>{x}</li>)}</ul>}
      <dl className="kv">
        {d.serial_check && <><dt>Serial or IMEI visible in the photos</dt><dd><Badge text={CHECK_BADGE[d.serial_check.status] ?? d.serial_check.status} /> {d.serial_check.status}. {d.serial_check.detail}</dd></>}
        {d.brand_model_check && <><dt>Brand and model text</dt><dd><Badge text={CHECK_BADGE[d.brand_model_check.status] ?? d.brand_model_check.status} /> {d.brand_model_check.status}. {d.brand_model_check.detail}</dd></>}
      </dl>
      <details>
        <summary>Method, thresholds and limits</summary>
        <p>{d.method}.</p>
        {d.thresholds && <p>Strong agreement from {d.thresholds.strong}, partial from {d.thresholds.partial}. {d.thresholds.note}</p>}
        {d.pairs.length > 0 && (
          <Table caption="Photo pairs compared" head={['Claim photo', 'Registered photo', 'Candidate matches', 'Consistent keypoints', 'Score']} numCols={[2, 3, 4]}>
            {d.pairs.slice(0, 6).map((p, i) => <tr key={i}><td>{p.claim_image}</td><td>{p.reference}</td><td className="num">{p.good_matches}</td><td className="num">{p.inliers}</td><td className="num">{p.score.toFixed(2)}</td></tr>)}
          </Table>)}
        <ul>{d.limitations.map(x => <li key={x}>{x}</li>)}</ul>
      </details>
    </div>
  );
}

function AuthenticityPanel({ r }: { r: Report }) {
  const a = r.authenticity;
  if (!a?.images?.length) return null;
  return (
    <details>
      <summary>Image authenticity checks</summary>
      <Table caption="Per photo authenticity checks" head={['Photo', 'Size', 'Camera data', 'Editing software', 'Error level check']}>
        {a.images.map(im => (
          <tr key={im.image}><td>{im.image}</td><td>{im.width} x {im.height} ({im.megapixels} MP)</td>
            <td>{im.exif.present ? (im.exif.camera ?? 'present') : 'None (normal for messaging apps and screenshots)'}</td>
            <td>{im.exif.editing_software ? (im.exif.software ?? 'yes') : 'Not named'}</td>
            <td>{im.ela.applicable ? (im.ela.uneven ? 'Uneven (weak signal)' : 'Even') : 'Not applicable'}</td></tr>))}
      </Table>
      {a.images.some(im => im.notes.length > 0) && <ul>{a.images.flatMap(im => im.notes.map(n => <li key={im.image + n}>{im.image}: {n}</li>))}</ul>}
      <p className="hint">{a.missing_exif_policy}</p>
      {a.limitations && <ul>{Object.entries(a.limitations).map(([k, v]) => <li key={k}>{v}</li>)}</ul>}
    </details>
  );
}

export function AiReport({ claim }: { claim: ClaimV3 }) {
  const r = claim.report;
  const [sel, setSel] = useState(0);
  if (!r) return <Notice>No verification report yet.</Notice>;
  const imgs = claim.images ?? [];
  const cur = imgs[Math.min(sel, imgs.length - 1)];
  const boxes = r.damage_detection.detections.filter(d => d.box).map(d => ({ box: d.box as number[], label: `${d.damage_type} ${pct(d.confidence)}` }));
  const dmg = r.damage_detection.detections;
  return (
    <section aria-labelledby="rep-h" className="card">
      <div className="row spread"><h2 id="rep-h" style={{ margin: 0 }}>AI damage verification report</h2><OutcomeBadge text={r.workflow_outcome || r.outcome} /></div>
      <p className="muted">Claim {claim.claim_number}. Run {r.run}. Analysed in {r.processing_ms} ms. Mode: <code>{r.mode}</code></p>
      <SimulationBanner report={r} />
      <div className="report-grid">
        <div>
          {cur ? <ImageWithBoxes src={`/api/v2/claims/${claim.id}/images/${cur.id}/file`} alt={`Uploaded photo ${cur.original_name}`} boxes={sel === 0 ? boxes : []} /> : <p className="muted"><ImageOff size={16} aria-hidden="true" /> No photo</p>}
          {imgs.length > 1 && <div className="row" role="group" aria-label="Choose photo">{imgs.map((im, i) => <button key={im.id} type="button" className={i === sel ? 'sm' : 'secondary sm'} aria-pressed={i === sel} onClick={() => setSel(i)}>Photo {i + 1}</button>)}</div>}
          {boxes.length > 0 && <p className="hint">Boxes show where the damage model found damage.</p>}
        </div>
        <dl className="kv">
          <dt>Asset</dt><dd>{claim.asset_category} ({claim.asset_name})</dd>
          <dt>Image quality</dt><dd>{r.quality.result} ({r.quality.average_score}/100, {r.quality.usable_count} of {r.quality.total_count} usable)</dd>
          <dt>Detected asset</dt><dd>{r.asset_identification.detected ?? 'Unable to verify'}{r.asset_identification.confidence != null ? ` (${pct(r.asset_identification.confidence)})` : ''}</dd>
          <dt>Asset match</dt><dd>{r.asset_identification.match}</dd>
          <dt>Detected damage</dt><dd>{dmg.length ? dmg.map(d => `${d.damage_type} (${pct(d.confidence)})`).join(', ') : r.damage_detection.status}</dd>
          <dt>Description match</dt><dd>{r.description_check.result}</dd>
          <dt>Duplicate image check</dt><dd>{r.duplicate_check.result}</dd>
          <dt>Evidence completeness</dt><dd>{r.evidence_completeness.complete ? 'Complete' : 'Incomplete'} ({r.evidence_completeness.photos_uploaded ?? 0} photos, {r.evidence_completeness.supporting_documents ?? 0} documents)</dd>
        </dl>
      </div>
      <VerificationSummary r={r} />
      <h3>Explanation</h3>
      <p>{r.explanation}</p>
      {r.device_match && r.device_match.band && <DeviceMatchPanel d={r.device_match} />}
      <AuthenticityPanel r={r} />
      <details>
        <summary>How each check was made</summary>
        <ul>
          <li>Image quality: {r.quality.images.map(q => `${q.image}: ${q.usable ? 'usable' : q.issues.join(', ')} (${q.score})`).join('; ') || 'none'}. OpenCV measurements, not machine learning.</li>
          <li>Asset: {r.asset_identification.method ?? 'not run'}. {r.asset_identification.explanation}</li>
          <li>Damage: {r.damage_detection.method ?? 'no method available'}. {r.damage_detection.explanation}</li>
          <li>Description: {r.description_check.method}. {r.description_check.notes.join(' ')}</li>
        </ul>
      </details>
      {r.risk_indicators.length > 0 && (
        <div><h3><AlertTriangle size={16} aria-hidden="true" /> Risk indicators</h3>
          <ul>{r.risk_indicators.map((x, i) => <li key={i}><Badge text={x.severity} /> {x.text}</li>)}</ul>
          <p className="hint">Indicators prompt a human review. They are not accusations and never reject a claim on their own.</p></div>
      )}
      <p><strong>Next step:</strong> {r.next_step}</p>
      <p className="hint">A model's confidence is a measure of the model's certainty, not proof that a claim is true or false. This report never approves or pays a claim: a person decides whenever the evidence is uncertain or conflicting.</p>
    </section>
  );
}

export function DecisionPanel({ d, claim }: { d: Decision | null | undefined; claim: ClaimV3 }) {
  if (!d) return null;
  const lines = d.calculation.lines ?? [];
  return (
    <section aria-labelledby="dec-h" className="card">
      <div className="row spread"><h2 id="dec-h" style={{ margin: 0 }}>Policy validation and decision</h2><Badge text={d.outcome} /></div>
      <p className="muted">Decided by {d.decided_by === 'staff' ? 'staff after exceptional review' : 'the automated policy rules'} on {dt(d.created_at)}. AI verification and the decision are separate steps.</p>
      <p>{d.reason}</p>
      {d.checks.length > 0 && (
        <Table caption="Policy checks" head={['Check', 'Result', 'Reason']}>
          {d.checks.map(c => <tr key={c.id + c.reason}><td>{c.id} {c.name}</td><td><Badge text={c.result === 'PASS' ? 'PASS' : c.result === 'FAIL' ? 'FAIL' : c.result} /></td><td>{c.reason}</td></tr>)}
        </Table>
      )}
      {lines.length > 0 && (
        <>
          <h3>How the amount was calculated</h3>
          <Table caption="Claim amount calculation" head={['Step', 'Amount', 'Note']} numCols={[1]}>
            {lines.map((l, i) => <tr key={i}><td>{l.label}</td><td className="num">{money(l.amount)}</td><td>{l.note}</td></tr>)}
          </Table>
          {d.calculation.basis && <p className="hint">Loss basis: {d.calculation.basis}. The amount is computed by the server from the policy terms frozen at purchase.</p>}
        </>
      )}
      {claim.settlement && <Notice kind="ok">Simulated settlement {claim.settlement.reference}: {money(claim.settlement.amount)} ({claim.settlement.status}). No real money moves in this prototype.</Notice>}
    </section>
  );
}
