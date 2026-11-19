import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api';
import { useAuth } from '../auth';
import { Async, Notice, Table, useLoad, usePageTitle } from '../ui';

interface LegalConfig {
  operator_name: string; contact_email: string; postal_address: string; governing_law: string;
  reviewed_by_counsel: boolean; ai_enabled: boolean; ai_provider: string; payments: string;
}
const UPDATED = '1 November 2026';

/** A value only the operator can supply. Missing values are shown as missing, never invented. */
const Fact = ({ v, what }: { v: string; what: string }) => (v ? <>{v}</> : <strong className="missing">[{what}: not yet provided by the operator]</strong>);

function missingFacts(c: LegalConfig): string[] {
  const m: string[] = [];
  if (!c.operator_name) m.push('operator name');
  if (!c.contact_email) m.push('contact email');
  if (!c.postal_address) m.push('postal address');
  if (!c.governing_law) m.push('governing law and jurisdiction');
  return m;
}

function Status({ c }: { c: LegalConfig }) {
  const m = missingFacts(c);
  return (
    <>
      {!c.reviewed_by_counsel && <Notice kind="warn"><strong>Draft, not legal advice.</strong> This document has not been reviewed by a lawyer. It describes how the software works, and it must be reviewed and adopted by the operator before this service is used with real people.</Notice>}
      {m.length > 0 && <Notice kind="warn"><strong>Incomplete.</strong> The operator has not yet provided: {m.join(', ')}. These are shown below as missing and must be set in the server configuration (LEGAL_* settings).</Notice>}
    </>
  );
}

function Shell({ title, children }: { title: string; children: (c: LegalConfig) => ReactNode }) {
  usePageTitle(title);
  const { user } = useAuth();
  const cfg = useLoad(() => api<LegalConfig>('/legal-config'), []);
  return (
    <>
      <a className="skip" href="#main">Skip to main content</a>
      <header className="top">
        <div><strong>StudentBelongings Cover</strong></div>
        <div className="row"><Link className="btn secondary" to={user ? `/${user.role}` : '/login'}>{user ? 'Back to the application' : 'Sign in'}</Link></div>
      </header>
      <main id="main" className="legal">
        <h1>{title}</h1>
        <p className="muted">Last updated {UPDATED}</p>
        <Async state={cfg}>{c => <><Status c={c} />{children(c)}</>}</Async>
      </main>
      <SiteFooter />
    </>
  );
}

export function SiteFooter() {
  return (
    <footer className="site">
      <nav aria-label="Legal">
        <ul className="row">
          <li><Link to="/privacy">Privacy Policy</Link></li>
          <li><Link to="/terms">Terms and Conditions</Link></li>
        </ul>
      </nav>
      <small>StudentBelongings Cover is an academic prototype. It is not an insurer and does not issue real insurance. Payments are simulated.</small>
    </footer>
  );
}

