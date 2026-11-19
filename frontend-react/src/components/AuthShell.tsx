import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { BrandMark, HeroArt } from './Art';

/** Two-column frame for sign in and register: brand panel on the left, form on the right. */
export default function AuthShell({ heading, blurb, children }: { heading: string; blurb: string; children: ReactNode }) {
  return (
    <div className="auth">
      <aside className="auth-side">
        <Link to="/" className="brand" style={{ color: '#fff', textDecoration: 'none' }}><BrandMark /><span>StudentBelongings Cover</span></Link>
        <div>
          <h2>{heading}</h2>
          <p>{blurb}</p>
          <div className="auth-art"><HeroArt /></div>
        </div>
        <p style={{ margin: 0, fontSize: '.9rem' }}>Academic prototype. Policies, payments and settlements are simulated.</p>
      </aside>
      <main className="auth-main" id="main">{children}</main>
    </div>
  );
}
