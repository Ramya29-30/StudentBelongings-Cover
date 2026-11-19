import { Suspense, lazy } from 'react';
import { Navigate, Route, Routes } from 'react-router-dom';
import { RequireRole, useAuth } from './auth';
import Layout from './components/Layout';
import ClaimDetail from './components/ClaimDetail';
import Landing from './pages/Landing';
import { About, Contact, Disclaimer } from './pages/Info';
import Login from './pages/Login';
import Register from './pages/Register';
import { Assets as MyAssets, Dashboard as StudentHome, Explore, Payments, Policies as MyPolicies, Profile } from './pages/student/Insure';
import { ClaimsList, ClaimWorkspace, NewClaim as NewAutoClaim } from './pages/student/ClaimFlow';
const AiAnalytics = lazy(() => import('./pages/admin/Insure').then(m => ({ default: m.AiAnalytics })));
const FinanceV3 = lazy(() => import('./pages/admin/Insure').then(m => ({ default: m.FinanceV3 })));  // loads the chart library only when opened
const Categories = lazy(() => import('./pages/admin/Insure').then(m => ({ default: m.Categories })));
const EvidenceQueue = lazy(() => import('./pages/admin/EvidenceReview').then(m => ({ default: m.EvidenceQueue })));
const EvidenceReviewDetail = lazy(() => import('./pages/admin/EvidenceReview').then(m => ({ default: m.EvidenceReviewDetail })));
const Overview = lazy(() => import('./pages/admin/Insure').then(m => ({ default: m.Overview })));
const PoliciesV3 = lazy(() => import('./pages/admin/Insure').then(m => ({ default: m.PoliciesV3 })));
import { AssessorClaims, AssessorDashboard } from './pages/assessor/Pages';
import { ClaimList } from './pages/student/Claims';
import { PolicyCentre, PolicyDetails } from './pages/student/Policies';
import { AdminPolicies, PolicyAdmin, PolicyNew } from './pages/admin/Policies';
import { PlanEditor, PlanList } from './pages/admin/Plans';
import Users from './pages/admin/Users';
import Settings from './pages/admin/Settings';
import AuditPage from './pages/shared/Audit';
import FinanceOverview from './pages/shared/Finance';
import { Privacy, Terms } from './pages/Legal';

/** Unknown addresses go to the right home: the signed-in user's dashboard, otherwise the public landing page. */
function Home() {
  const { user, ready } = useAuth();
  if (!ready) return <p role="status">Loading…</p>;
  return <Navigate to={user ? `/${user.role}` : '/'} replace />;
}
function NotFound() { return <><h1>Page not found</h1><p>The page you asked for does not exist.</p></>; }

export default function App() {
  return (
    <Suspense fallback={<p role="status">Loading…</p>}>
    <Routes>
      <Route path="/" element={<Landing />} />
      <Route path="/about" element={<About />} />
      <Route path="/contact" element={<Contact />} />
      <Route path="/disclaimer" element={<Disclaimer />} />
      <Route path="/login" element={<Login />} />
      <Route path="/register" element={<Register />} />
      <Route path="/privacy" element={<Privacy />} />
      <Route path="/terms" element={<Terms />} />
      <Route path="/student" element={<RequireRole role="student"><Layout /></RequireRole>}>
        <Route index element={<StudentHome />} />
        <Route path="assets" element={<MyAssets />} />
        <Route path="explore" element={<Explore />} />
        <Route path="policies" element={<MyPolicies />} />
        <Route path="claims" element={<ClaimsList />} />
        <Route path="claims/new" element={<NewAutoClaim />} />
        <Route path="claims/:id" element={<ClaimWorkspace />} />
        <Route path="payments" element={<Payments />} />
        <Route path="profile" element={<Profile />} />
        <Route path="*" element={<NotFound />} />
      </Route>
      <Route path="/assessor" element={<RequireRole role="assessor"><Layout /></RequireRole>}>
        <Route index element={<AssessorDashboard />} />
        <Route path="reviews" element={<ClaimsList staff detailBase="/assessor/reviews" only="Exceptional Review Required" />} />
        <Route path="reviews/:id" element={<ClaimWorkspace staff backTo="/assessor/reviews" />} />
        <Route path="claims" element={<AssessorClaims />} />
        <Route path="claims/:id" element={<ClaimDetail role="assessor" base="/assessor" />} />
        <Route path="finance" element={<FinanceOverview base="/assessor" />} />
        <Route path="policies" element={<PolicyCentre base="/assessor" />} />
        <Route path="policies/:id" element={<PolicyDetails base="/assessor" />} />
        <Route path="audit" element={<AuditPage />} />
        <Route path="*" element={<NotFound />} />
      </Route>
      <Route path="/admin" element={<RequireRole role="admin"><Layout /></RequireRole>}>
        <Route index element={<Overview />} />
        <Route path="categories" element={<Categories />} />
        <Route path="policy-list" element={<PoliciesV3 />} />
        <Route path="claims" element={<ClaimsList staff detailBase="/admin/claims" />} />
        <Route path="claims/:id" element={<ClaimWorkspace staff backTo="/admin/claims" />} />
        <Route path="reviews" element={<ClaimsList staff detailBase="/admin/claims" only="Exceptional Review Required" />} />
        <Route path="evidence" element={<EvidenceQueue />} />
        <Route path="evidence/:id" element={<EvidenceReviewDetail />} />
        <Route path="ai" element={<AiAnalytics />} />
        <Route path="financials" element={<FinanceV3 />} />
        <Route path="policies" element={<AdminPolicies />} />
        <Route path="policies/new" element={<PolicyNew />} />
        <Route path="policies/:id" element={<PolicyAdmin />} />
        <Route path="plans" element={<PlanList />} />
        <Route path="plans/new" element={<PlanEditor isNew />} />
        <Route path="plans/:id" element={<PlanEditor />} />
        <Route path="legacy-claims" element={<><h1>Legacy claim monitoring</h1><ClaimList base="/admin" /></>} />
        <Route path="legacy-claims/:id" element={<ClaimDetail role="admin" base="/admin" />} />
        <Route path="finance" element={<FinanceOverview base="/admin" />} />
        <Route path="users" element={<Users />} />
        <Route path="audit" element={<AuditPage />} />
        <Route path="settings" element={<Settings />} />
        <Route path="*" element={<NotFound />} />
      </Route>
      <Route path="*" element={<Home />} />
    </Routes>
    </Suspense>
  );
}
