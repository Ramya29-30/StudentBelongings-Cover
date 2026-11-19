import { describe, expect, it } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { base, calls, mockApi, renderApp, user } from './harness';

const cats = [
  { id: 1, name: 'Laptop', description: 'Laptops', min_purchase_value: 20000, monthly_premium: 99, annual_premium: 1188, max_coverage: 18000, deductible: 0, policy_months: 12, waiting_period_days: 0, exclusions: ['Theft and loss are not covered'], covered_incident_types: ['Accidental Damage'], damage_types: ['Broken screen', 'Cracked body'], reference_repair_costs: {}, eligibility_conditions: 'Purchased new for at least Rs 20,000.', requires_serial: true, active: true, excluded_damage_types: [], depreciation_pct_per_year: 0, depreciation_max_pct: 0 },
  { id: 2, name: 'Earbuds', description: 'Earbuds', min_purchase_value: 2500, monthly_premium: 50, annual_premium: 600, max_coverage: 2000, deductible: 0, policy_months: 12, waiting_period_days: 0, exclusions: ['Intentional damage'], covered_incident_types: ['Accidental Damage'], damage_types: ['Broken casing'], reference_repair_costs: {}, eligibility_conditions: 'Purchased new for at least Rs 2,500.', requires_serial: false, active: true, excluded_damage_types: [], depreciation_pct_per_year: 0, depreciation_max_pct: 0 },
];
const quote = { category: 'Laptop', purchase_value: 40000, monthly_premium: 99, annual_premium: 1188, max_coverage: 18000, estimated_max_claim: 18000, deductible: 0, policy_months: 12, waiting_period_days: 0, exclusions: ['Theft and loss are not covered'], covered_incident_types: ['Accidental Damage'], formula: { annual_premium: 'x', estimated_max_claim: 'y' } };
const asset = { id: 7, category: 'Laptop', category_id: 1, name: 'Acme X1', brand: 'Acme', model_name: 'X1', description: '', serial_number: 'S1', purchase_date: '2026-01-01', purchase_price: 40000, has_invoice: true, has_photo: true, invoice_verified: false, invoice_status: 'Uploaded, not yet verified', eligibility_status: 'Eligible', eligibility_reason: 'Eligible', policy: null, evidence_status: 'Approved', can_purchase: true };
const insuredAsset = { ...asset, policy: { id: 3, policy_number: 'SBC-2026-00009', status: 'Active', max_coverage: 18000, monthly_premium: 99 } };

describe('sign in and role based navigation', () => {
  it('validates the login form and signs a student in', async () => {
    mockApi({ 'GET /auth/me': { __status: 401, body: { detail: 'no' } }, 'GET /auth/demo-accounts': [], 'POST /auth/login': { user: user('student'), csrf_token: 'tok', expires_at: 'x' }, 'GET /meta': {}, 'GET /public-config': { banner: '' },
      'GET /v2/dashboard': { active_policies: 0, insured_assets: 0, registered_assets: 0, total_coverage: 0, monthly_commitment: 0, premium_due: [], recent_claims: [], recent_transactions: [] } });
    renderApp('/login');
    const u = userEvent.setup();
    await u.click(await screen.findByRole('button', { name: 'Sign in' }));
    expect(await screen.findByText('Enter your username')).toBeInTheDocument();
    await u.type(screen.getByLabelText(/Username/), 'riya');
    await u.type(screen.getByLabelText(/Password/), 'student123');
    await u.click(screen.getByRole('button', { name: 'Sign in' }));
    expect(await screen.findByRole('heading', { name: /Welcome, Riya/ })).toBeInTheDocument();
    expect(calls.find(c => c.path === '/auth/login')?.body).toEqual({ username: 'riya', password: 'student123' });
  });

  it('shows students only student navigation and sends them away from admin pages', async () => {
    mockApi({ ...base('student'), 'GET /v2/dashboard': { active_policies: 1, insured_assets: 1, registered_assets: 1, total_coverage: 18000, monthly_commitment: 99, premium_due: [], recent_claims: [], recent_transactions: [] } });
    renderApp('/admin/financials');
    expect(await screen.findByRole('heading', { name: /Welcome/ })).toBeInTheDocument();
    const nav = screen.getByRole('navigation', { name: 'Main' });
    expect(within(nav).getByRole('link', { name: 'Explore plans' })).toBeInTheDocument();
    expect(within(nav).queryByRole('link', { name: 'Financial performance' })).toBeNull();
  });

  it('shows administrators the admin navigation and overview', async () => {
    mockApi({ ...base('admin'), 'GET /v2/admin/overview': { students: 6, active_policies: 8, insured_assets: 8, premium_revenue: 2899, claims_received: 3, claims_approved: 1, claims_rejected: 1, pending_exceptional_reviews: 1, more_evidence: 0 } });
    renderApp('/admin');
    expect(await screen.findByRole('heading', { name: 'Overview' })).toBeInTheDocument();
    expect(await screen.findByText('Registered students')).toBeInTheDocument();
    expect(screen.getByText(/1 claim\(s\) need an exceptional review/)).toBeInTheDocument();
    const nav = screen.getByRole('navigation', { name: 'Main' });
    for (const n of ['Categories and plans', 'AI verification analytics', 'Financial performance', 'Exceptional reviews', 'Settings']) expect(within(nav).getByRole('link', { name: n })).toBeInTheDocument();
    expect(within(nav).queryByRole('link', { name: 'Submit a claim' })).toBeNull();
  });
});