export function Privacy() {
  return (
    <Shell title="Privacy Policy">{c => (
      <>
        <h2>1. Who is responsible</h2>
        <p>The operator of this service decides why and how personal information is processed. Operator: <Fact v={c.operator_name} what="operator name" />. Postal address: <Fact v={c.postal_address} what="postal address" />. Contact: <Fact v={c.contact_email} what="contact email" />.</p>

        <h2>2. What this service is</h2>
        <p>StudentBelongings Cover is software for recording students' personal belongings, sample cover plans, and claims for loss or damage. It is an academic prototype. It is not an insurance company, and no real insurance policy is issued through it. Payments shown in the service are simulated and no money moves.</p>

        <h2>3. Information we process</h2>
        <Table caption="Personal information processed" head={['Category', 'What it includes', 'Where it comes from']}>
          <tr><td>Account</td><td>Username, full name, optional email address, role (student, assessor or administrator), a salted password hash (the password itself is never stored), account creation and last sign-in time</td><td>You, or the administrator who created your account</td></tr>
          <tr><td>Belongings</td><td>Name, category, make and model, serial number, purchase date, declared value, proof of purchase reference</td><td>You, or an administrator</td></tr>
          <tr><td>Policies</td><td>Policy number, plan, period, status, insured items and every version of the terms</td><td>Administrators</td></tr>
          <tr><td>Claims</td><td>Incident date, type, place and description, damage items, status history, assessor notes, rule results, estimates, decisions and reasons, reserves and simulated payment records</td><td>You and the claims staff</td></tr>
          <tr><td>Evidence files</td><td>Photos, PDF, text and CSV files you upload, with original file name, size, type and uploader. A SHA-256 fingerprint of each file is kept in the audit trail. Photos may contain hidden details such as location and device model. The service does not remove them, so remove them before uploading if you wish.</td><td>You and the claims staff</td></tr>
          <tr><td>Security records</td><td>IP address and browser identifier at sign-in, failed sign-in attempts (username and IP address), session records, and server log lines with time, page path, result code and a request identifier. Logs do not contain request bodies, passwords or query strings.</td><td>Generated automatically</td></tr>
          <tr><td>Audit trail</td><td>A record of every create, change, decision, reserve and payment action with the user and time</td><td>Generated automatically</td></tr>
        </Table>

        <h2>4. Cookies</h2>
        <p>The service sets one cookie, <code>sbc_session</code>, which keeps you signed in. It is strictly necessary, cannot be read by page scripts, is only sent to this site, and is removed when you sign out. The service uses no analytics, advertising or tracking cookies, and loads no third-party scripts, fonts or images.</p>

        <h2>5. Why we use it</h2>
        <p>To run your account, record belongings and policies, assess and record claims, keep an audit trail, and protect the service against misuse (for example, limiting repeated sign-in attempts). Legal basis for processing: <Fact v="" what="legal basis, to be stated by the operator for the applicable law" />.</p>

        <h2>6. AI processing</h2>
        {c.ai_enabled ? (
          <p>An AI provider is configured for this service (provider type: {c.ai_provider}). When a user asks for an AI feature, the following is sent over HTTPS to that provider: for photo description, the selected image together with the asset category, incident type and claim description; for assessment suggestions, the asset category, incident type, claim description, evidence types, existing damage items and repair catalogue component names; for explanations, the policy terms, rule results and calculation; for quotation extraction, the selected image or text file. The provider processes this under its own terms. Provider name, location and retention terms: <Fact v="" what="to be stated by the operator" />.</p>
        ) : (
          <p>No AI provider is configured for this service at the moment. A simple keyword-based fallback runs on the server and is labelled as not AI. Nothing is sent to an outside AI provider. If the operator configures one later, this section must be updated before it is used.</p>
        )}
        <p>AI output is stored with the provider, model, timing and token counts. It is shown as an unverified suggestion, never decides or pays a claim, never sets a price, and a human assessor must verify or correct anything that becomes a claim item.</p>

        <h2>7. Where it is stored</h2>
        <p>Data is stored in the service's database and upload folder on the operator's server. Server location and hosting provider: <Fact v="" what="to be stated by the operator" />. Backups taken by the service (before upgrades and on request) contain a full copy of the data. The software does not itself encrypt data at rest, so protection at rest depends on how the operator configures the server and disks.</p>

        <h2>8. How long it is kept</h2>
        <p>The software has no automatic deletion of accounts, belongings, policies, claims, evidence or audit records, and the audit trail is designed to be permanent. Records are kept until the operator removes them. Failed sign-in records are deleted after 7 days and ended sessions after 30 days. Retention period decided by the operator: <Fact v="" what="to be stated by the operator" />.</p>

        <h2>9. Who can see it</h2>
        <ul>
          <li>Students see their own belongings, policies, claims and evidence only.</li>
          <li>Assessors can read submitted claims and the related belongings, policies and evidence, and can change claims assigned to them or not yet assigned. They cannot see unsubmitted drafts.</li>
          <li>Administrators can see and manage all records, users and the audit trail.</li>
          <li>The AI provider, only if one is configured and only for the data listed in section 6.</li>
          <li>The operator's hosting and infrastructure providers.</li>
        </ul>
        <p>We do not sell personal information and do not use it for advertising. Any disclosure required by law: <Fact v="" what="to be stated by the operator" />.</p>

        <h2>10. Your rights</h2>
        <p>Depending on where you live, you may have rights to access, correct, delete, restrict or object to the use of your personal information, to receive a copy, and to complain to a regulator. To use a right, contact the operator. The service has no self-service export or deletion tool, so such requests are handled by the operator by hand, and some claim and audit records may have to be kept. You can change your password at any time. Regulator and applicable law: <Fact v={c.governing_law} what="governing law" />.</p>

        <h2>11. Security</h2>
        <p>Passwords are hashed with Argon2id. Sessions use random tokens kept in a cookie that page scripts cannot read, with server-side expiry and sign-out. Requests that change data carry a request token against cross-site forgery. Every request is checked on the server for the user's role and ownership of the record. Sign-in attempts, uploads, claim creation, AI requests and payment requests are rate limited. Uploaded files are checked by content, stored under random names and are not run or shown as web pages. Pages are served with a strict content security policy. The operator is responsible for serving the site over HTTPS.</p>
        <p>No system is perfectly secure. Uploaded files are not scanned for malware, and no independent penetration test has been carried out.</p>

        <h2>12. Children</h2>
        <p>Minimum age for using this service: <Fact v="" what="to be stated by the operator" />. The software does not check age.</p>

        <h2>13. Changes</h2>
        <p>If this policy changes, the new version and its date will be published on this page.</p>

        <h2>14. Contact</h2>
        <p><Fact v={c.contact_email} what="contact email" /></p>
      </>
    )}</Shell>
  );
}

