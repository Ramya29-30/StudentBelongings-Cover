import { NavLink, Outlet, useLocation } from 'react-router-dom';
import { useEffect, useRef } from 'react';
import { BarChart3, Boxes, ClipboardCheck, ClipboardList, CreditCard, FileCheck2, FilePlus2, Gauge, History, Landmark, LayoutDashboard, LifeBuoy, ScrollText, Settings, ShieldCheck, Sparkles, UserCircle, Users } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { useAuth } from '../auth';
import { Notice, useLoad } from '../ui';
import { api } from '../api';
import { SiteFooter } from '../pages/Legal';
import { BrandMark } from './Art';
import CoverMate from './CoverMate';

const NAV: Record<string, [string, string, LucideIcon][]> = {
  student: [['/student', 'Dashboard', LayoutDashboard], ['/student/assets', 'My assets', Boxes], ['/student/explore', 'Explore plans', Sparkles], ['/student/policies', 'My policies', ShieldCheck], ['/student/claims/new', 'Submit a claim', FilePlus2], ['/student/claims', 'AI verification results', FileCheck2], ['/student/payments', 'Payment history', CreditCard], ['/student/profile', 'Profile', UserCircle]],
  assessor: [['/assessor', 'Dashboard', LayoutDashboard], ['/assessor/reviews', 'Exceptional reviews', ClipboardList], ['/assessor/claims', 'Manual claims', FileCheck2], ['/assessor/finance', 'Reserves and payments', Landmark], ['/assessor/policies', 'Policies', ShieldCheck], ['/assessor/audit', 'Audit history', History]],
  admin: [['/admin', 'Overview', LayoutDashboard], ['/admin/categories', 'Categories and plans', Boxes], ['/admin/policy-list', 'Policies', ShieldCheck], ['/admin/evidence', 'Evidence review', ClipboardCheck], ['/admin/claims', 'Claims', FileCheck2], ['/admin/reviews', 'Exceptional reviews', ClipboardList], ['/admin/ai', 'AI verification analytics', BarChart3], ['/admin/financials', 'Financial performance', Gauge], ['/admin/users', 'Users', Users], ['/admin/audit', 'Audit logs', ScrollText], ['/admin/plans', 'Legacy plans', LifeBuoy], ['/admin/legacy-claims', 'Legacy claims', FileCheck2], ['/admin/finance', 'Legacy reserves', Landmark], ['/admin/settings', 'Settings', Settings]],
};

export default function Layout() {
  const { user, signOut } = useAuth();
  const loc = useLocation();
  const main = useRef<HTMLElement>(null);
  const cfg = useLoad(() => api<{ banner: string; demo_mode: boolean }>('/public-config'), [loc.pathname]); // re-check on navigation so a new banner appears without a reload
  // Move focus to the page content on route change so keyboard / screen-reader users land in the new view.
  const prev = useRef(loc.pathname);
  useEffect(() => {
    if (prev.current !== loc.pathname) { prev.current = loc.pathname; main.current?.focus(); } // not on first load: the skip link must be the first Tab stop
  }, [loc.pathname]);
  if (!user) return null;
  return (
    <>
      <a className="skip" href="#main">Skip to main content</a>
      <header className="top">
        <a href="/" className="brand"><BrandMark size={30} /><span>StudentBelongings Cover<small>Academic prototype. Simulated payments and settlements.</small></span></a>
        <div className="userbox">
          <span>{user.full_name}</span><span className="role-chip">{user.role}</span>
          <button className="secondary sm" onClick={() => void signOut()}>Sign out</button>
        </div>
      </header>
      <div className="layout">
        <nav className="side" aria-label="Main">
          <ul>
            {NAV[user.role].map(([to, label, Icon]) => (
              <li key={to}><NavLink to={to} end={to.split('/').length === 2}><Icon size={18} aria-hidden="true" />{label}</NavLink></li>
            ))}
          </ul>
        </nav>
        <main id="main" ref={main} tabIndex={-1} style={{ outline: 'none' }}>
          {cfg.data?.banner ? <Notice kind="warn">{cfg.data.banner}</Notice> : null}
          <Outlet />
        </main>
      </div>
      <SiteFooter />
      <CoverMate />
    </>
  );
}