describe('student dashboard', () => {
  it('shows policies, coverage, premium commitment and the due premium action', async () => {
    mockApi({ ...base('student'), 'GET /v2/dashboard': { active_policies: 2, insured_assets: 2, registered_assets: 3, total_coverage: 20000, monthly_commitment: 149, premium_due: [{ policy_id: 3, policy_number: 'SBC-1', period: '2026-11' }],
      recent_claims: [{ id: 4, claim_number: 'CLM-2026-01004', asset_name: 'Acme X1', ai_outcome: 'Evidence Supported', status: 'Settled', payable_amount: 6000 }], recent_transactions: [{ id: 1, reference: 'PRM-1', policy_number: 'SBC-1', period: '2026-10', amount: 99, status: 'Paid' }] },
    'POST /v2/policies/3/pay-premium': { id: 9 } });
    renderApp('/student');
    expect(await screen.findByText('Total coverage')).toBeInTheDocument();
    expect(screen.getByText('\u20B920,000.00')).toBeInTheDocument();
    expect(screen.getByText('\u20B9149.00')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'CLM-2026-01004' })).toHaveAttribute('href', '/student/claims/4');
    await userEvent.setup().click(screen.getByRole('button', { name: /Pay now/ }));
    await waitFor(() => expect(calls.some(c => c.method === 'POST' && c.path === '/v2/policies/3/pay-premium')).toBe(true));
  });
});