export function Terms() {
  return (
    <Shell title="Terms and Conditions">{c => (
      <>
        <h2>1. About these terms</h2>
        <p>These terms apply to your use of StudentBelongings Cover, operated by <Fact v={c.operator_name} what="operator name" /> (the operator). By signing in you agree to them. If you do not agree, do not use the service. Please also read the <Link to="/privacy">Privacy Policy</Link>.</p>

        <h2>2. Purpose of the service</h2>
        <p>The service lets students record belongings, view sample cover plans and policies, and submit claims with evidence, and lets claims staff assess those claims and administer plans and users. It is an academic prototype built to demonstrate how such a system can work.</p>

        <h2>3. Not an insurer and not insurance</h2>
        <p>The operator does not state that it is an insurer, insurance broker or other regulated provider. Policy numbers, plans, limits, deductibles, rules and prices in the service are samples. A policy shown here is a record in this software and is not a contract of insurance. Nothing in the service is a quote, an offer of cover, a promise to pay, or financial, legal or insurance advice.</p>

        <h2>4. Your account and its security</h2>
        <ul>
          <li>Keep your password private and use one that you do not use elsewhere.</li>
          <li>You are responsible for activity under your account. Tell the operator at once if you think it has been used by someone else.</li>
          <li>Accounts are created by an administrator. The operator may disable an account to protect the service or other users.</li>
        </ul>

        <h2>5. Your responsibilities</h2>
        <ul>
          <li>Give information that is true, accurate and complete, including belongings, values, dates and incident descriptions.</li>
          <li>Upload only files you have the right to share. Do not upload other people's personal information unless it is needed for the claim and you are allowed to share it.</li>
          <li>Do not submit a claim that you know to be false or exaggerated.</li>
        </ul>

        <h2>6. Acceptable use</h2>
        <p>Do not try to access records that are not yours, bypass security or rate limits, probe or attack the service, upload malicious files, overload it, or use it to harm others. Do not use automated tools against it without the operator's written permission.</p>

        <h2>7. Limits of the insurance information</h2>
        <p>Rules, exclusions, waiting periods, depreciation and repair prices are fictional samples used to show how calculations work. A result shown in the service applies to this software only.</p>

        <h2>8. Limits of AI assistance</h2>
        <p>Where AI features are available, they produce suggestions that can be wrong, incomplete or based on a photo that cannot show hidden damage. AI never approves, rejects or pays a claim and never sets a price. Anything derived from AI starts as unverified and must be checked by a human assessor. Do not rely on AI output for any decision.</p>

        <h2>9. Limits of claim assessment</h2>
        <p>An estimate shown on a claim is produced by a rules engine from the information entered, and it is a recommendation, not a decision or a promise of payment. A human assessor decides the assessment, and an administrator separately approves reserves and payments. Estimates and decisions can change when information changes or errors are found.</p>

        <h2>10. Simulated payments</h2>
        <p>Payments in the service are simulated. No bank, card or payment provider is contacted. A status such as Paid only means that a simulated settlement was recorded, and no money has been or will be moved because of it.</p>

        <h2>11. Availability and changes</h2>
        <p>The service is provided without a promise that it will be available, error free or retained. Features, plans and rules may change or be removed, and data may be reset, particularly in demonstration use.</p>

        <h2>12. Liability</h2>
        <p>The service is provided as it is. To the extent the law allows, the operator is not liable for loss that results from using the service, from reliance on estimates, AI suggestions or simulated payments, or from the service being unavailable. Nothing in these terms limits any liability that cannot be limited by law. The operator should have this section checked by a lawyer for the applicable law.</p>

        <h2>13. Intellectual property</h2>
        <p>The software and its content belong to the operator or its licensors, and open source components remain under their own licences. You keep ownership of what you submit, and you allow the operator to store and process it to run the service as described in the Privacy Policy. Names of other companies and products that appear in project documentation belong to their owners, and the service is not affiliated with or endorsed by them.</p>

        <h2>14. Ending use</h2>
        <p>You may stop using the service at any time by signing out and asking the operator to disable your account. The operator may suspend or end access if these terms are broken or to protect the service. Records that must be kept, such as the audit trail, may remain afterwards.</p>

        <h2>15. Governing law</h2>
        <p><Fact v={c.governing_law} what="governing law and jurisdiction" /></p>

        <h2>16. Changes to these terms</h2>
        <p>The operator may update these terms. The current version and its date are always on this page, and continued use after a change means you accept it.</p>

        <h2>17. Contact</h2>
        <p><Fact v={c.contact_email} what="contact email" />. Postal address: <Fact v={c.postal_address} what="postal address" />.</p>
      </>
    )}</Shell>
  );
}
