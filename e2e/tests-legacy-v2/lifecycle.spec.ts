import { expect, test, type Page } from '@playwright/test';
import { PNG, isoDaysAgo, loginAs, logout, selectByText, tab, watchBrowser } from './helpers';

/**
 * One claim travels through all three portals, in order:
 * student registers + submits -> assessor assesses -> administrator approves reserve and payment -> student sees the outcome.
 * The claim is for the seeded Dell laptop on a Campus Plus policy (deductible 1,000); a screen repair costs 4,000 + 500.
 * Expected result: 4,500.00 - 1,000.00 = 3,500.00.
 */
test.describe.serial('claim lifecycle across student, assessor and administrator', () => {
  let claimPath = '';
  let claimNo = '';
  const open = (page: Page, role: string) => page.goto(claimPath.replace('/student/', `/${role}/`));

  test('student: view policies and policy details', async ({ page }) => {
    const w = watchBrowser(page);
    await loginAs(page, 'student');
    await page.getByRole('link', { name: 'Policy Centre' }).click();
    await expect(page.getByRole('heading', { level: 1, name: 'Policy Centre' })).toBeVisible();
    const row = page.getByRole('row', { name: /Campus Plus/ }).filter({ hasText: 'Active' });
    await expect(row).toHaveCount(1);
    await row.getByRole('link').click();
    await expect(page.getByRole('heading', { level: 1 })).toContainText('Policy SBC-');
    await expect(page.getByText('Coverage limits, deductible and conditions')).toBeVisible();
    await expect(page.getByRole('region', { name: 'Policy exclusions' })).toContainText('Wear and tear');
    await expect(page.getByRole('region', { name: 'Required documents' })).toBeVisible();
    await expect(page.getByText('7 day(s) from cover start')).toBeVisible();
    await tab(page, 'Insured assets').click();
    await expect(page.getByRole('cell', { name: 'Dell Inspiron 15' })).toBeVisible();
    await tab(page, 'Versions').click();
    await expect(page.getByRole('row', { name: /v2/ })).toBeVisible(); // seeded mid-term version
    w.assertClean();
  });

  test('student: register a claim, add damage item and evidence, submit', async ({ page }) => {
    const w = watchBrowser(page);
    await loginAs(page, 'student');
    await page.getByRole('link', { name: 'New claim' }).click();
    await selectByText(page.getByLabel('Policy'), /Campus Plus/);
    await selectByText(page.getByLabel('Affected item'), /Dell Inspiron 15/);
    await page.getByLabel('Incident date').fill(isoDaysAgo(12));
    await page.getByLabel(/^What happened/).selectOption('Accidental Damage');
    await page.getByLabel('Where did it happen').fill('Hostel room');
    await page.getByLabel('Describe the incident').fill('Laptop slipped off the desk; the screen is cracked across the lower half.');
    await page.getByRole('button', { name: 'Check eligibility first' }).click();
    await expect(page.getByRole('list', { name: 'Eligibility results' })).toContainText('POL-001');
    await page.getByRole('button', { name: 'Create draft claim' }).click();
    await expect(page.getByRole('heading', { level: 1 })).toContainText(/Claim CLM-/);
    claimPath = new URL(page.url()).pathname;
    claimNo = (await page.getByRole('heading', { level: 1 }).innerText()).match(/CLM-\d{4}-\d{5}/)![0];
    await expect(page.getByRole('heading', { level: 1 })).toContainText('Draft');

    await tab(page, 'Damage items').click();
    await page.getByLabel('Damaged part').fill('Screen');
    await page.getByLabel('Type of damage').selectOption('Cracked screen');
    await page.getByLabel('Severity').selectOption('Moderate');
    await page.getByRole('button', { name: 'Add item' }).click();
    const itemsTable = page.getByRole('region', { name: 'Damage items' });
    await expect(itemsTable).toContainText('Student Declared');

    await tab(page, 'Evidence').click();
    await page.getByLabel('Document type').selectOption('damage_photo');
    await page.getByLabel('File').setInputFiles({ name: 'cracked-screen.png', mimeType: 'image/png', buffer: PNG });
    await page.getByRole('button', { name: 'Upload' }).click();
    await expect(page.getByRole('region', { name: 'Uploaded evidence' })).toContainText('cracked-screen.png');

    await tab(page, 'Overview').click();
    await page.getByRole('button', { name: 'Submit claim for assessment' }).click();
    await expect(page.getByRole('heading', { level: 1 })).toContainText('Submitted');
    // Status tracking + assessment information are visible to the student
    await tab(page, 'Assessment').click();
    await expect(page.getByText('Recommendation (policy version')).toBeVisible();
    await expect(page.getByRole('region', { name: 'Rules applied' })).toBeVisible();
    await tab(page, 'History').click();
    await expect(page.getByRole('region', { name: 'Claim status history' })).toContainText('Submitted');
    w.assertClean();
  });

  test('student: the claim is read-only after submission', async ({ page }) => {
    await loginAs(page, 'student');
    await page.goto(claimPath);
    await tab(page, 'Damage items').click();
    await expect(page.getByRole('button', { name: 'Add item' })).toHaveCount(0);
    await tab(page, 'Overview').click();
    await expect(page.getByRole('button', { name: /Submit claim|Re-submit/ })).toHaveCount(0);
    // The API refuses it as well
    const r = await page.request.put(`/api/claims/${claimPath.split('/').pop()}`, { data: { description: 'tamper' } });
    expect([400, 403]).toContain(r.status());
  });

  test('another student cannot see the claim', async ({ page }) => {
    await loginAs(page, 'student2');
    const id = claimPath.split('/').pop();
    expect((await page.request.get(`/api/claims/${id}`)).status()).toBe(404);
    await page.goto(claimPath);
    await expect(page.getByRole('alert')).toContainText('Claim not found');
  });

  test('assessor: take the claim, review evidence, verify AI output, complete the assessment', async ({ page }) => {
    const w = watchBrowser(page);
    page.on('dialog', d => void d.accept());
    await loginAs(page, 'assessor');
    await page.getByRole('link', { name: 'Claims', exact: true }).click();
    await tab(page, 'Unassigned').click();
    await page.getByRole('link', { name: claimNo }).click();
    await expect(page.getByRole('heading', { level: 1 })).toContainText(claimNo);

    // evidence review
    await tab(page, 'Evidence').click();
    await expect(page.getByRole('region', { name: 'Uploaded evidence' })).toContainText('damage_photo');
    await expect(page.getByRole('link', { name: /Open cracked-screen.png/ })).toHaveAttribute('href', /\/api\/claims\/\d+\/evidence\/\d+\/file/);

    // start assessment
    await tab(page, 'Overview').click();
    await page.getByRole('button', { name: 'Move to: Under Assessment' }).click();
    await expect(page.getByRole('heading', { level: 1 })).toContainText('Under Assessment');

    // AI suggestion: honestly labelled, never applied automatically
    await tab(page, 'Damage items').click();
    await expect(page.getByRole('region', { name: 'Damage items' })).toContainText('Student Declared');
    await page.getByRole('button', { name: 'Get AI assessment suggestions' }).click();
    const ai = page.getByRole('region', { name: /assessment$/ });
    await expect(ai).toContainText('Demo fallback - NOT an AI result');
    await expect(ai).toContainText('Unverified');
    await page.getByRole('button', { name: /Add suggested item Screen for verification/ }).click();
    await expect(page.getByRole('region', { name: 'Damage items' })).toContainText('AI Suggested');

    // the student's unpriced duplicate is removed; the AI line is priced from the catalogue
    await page.getByRole('button', { name: 'Delete Screen' }).first().click();
    await expect(page.getByRole('region', { name: 'Damage items' }).getByRole('row')).toHaveCount(2); // header + 1 item

    // completing is refused while the AI item is unverified
    await tab(page, 'Overview').click();
    await page.getByRole('button', { name: 'Move to: Assessment Completed' }).click();
    await expect(page.getByRole('alert').filter({ hasText: /pending/i }).first()).toBeVisible();
    await expect(page.getByRole('heading', { level: 1 })).toContainText('Under Assessment');

    // human verification
    await tab(page, 'Damage items').click();
    await page.getByRole('button', { name: 'Verify Screen' }).click();
    await expect(page.getByRole('region', { name: 'Damage items' })).toContainText('Human Verified');

    // rules trace + calculation
    await tab(page, 'Assessment & rules').click();
    await page.getByRole('button', { name: 'Re-run rules and calculation' }).click();
    const trace = page.getByRole('region', { name: 'Rule execution trace' });
    await expect(trace).toContainText('POL-001');
    await expect(trace).toContainText('POL-013');
    const calc = page.getByRole('region', { name: 'Itemised calculation lines' });
    await expect(calc).toContainText('₹4,500.00');
    await expect(calc).toContainText('-₹1,000.00'); // deductible line
    await expect(page.getByText('Estimated payable: ₹3,500.00')).toBeVisible();

    // complete and recommend
    await tab(page, 'Overview').click();
    await page.getByRole('button', { name: 'Move to: Assessment Completed' }).click();
    await expect(page.getByRole('heading', { level: 1 })).toContainText('Assessment Completed');
    await page.getByLabel(/Reason \(required/).fill('Cracked screen is covered; repair priced from the catalogue.');
    await page.getByRole('button', { name: 'Move to: Approved for Review' }).click();
    await expect(page.getByRole('heading', { level: 1 })).toContainText('Approved for Review');

    // reserve recommendation
    await tab(page, 'Reserves & payments').click();
    await page.getByRole('button', { name: 'Recommend the estimated payable' }).click();
    await expect(page.getByText('Reserve recommendation saved')).toBeVisible();
    await expect(page.getByRole('region', { name: 'Reserve' }).or(page.getByText('Recommended reserve').locator('..')).first()).toContainText('₹3,500.00');
    // audit trail
    await tab(page, 'History').click();
    await expect(page.getByRole('region', { name: 'Claim audit history' })).toContainText('damage item verified');
    w.assertClean();
  });

  test('assessor cannot approve a reserve or a payment', async ({ page }) => {
    await loginAs(page, 'assessor');
    await open(page, 'assessor');
    await tab(page, 'Reserves & payments').click();
    await expect(page.getByRole('button', { name: 'Approve reserve' })).toHaveCount(0);
    const id = claimPath.split('/').pop();
    // missing CSRF -> 403, and even with a valid session the role check applies to the endpoint
    const me = await (await page.request.get('/api/auth/me')).json();
    const r = await page.request.post(`/api/claims/${id}/reserve/approve`, { data: { amount: 3500 }, headers: { 'X-CSRF-Token': me.csrf_token } });
    expect(r.status()).toBe(403);
  });

  test('administrator: approve the reserve; assessor requests a payment; duplicate is blocked; admin approves and settles (simulated)', async ({ browser }) => {
    const wAdmin = await browser.newContext();
    const wAss = await browser.newContext();
    const admin = await wAdmin.newPage();
    const ass = await wAss.newPage();
    const w = watchBrowser(admin);
    await loginAs(admin, 'admin');
    await open(admin, 'admin');
    await tab(admin, 'Reserves & payments').click();
    await admin.getByLabel('Amount (INR)').fill('3500');
    await admin.getByRole('button', { name: 'Approve reserve' }).click();
    await expect(admin.getByText('Reserve approved')).toBeVisible();
    await expect(admin.getByText('Approved reserve').locator('xpath=following-sibling::dd[1]')).toContainText('₹3,500.00');

    await loginAs(ass, 'assessor');
    await open(ass, 'assessor');
    await tab(ass, 'Reserves & payments').click();
    await ass.getByLabel('Amount (INR)', { exact: false }).last().fill('3500');
    await ass.getByLabel('Payee name').fill('Aarav Sharma');
    await ass.getByRole('button', { name: 'Request payment' }).click();
    await expect(ass.getByText('Payment requested (simulated)')).toBeVisible();
    // a second identical request must not create a second payment
    await ass.getByLabel('Amount (INR)').last().fill('3500');
    await ass.getByLabel('Payee name').fill('Aarav Sharma');
    await ass.getByRole('button', { name: 'Request payment' }).click();
    await expect(ass.getByRole('alert').filter({ hasText: /Duplicate payment|exceeds the remaining/ }).first()).toBeVisible();
    await expect(ass.getByRole('region', { name: 'Payments (simulated)' }).getByRole('row')).toHaveCount(2); // header + one payment

    await admin.reload();
    await tab(admin, 'Reserves & payments').click();
    await admin.getByRole('button', { name: 'Approve', exact: true }).click();
    await expect(admin.getByText('Payment approve done')).toBeVisible();
    await admin.getByRole('button', { name: 'Simulate: paid' }).click();
    await expect(admin.getByText('Payment simulate settlement done')).toBeVisible();
    await expect(admin.getByRole('region', { name: 'Payments (simulated)' })).toContainText('Paid');
    await expect(admin.getByText(/SIMULATED payment workflow/).first()).toBeVisible();
    w.assertClean();
    await wAdmin.close(); await wAss.close();
  });

  test('administrator: payments and reserves overview, claim monitoring and audit log reflect the claim', async ({ page }) => {
    const w = watchBrowser(page);
    await loginAs(page, 'admin');
    await page.getByRole('link', { name: 'Reserves & payments' }).click();
    await expect(page.getByRole('region', { name: 'Claim reserves' })).toContainText(claimNo);
    await tab(page, 'Payments').click();
    await expect(page.getByRole('region', { name: 'All payments (simulated)' })).toContainText('Paid');
    await page.getByRole('link', { name: 'Claim monitoring' }).click();
    await expect(page.getByRole('link', { name: claimNo })).toBeVisible();
    await page.getByRole('link', { name: 'Audit logs' }).click();
    await page.getByLabel('Entity type').selectOption('payment');
    await expect(page.getByRole('region', { name: 'Audit log' })).toContainText('payment');
    w.assertClean();
  });

  test('student: sees the final assessment and the simulated payment', async ({ page }) => {
    await loginAs(page, 'student');
    await page.goto(claimPath);
    await expect(page.getByRole('heading', { level: 1 })).toContainText('Approved for Review');
    await tab(page, 'Assessment').click();
    await expect(page.getByText('Estimated payable: ₹3,500.00')).toBeVisible();
    await expect(page.getByRole('region', { name: 'Itemised calculation lines' })).toContainText('₹1,000.00');
    await tab(page, 'Payments').click();
    await expect(page.getByRole('region', { name: 'Payments (simulated)' })).toContainText('Paid');
    // students never get reserve controls or provider metadata
    await expect(page.getByText('Recommended reserve')).toHaveCount(0);
    await logout(page);
  });
});