describe('asset registration and eligibility', () => {
  it('explains why an asset below the minimum value is not eligible and blocks registration', async () => {
    const msg = 'Your earbuds are not eligible because the minimum purchase value for this category is \u20B92,500.';
    mockApi({ ...base('student'), 'GET /v2/assets': [], 'GET /v2/categories': cats, 'POST /v2/eligibility': (b: any) => (b.purchase_price < 2500 ? { eligible: false, reason: msg, quote: null } : { eligible: true, reason: 'Eligible: the purchase value meets the minimum.', quote }) });
    renderApp('/student/assets');
    const u = userEvent.setup();
    await u.click(await screen.findByRole('button', { name: 'Add an asset' }));
    await u.selectOptions(await screen.findByLabelText(/Category/), '2');
    await u.type(screen.getByLabelText(/Purchase price/), '1500');
    expect(await screen.findByText(msg)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Check eligibility and register' })).toBeDisabled();
    await u.clear(screen.getByLabelText(/Purchase price/));
    await u.type(screen.getByLabelText(/Purchase price/), '3000');
    expect(await screen.findByText(/Eligible: the purchase value meets/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Check eligibility and register' })).toBeEnabled();
  });

  it('requires the front and back photographs and details before registering, but not an invoice', async () => {
    mockApi({ ...base('student'), 'GET /v2/assets': [], 'GET /v2/categories': cats });
    renderApp('/student/assets');
    const u = userEvent.setup();
    await u.click(await screen.findByRole('button', { name: 'Add an asset' }));
    await u.click(await screen.findByRole('button', { name: 'Check eligibility and register' }));
    expect(await screen.findByText('Choose a category', { selector: '.field-error' })).toBeInTheDocument();
    expect(screen.getByText(/Upload a photograph of the front of the item/)).toBeInTheDocument();
    expect(screen.getByText(/Upload a photograph of the back of the item/)).toBeInTheDocument();
    expect(screen.queryByText(/Upload the invoice/)).not.toBeInTheDocument();  // an invoice is asked for "where available"
    expect(calls.some(c => c.method === 'POST' && c.path === '/v2/assets')).toBe(false);
  });
});

describe('plan selection and policy purchase', () => {
  it('lists the plans with server prices and calculates a premium', async () => {
    mockApi({ ...base('student'), 'GET /v2/categories': cats, 'GET /v2/assets': [], 'POST /v2/eligibility': { eligible: true, reason: 'Eligible: ok.', quote } });
    renderApp('/student/explore');
    const laptop = await screen.findByRole('article', { name: /Laptop/ });
    expect(within(laptop).getByText('\u20B918,000.00')).toBeInTheDocument();
    expect(within(laptop).getByText('\u20B91,188.00')).toBeInTheDocument();
    const u = userEvent.setup();
    await u.selectOptions(screen.getByLabelText('Category'), '1');
    await u.type(screen.getByLabelText(/Purchase price/), '40000');
    expect(await screen.findByText('Estimated maximum claim')).toBeInTheDocument();
  });

  it('shows the full breakdown, needs consent, then buys through the backend (simulated)', async () => {
    mockApi({ ...base('student'), 'GET /v2/categories': cats, 'GET /v2/assets': [asset], 'GET /v2/assets/7/quote': { eligible: true, reason: 'ok', quote, active_policy: false },
      'POST /v2/assets/7/purchase': { id: 3 }, 'GET /v2/policies': [] });
    renderApp('/student/assets');
    const u = userEvent.setup();
    await u.click(await screen.findByRole('button', { name: 'Insure this asset' }));
    expect(await screen.findByText(/Simulated purchase/)).toBeInTheDocument();
    expect(await screen.findByText('Maximum coverage')).toBeInTheDocument();
    const buy = screen.getByRole('button', { name: /Pay .*99.* and activate/ });
    expect(buy).toBeDisabled();
    await u.click(screen.getByLabelText(/accept the policy terms/));
    await u.click(buy);
    await waitFor(() => expect(calls.find(c => c.path === '/v2/assets/7/purchase')?.body).toEqual({ accept_terms: true }));
  });
});

describe('claim submission and AI report', () => {
  it('walks through asset and incident steps and creates the claim with no money or policy fields', async () => {
    mockApi({ ...base('student'), 'GET /v2/assets': [insuredAsset], 'GET /v2/categories': cats, 'POST /v2/claims': { id: 11, claim_number: 'CLM-1', status: 'Submitted', images: [] },
      'GET /v2/claims/11': { id: 11, claim_number: 'CLM-1', status: 'Submitted', asset_name: 'Acme X1', asset_category: 'Laptop', policy_number: 'P', incident_type: 'Accidental Damage', incident_date: '2026-11-01', damage_type: 'Broken screen', description: 'x', images: [], estimated_repair_cost: null },
      'GET /v2/ai/capabilities': { effective_mode: 'development_simulation', note: '' } });
    renderApp('/student/claims/new');
    const u = userEvent.setup();
    await u.selectOptions(await screen.findByLabelText('Insured asset'), '7');
    await u.click(screen.getByRole('button', { name: 'Continue' }));
    await u.click(await screen.findByRole('button', { name: 'Continue to photos' }));
    expect(await screen.findByText('Choose the type of damage', { selector: '.field-error' })).toBeInTheDocument();
    await u.selectOptions(screen.getByLabelText(/Type of damage/), 'Broken screen');
    await u.type(screen.getByLabelText(/Describe the incident/), 'My laptop fell and the screen cracked.');
    await u.click(screen.getByRole('button', { name: 'Continue to photos' }));
    await waitFor(() => expect(calls.some(c => c.method === 'POST' && c.path === '/v2/claims')).toBe(true));
    const body = calls.find(c => c.path === '/v2/claims' && c.method === 'POST')!.body;
    expect(body).toMatchObject({ asset_id: 7, damage_type: 'Broken screen', incident_type: 'Accidental Damage' });
    expect(Object.keys(body).some(k => /payable|policy|coverage|amount/.test(k))).toBe(false);
    expect(await screen.findByRole('heading', { name: /Claim CLM-1/ })).toBeInTheDocument();
    expect(await screen.findByText(/Development simulation is on/)).toBeInTheDocument();
  });

  const settled = {
    id: 11, claim_number: 'CLM-2026-01011', status: 'Settled', asset_name: 'Acme X1', asset_category: 'Laptop', policy_number: 'SBC-1', claimant_name: 'Riya', incident_type: 'Accidental Damage', incident_date: '2026-11-01', damage_type: 'Broken screen',
    description: 'Screen cracked after a fall.', estimated_repair_cost: null, payable_amount: 6000, decision_reason: 'All policy checks passed.', ai_outcome: 'Evidence Supported',
    images: [{ id: 1, original_name: 'a.png', size_bytes: 10, width: 10, height: 10 }],
    report: { id: 1, run: 1, mode: 'development_simulation', is_simulated: true, model_info: {}, quality: { images: [{ image: 'a.png', usable: true, score: 91, issues: [] }], usable_count: 1, total_count: 1, average_score: 91, result: 'Good' },
      asset_identification: { status: 'Simulated', detected: 'Laptop', confidence: null, match: 'Consistent (assumed)', explanation: 'assumed' }, damage_detection: { status: 'Simulated', detections: [{ damage_type: 'Broken screen', confidence: null, box: null, source: 'simulation' }], explanation: 'assumed', method: 'assumed' },
      description_check: { result: 'Consistent', notes: [], method: 'rule-based keyword comparison (not machine learning)' }, duplicate_check: { result: 'No matching previous image found' }, evidence_completeness: { photos_uploaded: 1, supporting_documents: 0, complete: true },
      risk_indicators: [], outcome: 'Evidence Supported', route: 'auto', explanation: 'DEVELOPMENT SIMULATION: the photos are usable.', next_step: 'Proceeding to policy eligibility checks.', processing_ms: 12, created_at: '2026-11-05T00:00:00' },
    decision: { outcome: 'Approved', decided_by: 'system', checks: [{ id: 'CHK-01', name: 'Student is authenticated', result: 'PASS', reason: 'Signed-in student.' }], payable_amount: 6000, reason: 'All policy checks passed.', created_at: '2026-11-05T00:00:00',
      calculation: { payable: 6000, basis: 'reference repair cost', lines: [{ label: 'Assessed loss', amount: 6000, note: 'n' }, { label: 'Payable amount', amount: 6000, note: 'Final' }] } },
    settlement: { reference: 'SET-1', amount: 6000, status: 'Settled', simulated: true, settled_at: '2026-11-05T00:00:00' }, history: [],
  };

  it('displays the explainable AI report, the policy decision, the calculation and the simulated settlement', async () => {
    mockApi({ ...base('student'), 'GET /v2/claims/11': settled, 'GET /v2/ai/capabilities': { effective_mode: 'development_simulation', note: '' } });
    renderApp('/student/claims/11');
    expect(await screen.findByRole('heading', { name: 'AI damage verification report' })).toBeInTheDocument();
    expect(screen.getByText(/Development simulation\./)).toBeInTheDocument();
    expect(screen.getAllByText('Evidence Supported').length).toBeGreaterThan(0);
    expect(screen.getByText('No matching previous image found')).toBeInTheDocument();
    expect(screen.getByText(/Proceeding to policy eligibility checks/)).toBeInTheDocument();
    expect(screen.getByRole('img', { name: /Uploaded photo a.png/ })).toHaveAttribute('src', '/api/v2/claims/11/images/1/file');
    expect(screen.getByText(/Simulated settlement SET-1/)).toBeInTheDocument();
    expect(screen.getByRole('table', { name: 'Claim amount calculation' }) ?? screen.getByText('Payable amount')).toBeTruthy();
    expect(screen.getByText(/AI verification and the decision are separate steps/)).toBeInTheDocument();
  });

  it('lets staff approve or reject an exceptional review only with a reason', async () => {
    mockApi({ ...base('assessor'), 'GET /v2/claims/11': { ...settled, status: 'Exceptional Review Required', settlement: null, payable_amount: null, decision: { ...settled.decision, outcome: 'Exceptional Review Required', reason: 'Needs a human.' } }, 'GET /v2/ai/capabilities': { effective_mode: 'limited', note: '' }, 'POST /v2/claims/11/review': { id: 11 } });
    renderApp('/assessor/reviews/11');
    const u = userEvent.setup();
    const approve = await screen.findByRole('button', { name: /Approve and settle/ });
    expect(approve).toBeDisabled();
    await u.type(screen.getByLabelText(/Reason/), 'Photos checked by hand.');
    await u.click(approve);
    await waitFor(() => expect(calls.find(c => c.path === '/v2/claims/11/review')?.body).toEqual({ action: 'approve', reason: 'Photos checked by hand.' }));
  });
});

describe('administrator financial dashboard', () => {
  it('shows the finance figures, warns about deficits and runs the scenario calculator', async () => {
    const month = { month: '2026-10', premium_income: 1000, claim_payouts: 900, expected_claims: 900, operating_expenses: 150, ai_technology_expenses: 60, risk_reserve: 130, expected_surplus: -240, actual_surplus: -240, assumed_items: ['operating'] };
    mockApi({ ...base('admin'), 'GET /v2/finance/summary': { disclaimer: 'Sample assumptions for an academic prototype. These are NOT validated actuarial projections.', assumptions: { expected_loss_ratio_pct: 50, operating_pct: 15, ai_tech_pct: 6, reserve_pct: 13 }, months: [month],
      totals: { premium_income: 1000, claim_payouts: 900, expected_claims: 900, operating_expenses: 150, ai_technology_expenses: 60, risk_reserve: 130, expected_surplus: -240, actual_surplus: -240 }, warnings: ['2026-10: expected claims and expenses exceed premium income (deficit 240).'],
      distribution: [{ name: 'Expected claims', amount: 900 }, { name: 'Deficit', amount: 240 }], assumed_values_used: true, formula: 'Expected surplus = premium income - expected claims - operating expenses - AI/technology expenses - risk reserve',
      policy_breakdown: [{ category: 'Laptop', active_policies: 2, monthly_premium: 198, annualized_premium: 2376, premiums_collected: 500, claims_paid: 0, net: 500 }], counts: { active_policies: 8, insured_students: 4, insured_assets: 8, monthly_premium_collection: 700, annualized_premium_income: 8400, claims_submitted: 2, claims_approved: 1, claims_rejected: 1, claims_in_review: 0, total_payouts: 600 } },
    'POST /v2/finance/scenario': { premium_income: 79000, rows: [{ name: 'Premium income', amount: 79000 }, { name: 'Surplus', amount: 12000 }], surplus: 12000, margin_pct: 15.2, loss_ratio_pct: 50.6, break_even_loss_ratio_pct: 65.8, warnings: [], disclaimer: 'Sample assumptions.' } });
    renderApp('/admin/financials');
    expect(await screen.findByRole('heading', { name: 'Financial performance' })).toBeInTheDocument();
    expect(screen.getByText(/NOT validated actuarial projections/)).toBeInTheDocument();
    expect(screen.getByText(/expected claims and expenses exceed premium income \(deficit 240\)/)).toBeInTheDocument();
    expect(screen.getByRole('table', { name: 'Monthly financial performance' })).toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole('button', { name: 'Calculate' }));
    expect(await screen.findByText(/Break-even loss ratio 65.8%/)).toBeInTheDocument();
    expect(calls.find(c => c.path === '/v2/finance/scenario')?.body).toMatchObject({ students: 1000, avg_monthly_premium: 79, expected_claims: 40000 });
  });
});


describe('registration evidence review and the extended verification report', () => {
  const pending = { ...asset, evidence_status: 'Pending review', can_purchase: false, evidence: { status: 'Pending review', note: '', reviewed_at: null, missing_required: ['Back photograph'], has_invoice: true,
    counts: {}, can_purchase: false, can_add: true, reason: 'The registration evidence is waiting for an administrator\'s review. A policy can be bought once it is approved.',
    files: [{ id: 1, kind: 'front_photo', label: 'Front photograph', original_name: 'front.png', content_type: 'image/png', size_bytes: 10, width: 10, height: 10, uploaded_at: '2026-01-01T00:00:00', review_status: 'Pending', is_image: true, quality_issues: [], file_url: '/api/v2/assets/7/evidence/1/file' }] } };

  it('does not offer to insure an item until an administrator has approved its evidence', async () => {
    mockApi({ ...base('student'), 'GET /v2/categories': cats, 'GET /v2/assets': [pending] });
    renderApp('/student/assets');
    expect(await screen.findByText('Waiting for evidence approval')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Insure this asset' })).not.toBeInTheDocument();
    expect(screen.getAllByText('Pending review').length).toBeGreaterThan(0);
  });

  it('shows the evidence files and says what is still missing before approval is possible', async () => {
    mockApi({ ...base('student'), 'GET /v2/categories': cats, 'GET /v2/assets': [pending], 'GET /v2/assets/7/evidence': pending.evidence });
    renderApp('/student/assets');
    const u = userEvent.setup();
    await u.click(await screen.findByRole('button', { name: 'Evidence and details' }));
    expect(await screen.findByText(/cannot approve this registration until you add: Back photograph/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'front.png' })).toHaveAttribute('href', '/api/v2/assets/7/evidence/1/file');
    expect(screen.getByRole('button', { name: 'Remove front.png' })).toBeInTheDocument();
  });

  const claim = {
    id: 12, claim_number: 'CLM-2026-01012', status: 'Exceptional Review Required', asset_name: 'Acme X1', asset_category: 'Laptop', policy_number: 'SBC-1', claimant_name: 'Riya', incident_type: 'Accidental Damage',
    incident_date: '2026-11-01', damage_type: 'Broken screen', description: 'Screen cracked after a fall.', estimated_repair_cost: null, payable_amount: null, decision_reason: 'x', ai_outcome: 'Evidence Inconsistent / Suspicious',
    ai_workflow_outcome: 'Suspicious evidence - manual review', awaiting_staff_confirmation: false, images: [{ id: 1, original_name: 'a.png', size_bytes: 10, width: 10, height: 10 }], settlement: null, decision: null, history: [],
    report: { id: 2, run: 1, mode: 'onnx_model', is_simulated: false, model_info: {}, quality: { images: [{ image: 'a.png', usable: true, score: 90, issues: [] }], usable_count: 1, total_count: 1, average_score: 90, result: 'Good' },
      asset_identification: { status: 'Unable to verify', detected: null, confidence: null, match: 'Unable to verify', explanation: 'x' }, damage_detection: { status: 'Detected', detections: [{ damage_type: 'Broken screen', confidence: 0.82, box: null, source: 'model' }], explanation: 'x', method: 'model' },
      description_check: { result: 'Consistent', notes: [], method: 'rules' }, duplicate_check: { result: 'Matching earlier image found' }, evidence_completeness: { photos_uploaded: 1, supporting_documents: 0, complete: true },
      risk_indicators: [{ code: 'DUP-REG-EXACT', severity: 'high', text: 'a.png is byte-identical to this item\'s own registration photograph, so it cannot show new damage.' }],
      workflow_outcome: 'Suspicious evidence - manual review', outcome: 'Evidence Inconsistent / Suspicious', route: 'exceptional_review', explanation: 'See the risk indicators.', next_step: 'Referred to staff for manual review. This is not a finding of fraud.', processing_ms: 30, created_at: '2026-11-05T00:00:00',
      summary: { expected_device_present: { status: 'Unable to verify', detail: null }, visible_damage: { status: 'Detected', types: ['Broken screen'], top_confidence: 0.82 }, description_matches: 'Consistent',
        registered_device_match: { band: 'Weak or no feature agreement', score: 0.0, used_for_routing: true }, authenticity_flags: { high: 1, medium: 0, low: 0 },
        note: 'Detected damage describes what the software saw in the photographs. It does not establish that the claim is genuine.' },
      device_match: { status: 'Computed', band: 'Weak or no feature agreement', best_score: 0, method: 'ORB keypoint matching', conclusion: 'Few or no visible features agree with the registered photographs. This is not proof of a different item.', supporting_evidence: [],
        limitations: ['Thresholds are heuristic and have not been calibrated on labelled data for this deployment.'], registered_photos_used: ['front photograph'], pairs: [{ claim_image: 'a.png', reference: 'front photograph', good_matches: 4, inliers: 2, score: 0 }],
        serial_check: { status: 'Not checked', detail: 'No vision-language model is configured to read text in photographs.', method: null }, brand_model_check: { status: 'Not checked', detail: 'No vision-language model is configured to read text in photographs.', method: null } },
      authenticity: { images: [{ image: 'a.png', sha256: 'ab', width: 640, height: 480, megapixels: 0.31, format: 'PNG', exif: { present: false, camera: null, software: null, captured: null, gps_present: false, editing_software: false }, ela: { applicable: false, uneven: false, reason: 'n/a' }, notes: [] }],
        missing_exif_policy: 'Missing metadata is never treated as a risk indicator.', limitations: { exif: 'Camera metadata is often removed by messaging apps, so missing metadata is NOT a sign of fraud.' } } },
  };

  it('shows the four-way outcome, the verification summary, the device comparison and the authenticity limits', async () => {
    mockApi({ ...base('assessor'), 'GET /v2/claims/12': claim, 'GET /v2/ai/capabilities': { effective_mode: 'onnx_model', note: '' } });
    renderApp('/assessor/reviews/12');
    expect(await screen.findByRole('heading', { name: 'AI damage verification report' })).toBeInTheDocument();
    expect(screen.getAllByText('Suspicious evidence - manual review').length).toBeGreaterThan(0);
    expect(screen.getByRole('heading', { name: 'Verification summary' })).toBeInTheDocument();
    expect(screen.getByText(/does not establish that the claim is genuine/)).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Comparison with the registered photographs' })).toBeInTheDocument();
    expect(screen.getAllByText('Weak or no feature agreement').length).toBeGreaterThan(0);
    expect(screen.getByText(/byte-identical to this item's own registration photograph/)).toBeInTheDocument();
    expect(screen.getByText(/Missing metadata is never treated as a risk indicator/)).toBeInTheDocument();
  });

  it('tells the student that a person must confirm even when every automatic check passed', async () => {
    mockApi({ ...base('student'), 'GET /v2/claims/12': { ...claim, ai_workflow_outcome: 'Evidence appears consistent', awaiting_staff_confirmation: true,
      report: { ...claim.report, workflow_outcome: 'Evidence appears consistent', outcome: 'Evidence Supported', risk_indicators: [] } }, 'GET /v2/ai/capabilities': { effective_mode: 'onnx_model', note: '' } });
    renderApp('/student/claims/12');
    expect(await screen.findByText(/Waiting for a staff member to confirm/)).toBeInTheDocument();
    expect(screen.getByText(/Nothing is paid until a person confirms/)).toBeInTheDocument();
  });
});


describe('administrator evidence review and AI analytics', () => {
  const row = { id: 7, name: 'Acme X1', category: 'Laptop', owner: 'Riya Menon', purchase_price: 40000, created_at: '2026-11-01T00:00:00', evidence_status: 'Pending review', files: 3, missing_required: [], has_invoice: true, flags: { high: 1, medium: 0, low: 2 }, insured: false };
  const file = (id: number, kind: string, label: string, flags: { code: string; severity: string; text: string }[] = []) => ({ id, kind, label, original_name: `${kind}.png`, content_type: 'image/png', size_bytes: 10, width: 640, height: 480, uploaded_at: '2026-11-01T00:00:00',
    review_status: 'Pending', is_image: true, quality_issues: [], file_url: `/api/v2/assets/7/evidence/${id}/file`, sha256: 'abcdef0123456789abcdef', flags, exif: {} });
  const detail = { ...asset, evidence_status: 'Pending review', can_purchase: false, owner_name: 'Riya Menon', review_history: [], evidence: { status: 'Pending review', note: '', reviewed_at: null, missing_required: [], has_invoice: true, counts: {}, can_purchase: false, can_add: true, reason: '',
    files: [file(1, 'front_photo', 'Front photograph', [{ code: 'REG-DUP-EXACT', severity: 'high', text: 'This file is byte-identical to a file registered for the registration of Other Phone (a different student).' }]), file(2, 'back_photo', 'Back photograph'), file(3, 'invoice', 'Purchase invoice or receipt')] } };

  it('lists registrations with their observations and a link to review each one', async () => {
    mockApi({ ...base('admin'), 'GET /v2/admin/evidence-reviews': [row] });
    renderApp('/admin/evidence');
    expect(await screen.findByRole('heading', { name: 'Registration evidence review' })).toBeInTheDocument();
    expect(await screen.findByText('1 high, 0 medium, 2 low')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Review/ })).toHaveAttribute('href', '/admin/evidence/7');
  });

  it('shows the automatic observations and sends an approval, requiring a note for any other decision', async () => {
    mockApi({ ...base('admin'), 'GET /v2/admin/assets/7/evidence-review': detail, 'POST /v2/admin/assets/7/evidence-review': { id: 7 } });
    renderApp('/admin/evidence/7');
    const u = userEvent.setup();
    expect(await screen.findByText(/byte-identical to a file registered for the registration of Other Phone/)).toBeInTheDocument();
    expect(screen.getByText(/Missing camera data is normal and is not listed as a concern/)).toBeInTheDocument();
    const save = screen.getByRole('button', { name: 'Save decision' });
    expect(save).toBeEnabled();  // approving with an invoice needs no note
    await u.selectOptions(screen.getByLabelText('Decision'), 'reject');
    expect(screen.getByRole('button', { name: 'Save decision' })).toBeDisabled();  // rejecting needs a reason the student will see
    await u.type(screen.getByLabelText(/Note \(shown to the student, required\)/), 'The invoice is for a different product.');
    expect(screen.getByRole('button', { name: 'Save decision' })).toBeEnabled();
    await u.click(screen.getByRole('button', { name: 'Save decision' }));
    await waitFor(() => expect(calls.find(c => c.method === 'POST' && c.path === '/v2/admin/assets/7/evidence-review')?.body).toEqual({ decision: 'reject', note: 'The invoice is for a different product.', accept_missing_invoice: false }));
  });

  const model = { available: false, state: 'Not installed. No damage detector has been trained or supplied, so damage cannot be detected automatically.', file: 'damage_model.onnx', sha256: null, classes: [], input_size: null, file_modified: null,
    training_metadata: null, evaluation_present: false, evaluation_matches_model: false, evaluation_note: '' };
  const analytics = { reports: 0, images_analyzed: 0, successful: 0, uncertain: 0, inconsistent: 0, avg_processing_ms: 0, damage_distribution_detected: {}, damage_distribution_declared: {}, modes: {}, simulated_reports: 0, model_metrics: null, model_metrics_note: 'Not measured',
    damage_model: model, evaluation: null, workflow_outcomes: {}, workflow_outcomes_note: 'Counts reports from real verification runs only.',
    device_matching: { reports_compared: 0, bands: {}, average_best_score: null, scores_measured: 0, serial_check: {}, brand_model_check: {}, calibrated: false, note: 'Thresholds are heuristic and have not been calibrated on labelled pairs.' },
    authenticity_indicators: {}, manual_review: { waiting_for_staff: 0, decided_by_staff: {}, average_hours_to_decision: null, decisions_with_timing: 0, sent_to_manual_review: 0, approved_after_suspicious_outcome: 0, rejected_after_consistent_outcome: 0, auto_approval_setting: 'off' },
    evidence_review: { 'Pending review': 1, 'More evidence requested': 0, Approved: 4, Rejected: 0 }, capabilities: { effective_mode: 'limited', note: '', asset_model: { file: 'yolo11n.onnx', sha256: 'abc' }, damage_model: null, vision_language_model: false, auto_approval: 'off' } };

  it('says "Not measured" instead of inventing performance numbers when no model or evaluation exists', async () => {
    mockApi({ ...base('admin'), 'GET /v2/ai/analytics': analytics });
    renderApp('/admin/ai');
    expect(await screen.findByText(/No damage detector has been trained or supplied/)).toBeInTheDocument();
    expect(screen.getByText(/Not measured\. No labelled evaluation has been run/)).toBeInTheDocument();
    expect(screen.getByText('No model file loaded')).toBeInTheDocument();
    expect(screen.getByText(/Not available \(no comparison has run\)/)).toBeInTheDocument();
    expect(screen.getByText('Off: a person confirms every claim before any payout')).toBeInTheDocument();
  });

  it('shows measured per-class metrics, marks unmeasured ones, and warns when the evaluation belongs to another model', async () => {
    const ev = { model: 'damage_model.onnx', model_sha256: 'f'.repeat(16), split: 'val', images: 40, iou_threshold: 0.5, confidence_threshold: 0.35, generated_at: '2026-11-08T00:00:00', dataset: { fingerprint: 'dd' },
      per_class: { 'Cracked screen': { precision: 0.9, recall: 0.8, f1: 0.847, ap50: 0.88, ap50_95: null, instances: 20 }, 'Broken hinge': { precision: null, recall: null, f1: null, ap50: null, ap50_95: null, instances: 0 } },
      overall: { precision: 0.9, recall: 0.8, f1: 0.847, map50: 0.88, map50_95: null }, confusion_matrix: null, unavailable_metrics: ['mAP@0.5:0.95', 'confusion matrix'], note: null };
    mockApi({ ...base('admin'), 'GET /v2/ai/analytics': { ...analytics, damage_model: { ...model, available: true, state: 'Installed and loaded', sha256: 'a'.repeat(64), evaluation_present: true, evaluation_matches_model: false, evaluation_note: 'different model' }, evaluation: ev } });
    renderApp('/admin/ai');
    expect(await screen.findByText(/measured on a different model file than the one installed/)).toBeInTheDocument();
    expect(screen.getAllByText('0.900').length).toBe(2);  // the class row and the overall row
    expect(screen.getAllByText('Not measured').length).toBeGreaterThan(3);  // AP@0.5:0.95 and the class with no instances are never shown as zero
    expect(screen.getByText(/Unavailable in this file: mAP@0.5:0.95, confusion matrix/)).toBeInTheDocument();
    expect(screen.getByText('a'.repeat(64))).toBeInTheDocument();
  });
});
