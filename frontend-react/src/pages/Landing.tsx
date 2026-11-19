import { useState } from 'react';
import { Link } from 'react-router-dom';
import { BadgeIndianRupee, Bot, FileCheck2, Menu, ScanSearch, ShieldCheck, Sparkles, X, Scale } from 'lucide-react';
import { api } from '../api';
import { useAuth } from '../auth';
import { AssetArt, BrandMark, HeroArt } from '../components/Art';
import { SiteFooterPublic } from '../components/PublicFooter';
import { money, useLoad, usePageTitle } from '../ui';
import type { Category } from '../types3';

const NAV: [string, string][] = [['#home', 'Home'], ['#how', 'How it works'], ['#plans', 'Coverage plans'], ['#why', 'Why choose us'], ['#faq', 'FAQ']];

const WHY = [
  { icon: BadgeIndianRupee, title: 'Affordable monthly premiums', text: 'Pay a small amount each month for each belonging you insure. Every price is shown before you buy.' },
  { icon: ShieldCheck, title: 'Protection for eligible belongings', text: 'Laptops, phones, tablets, earbuds, bicycles and smartwatches that meet the minimum purchase value can be covered.' },
  { icon: FileCheck2, title: 'Simple claim submission', text: 'Tell us what happened, add clear photos, and follow the claim from submission to result.' },
  { icon: ScanSearch, title: 'AI-assisted damage verification', text: 'A computer vision check reviews your photos and writes a report that explains what it could and could not see.' },
  { icon: Scale, title: 'Transparent coverage limits', text: 'Each policy states its maximum coverage, deductible and exclusions. Cover is for the loss, up to the limit, not the full price you paid.' },
  { icon: Bot, title: 'Easy-to-understand information', text: 'CoverMate AI explains insurance words and your own policy in everyday language.' },
];

const STEPS: [string, string, boolean?][] = [
  ['Register an account', 'Create a student account in a minute.'],
  ['Add your belongings', 'Enter the brand, model, value, serial number, invoice and a photo.'],
  ['Check eligibility', 'The system compares your purchase value with the category minimum and tells you the exact reason if it is not eligible.'],
  ['Select a plan', 'See the premium, coverage limit, deductible and exclusions before you decide.'],
  ['Activate the simulated policy', 'No real money moves. This is an academic prototype.'],
  ['Submit a claim', 'If damage happens, describe the incident and upload photos.'],
  ['Receive AI-assisted verification', 'Image checks produce an explainable evidence report.', true],
  ['Track the outcome', 'Rules decide the claim, uncertain cases go to a person, and you can see every step.'],
];

const FAQ: [string, string][] = [
  ['What is an insurance premium?', 'A premium is the amount you pay to keep a policy active. Here you pay it monthly, and the amount depends on the type of belonging.'],
  ['What does maximum coverage mean?', 'It is the most the policy will pay for one claim. If the loss is larger than the limit, the extra amount is not paid.'],
  ['What happens if my asset is damaged?', 'You submit a claim with a description and photos. The photos are checked, the policy rules are applied, and you can see the result and the reasons on your claim page.'],
  ['How do I submit a claim?', 'Sign in, open Submit a claim, choose the insured belonging, describe what happened and upload clear photos of the damage.'],
  ['What is a deductible?', 'A deductible is the part of a loss you pay yourself. It is subtracted from the loss before the policy pays. Your policy shows whether one applies.'],
  ['What does an exclusion mean?', 'An exclusion is something the policy does not cover. Each plan lists its exclusions so you can read them before buying.'],
  ['Can I insure an asset below its minimum value?', 'No. Each category has a minimum purchase value. If your item is below it, the system tells you which minimum applies. The current minimums are in the pricing table on this page.'],
  ['How does AI damage verification work?', 'Software checks that your photos are clear, tries to identify the item, looks for visible damage, and compares what it finds with your description. It writes a report. It does not decide the claim and it cannot prove who owns an item. Unclear cases are sent to a person.'],
];

