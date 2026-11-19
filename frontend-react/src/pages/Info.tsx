import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api';
import { SiteFooterPublic } from '../components/PublicFooter';
import { BrandMark } from '../components/Art';
import { Async, Notice, useLoad, usePageTitle } from '../ui';

function Page({ title, children }: { title: string; children: ReactNode }) {
  usePageTitle(title);
  return (
    <>
      <header className="pub-nav"><div className="bar"><Link to="/" className="brand"><BrandMark /><span>StudentBelongings Cover</span></Link><ul style={{ display: 'flex' }}><li><Link to="/">Home</Link></li></ul></div></header>
      <main id="main" className="legal" tabIndex={-1} style={{ outline: 'none' }}><h1>{title}</h1>{children}</main>
      <SiteFooterPublic />
    </>
  );
}

export function About() {
  return (
    <Page title="About">
      <p>StudentBelongings Cover is an academic prototype that shows how affordable belongings protection for college students could work. It covers six categories of everyday items and walks through the whole journey: registering an item, getting a quote, buying a simulated policy, filing a claim with photos, and seeing the result.</p>
      <h2>Two separate AI systems</h2>
      <p>CoverMate AI is a language model that explains insurance and your own policy in simple words. The damage check is a separate computer vision process that reviews claim photos and writes an evidence report. Neither one decides a claim. A rules engine does, and uncertain cases go to a person.</p>
      <h2>What this is not</h2>
      <p>It is not a licensed insurer. Policies, payments and settlements are simulated, and prices and limits are sample values.</p>
    </Page>
  );
}

export function Contact() {
  const c = useLoad(() => api<{ operator_name: string; contact_email: string; postal_address: string }>('/legal-config'), []);
  return (
    <Page title="Contact">
      <Async state={c}>{d => (
        <>
          {!d.contact_email && !d.postal_address ? <Notice kind="warn">The operator of this deployment has not published contact details yet.</Notice> : null}
          <dl className="kv">
            <dt>Operator</dt><dd>{d.operator_name || <span className="missing">not provided</span>}</dd>
            <dt>Email</dt><dd>{d.contact_email ? <a href={`mailto:${d.contact_email}`}>{d.contact_email}</a> : <span className="missing">not provided</span>}</dd>
            <dt>Postal address</dt><dd>{d.postal_address || <span className="missing">not provided</span>}</dd>
          </dl>
        </>
      )}</Async>
    </Page>
  );
}

export function Disclaimer() {
  return (
    <Page title="Insurance Disclaimer">
      <Notice kind="warn"><strong>Academic prototype.</strong> Nothing on this site is an offer of insurance, financial advice or legal advice.</Notice>
      <ul>
        <li>StudentBelongings Cover is not a licensed insurer and issues no real policies.</li>
        <li>Premiums, coverage limits, deductibles, repair costs and finance figures are sample values chosen for demonstration. They are not validated actuarial projections and do not guarantee any profit or payout.</li>
        <li>Payments and settlements are simulated. No card, bank or payment gateway is used and no money moves.</li>
        <li>AI output can be wrong. The damage check reviews visual evidence only and cannot prove ownership or that a person is telling the truth. CoverMate AI explains information and does not decide claims. Official figures and decisions are the ones shown on your Policy and Claim pages.</li>
        <li>Cover, where described, pays the assessed loss up to the maximum coverage after any deductible. It is not a refund of the purchase price.</li>
      </ul>
    </Page>
  );
}