export default function Landing() {
  usePageTitle('Protect what matters');
  const { user } = useAuth();
  const [open, setOpen] = useState(false);
  const cats = useLoad(() => api<Category[]>('/v2/categories'), []);
  const list = cats.data ?? [];
  const close = () => setOpen(false);
  return (
    <>
      <a className="skip" href="#content">Skip to main content</a>
      <header className="pub-nav">
        <div className="bar">
          <Link to="/" className="brand" aria-label="StudentBelongings Cover home"><BrandMark /><span>StudentBelongings Cover</span></Link>
          <button type="button" className="nav-toggle" aria-expanded={open} aria-controls="pub-menu" onClick={() => setOpen(o => !o)}>
            {open ? <X size={18} aria-hidden="true" /> : <Menu size={18} aria-hidden="true" />}<span>Menu</span>
          </button>
          <nav aria-label="Primary">
            <ul id="pub-menu" className={open ? 'open' : ''}>
              {NAV.map(([h, l]) => <li key={h}><a href={h} onClick={close}>{l}</a></li>)}
              {user ? <li><Link className="btn" to={`/${user.role}`}>Open dashboard</Link></li> : <>
                <li><Link to="/login" onClick={close}>Sign in</Link></li>
                <li><Link className="btn" to="/register" onClick={close}>Get started</Link></li>
              </>}
            </ul>
          </nav>
        </div>
      </header>

      <main id="content" tabIndex={-1} style={{ padding: 0, maxWidth: 'none', outline: 'none' }}>
        <section className="hero" id="home" aria-labelledby="hero-h">
          <div className="wrap">
            <div>
              <h1 id="hero-h">Protect What Matters. Study Without Worry.</h1>
              <p className="lead">Affordable personal belongings protection designed for students. Protect your laptop, smartphone, tablet, earbuds, and other eligible essentials without expensive premiums.</p>
              <div className="actions">
                <a className="btn lg on-dark" href="#plans">Explore plans</a>
                <a className="btn lg outline-dark" href="#how">How it works</a>
              </div>
              <p className="note">Academic prototype. Policies, payments and settlements are simulated, and this is not a licensed insurer.</p>
            </div>
            <HeroArt />
          </div>
        </section>

        <section className="section" id="why" aria-labelledby="why-h">
          <div className="wrap">
            <div className="section-head"><span className="eyebrow">Why StudentBelongings Cover</span><h2 id="why-h">Cover that is easy to understand</h2><p>Built around what students actually carry to class, with the numbers in plain sight.</p></div>
            <div className="feature-grid">
              {WHY.map(w => <article className="feature" key={w.title}><div className="ico"><w.icon size={22} aria-hidden="true" /></div><h3>{w.title}</h3><p>{w.text}</p></article>)}
            </div>
          </div>
        </section>

        <section className="section alt" id="protect" aria-labelledby="protect-h">
          <div className="wrap">
            <div className="section-head"><span className="eyebrow">What can you protect?</span><h2 id="protect-h">Six everyday essentials</h2><p>Figures below are the live values from our catalogue.</p></div>
            {cats.loading && !cats.data ? <p role="status" className="muted">Loading categories…</p> : null}
            {cats.error ? <div className="empty" role="alert">The coverage catalogue could not be loaded right now. Please refresh in a moment.</div> : null}
            {!cats.loading && !cats.error && list.length === 0 ? <div className="empty">No categories are being offered at the moment.</div> : null}
            <div className="asset-grid">
              {list.map(c => (
                <article className="asset-card" key={c.id}>
                  <div className="art"><AssetArt kind={c.name} /></div>
                  <div className="body">
                    <h3>{c.name}</h3>
                    <dl>
                      <dt>Minimum purchase value</dt><dd>{money(c.min_purchase_value)}</dd>
                      <dt>Monthly premium</dt><dd>{money(c.monthly_premium)}</dd>
                      <dt>Maximum coverage</dt><dd>{money(c.max_coverage)}</dd>
                    </dl>
                  </div>
                </article>
              ))}
            </div>
          </div>
        </section>

        <section className="section" id="how" aria-labelledby="how-h">
          <div className="wrap">
            <div className="section-head"><span className="eyebrow">How it works</span><h2 id="how-h">From sign-up to claim result in eight steps</h2><p>Every step is recorded, so you can always see where you stand.</p></div>
            <ol className="steps">
              {STEPS.map(([t, d, ai]) => <li key={t} className={ai ? 'ai' : ''}><h3>{t}</h3><p>{d}</p></li>)}
            </ol>
          </div>
        </section>

        <section className="section dark" id="covermate" aria-labelledby="cm-h">
          <div className="wrap ai-split">
            <div>
              <span className="eyebrow">CoverMate AI</span>
              <h2 id="cm-h">Insurance Terms Too Complicated? Just Ask AI.</h2>
              <p>Understand your insurance coverage, exclusions, premiums, and claim process in simple language. CoverMate AI helps explain complicated insurance terms in a way students can understand.</p>
              <p>It answers new questions as you ask them, remembers what you just talked about, and reads your own policy and claims to explain them. It never decides a claim.</p>
              <Link className="btn lg on-dark" to={user ? `/${user.role}` : '/login'}><Sparkles size={18} aria-hidden="true" />Try AI assistant</Link>
            </div>
            <div className="chat-preview" role="group" aria-label="Preview of the CoverMate AI chat window">
              <header><Bot size={20} aria-hidden="true" />CoverMate AI</header>
              <div className="msgs">
                <div className="cm-msg ai">Hi! I'm CoverMate AI. Insurance terms can be confusing, but don't worry. Ask me anything about your coverage, policy, premiums, exclusions, or claims. I'll explain everything in simple language.</div>
              </div>
              <div className="chips">
                {['What is insurance?', 'What is a deductible?', 'Why might a claim be rejected?'].map(q => <Link key={q} className="cm-chip btn secondary sm" to={user ? `/${user.role}` : '/login'}>{q}</Link>)}
              </div>
              <div className="fake-input" aria-hidden="true"><span>Ask anything about insurance</span><span>Send</span></div>
            </div>
          </div>
        </section>

        <section className="section" id="plans" aria-labelledby="plans-h">
          <div className="wrap">
            <div className="section-head"><span className="eyebrow">Coverage plans</span><h2 id="plans-h">Transparent pricing</h2><p>Annual premium is the monthly premium multiplied by 12. Cover pays the assessed loss up to the maximum coverage, after any deductible.</p></div>
            {list.length > 0 ? (
              <div className="table-wrap">
                <table className="price-table">
                  <caption className="sr-only">Premiums and coverage limits by category</caption>
                  <thead><tr><th scope="col">Asset</th><th scope="col" className="num">Minimum value</th><th scope="col" className="num">Monthly premium</th><th scope="col" className="num">Annual premium</th><th scope="col" className="num">Maximum coverage</th><th scope="col" className="num">Deductible</th></tr></thead>
                  <tbody>{list.map(c => <tr key={c.id}><th scope="row">{c.name}</th><td className="num">{money(c.min_purchase_value)}</td><td className="num">{money(c.monthly_premium)}</td><td className="num">{money(c.annual_premium)}</td><td className="num">{money(c.max_coverage)}</td><td className="num">{c.deductible > 0 ? money(c.deductible) : 'None'}</td></tr>)}</tbody>
                </table>
              </div>
            ) : <div className="empty">Pricing appears here once the catalogue loads.</div>}
            <p className="hint">Prices are sample values for an academic prototype and are not an offer of real insurance.</p>
            <div className="row" style={{ marginTop: '1rem' }}><Link className="btn lg" to={user ? `/${user.role}` : '/register'}>{user ? 'Open dashboard' : 'Create a student account'}</Link></div>
          </div>
        </section>

        <section className="section alt" id="faq" aria-labelledby="faq-h">
          <div className="wrap">
            <div className="section-head"><span className="eyebrow">FAQ</span><h2 id="faq-h">Common questions</h2></div>
            <div className="faq">{FAQ.map(([q, a]) => <details key={q}><summary>{q}</summary><p>{a}</p></details>)}</div>
          </div>
        </section>
      </main>
      <SiteFooterPublic />
    </>
  );
}
