import { expect, test } from '@playwright/test';
import { isoDaysAgo, loginAs, selectByText, tab, toast, watchBrowser } from './helpers';

const plusDays = (n: number) => new Date(Date.now() + n * 86400000).toISOString().slice(0, 10);

test.describe.serial('administrator workflows', () => {
  test('dashboard shows claim, reserve and security overview', async ({ page }) => {
    const w = watchBrowser(page);
    await loginAs(page, 'admin');
    await expect(page.getByText('Unassigned open claims')).toBeVisible();
    await expect(page.getByRole('region', { name: 'Claims by status' })).toBeVisible();
    await expect(page.getByText('Active sessions')).toBeVisible();
    w.assertClean();
  });

  test('policy: create, activate, edit (new version), cancel', async ({ page }) => {
    const w = watchBrowser(page);
    await loginAs(page, 'admin');
    await page.getByRole('link', { name: 'Policies' }).click();
    await page.getByRole('link', { name: 'Create policy' }).click();
    await selectByText(page.getByLabel('Policy holder'), /Meera/);
    await selectByText(page.getByLabel('Coverage plan'), /Campus Plus/);
    await page.getByLabel('Start date').fill(isoDaysAgo(1));
    await page.getByLabel('Expiry date').fill(plusDays(300));
    await page.getByLabel(/HP Pavilion 14/).check();
    await page.getByRole('button', { name: 'Create draft policy' }).click();
    await expect(page.getByRole('heading', { level: 1 })).toContainText('Draft');
    const policyUrl = page.url();

    await page.getByRole('button', { name: 'Activate policy' }).click();
    await expect(page.getByRole('heading', { level: 1 })).toContainText('Active');

    // editing an active policy creates a new version and cannot be back-dated
    await tab(page, 'Edit / new version').click();
    await page.getByLabel('Expiry date').fill(plusDays(330));
    await page.getByLabel('New version effective from').fill(isoDaysAgo(3));
    await page.getByRole('button', { name: 'Save', exact: true }).click();
    await expect(page.getByRole('alert').filter({ hasText: /back-dated/ })).toBeVisible();
    await page.getByLabel('New version effective from').fill('');
    await page.getByLabel('Reason for change').fill('Extended cover period');
    await page.getByRole('button', { name: 'Save', exact: true }).click();
    await expect(page.getByText('Saved as a new policy version')).toBeVisible();
    await tab(page, 'Versions').click();
    const versions = page.getByRole('region', { name: 'Policy versions' });
    await expect(versions).toContainText('v1');
    await expect(versions).toContainText('v2');
    await expect(versions).toContainText('Extended cover period');

    // cancellation needs a reason
    await tab(page, 'Overview & lifecycle').click();
    await page.getByRole('button', { name: 'Cancel policy' }).click();
    await expect(page.getByRole('alert').filter({ hasText: 'cancellation reason is required' })).toBeVisible();
    await page.getByLabel('Reason (required to cancel)').fill('Policyholder request');
    await page.getByRole('button', { name: 'Cancel policy' }).click();
    await expect(page.getByRole('heading', { level: 1 })).toContainText('Cancelled');
    await tab(page, 'Edit / new version').click();
    await expect(page.getByText('A Cancelled policy cannot be edited.')).toBeVisible();
    expect(policyUrl).toContain('/admin/policies/');
    w.assertClean();
  });

  test('policy: draft needs an asset before activation', async ({ page }) => {
    await loginAs(page, 'admin');
    await page.goto('/admin/policies/new');
    await selectByText(page.getByLabel('Policy holder'), /Aarav/);
    await selectByText(page.getByLabel('Coverage plan'), /Campus Basic/);
    await page.getByLabel('Expiry date').fill(plusDays(200));
    await page.getByRole('button', { name: 'Create draft policy' }).click();
    await page.getByRole('button', { name: 'Activate policy' }).click();
    await expect(page.getByRole('alert').filter({ hasText: /at least one insured asset/ })).toBeVisible();
    await expect(page.getByRole('heading', { level: 1 })).toContainText('Draft');
  });

  test('plan: create with an exclusion, then edit', async ({ page }) => {
    const w = watchBrowser(page);
    await loginAs(page, 'admin');
    await page.getByRole('link', { name: 'Plans & exclusions' }).click();
    await page.getByRole('link', { name: 'Create plan' }).click();
    await page.getByRole('button', { name: 'Create plan' }).click(); // empty form -> client validation
    await expect(page.getByText('Enter a plan name')).toBeVisible();
    await expect(page.getByText('Select at least one covered peril')).toBeVisible();
    await page.getByLabel('Plan name').fill('E2E Plan');
    await page.getByLabel('Theft', { exact: true }).first().check();
    await page.getByLabel('Overall limit (INR)').fill('10000');
    await page.getByLabel('Deductible (INR)').fill('500');
    await page.getByRole('button', { name: 'Add exclusion' }).click();
    await page.getByRole('group', { name: 'Exclusion 1' }).getByLabel('Code').fill('EXC-E2E');
    await page.getByRole('group', { name: 'Exclusion 1' }).getByLabel('Title').fill('E2E exclusion');
    await page.getByRole('button', { name: 'Create plan' }).click();
    await expect(page.getByText('Plan created')).toBeVisible();
    await expect(page.getByRole('heading', { level: 1 })).toContainText('Edit plan: E2E Plan');
    await page.getByLabel('Deductible (INR)').fill('750');
    await page.getByRole('button', { name: 'Save plan' }).click();
    await expect(page.getByText(/Plan saved/)).toBeVisible();
    await page.getByRole('link', { name: 'Plans & exclusions' }).click();
    await expect(page.getByRole('row', { name: /E2E Plan/ })).toContainText('₹750.00');
    w.assertClean();
  });

  test('users: create, validate, edit, disable, reset password, enable', async ({ page, browser }) => {
    const w = watchBrowser(page);
    await loginAs(page, 'admin');
    await page.getByRole('link', { name: 'Users', exact: true }).click();
    await page.getByRole('button', { name: 'Create user' }).click();
    const dlg = page.getByRole('dialog', { name: 'Create user' });
    await dlg.getByRole('button', { name: 'Create' }).click();
    await expect(dlg.getByText(/3-50 characters/)).toBeVisible();
    await expect(dlg.getByText(/at least 12 characters/)).toBeVisible();
    await dlg.getByLabel('Username').fill('e2e.assessor');
    await dlg.getByLabel('Full name').fill('E2E Assessor');
    await dlg.getByLabel('Role').selectOption('assessor');
    await dlg.getByLabel('Initial password').fill('Initial-Pass-2026');
    await dlg.getByRole('button', { name: 'Create' }).click();
    await expect(page.getByText('User created')).toBeVisible();
    const row = page.getByRole('row', { name: /e2e.assessor/ });
    await expect(row).toContainText('assessor');

    // the new account can sign in
    const ctx = await browser.newContext();
    const other = await ctx.newPage();
    const ok = await other.request.post('/api/auth/login', { data: { username: 'e2e.assessor', password: 'Initial-Pass-2026' } });
    expect(ok.status()).toBe(200);

    await row.getByRole('button', { name: 'Edit e2e.assessor' }).click();
    await page.getByRole('dialog').getByLabel('Full name').fill('E2E Assessor Renamed');
    await page.getByRole('dialog').getByRole('button', { name: 'Save' }).click();
    await expect(page.getByRole('cell', { name: 'E2E Assessor Renamed' })).toBeVisible();

    await page.getByRole('button', { name: 'Disable e2e.assessor' }).click();
    await expect(page.getByRole('row', { name: /e2e.assessor/ })).toContainText('Disabled');
    expect((await other.request.get('/api/auth/me')).status()).toBe(401); // existing session was revoked
    expect((await other.request.post('/api/auth/login', { data: { username: 'e2e.assessor', password: 'Initial-Pass-2026' } })).status()).toBe(401);

    await page.getByRole('button', { name: 'Enable e2e.assessor' }).click();
    await page.getByRole('button', { name: 'Reset password for e2e.assessor' }).click();
    await page.getByRole('dialog').getByLabel('New password').fill('short');
    await page.getByRole('dialog').getByRole('button', { name: 'Reset password' }).click();
    await expect(page.getByRole('dialog').getByText('Use at least 12 characters')).toBeVisible();
    await page.getByRole('dialog').getByLabel('New password').fill('Another-Pass-2027');
    await page.getByRole('dialog').getByRole('button', { name: 'Reset password' }).click();
    await expect(page.getByText(/Password reset/)).toBeVisible();
    expect((await other.request.post('/api/auth/login', { data: { username: 'e2e.assessor', password: 'Initial-Pass-2026' } })).status()).toBe(401);
    expect((await other.request.post('/api/auth/login', { data: { username: 'e2e.assessor', password: 'Another-Pass-2027' } })).status()).toBe(200);
    await ctx.close();
    w.assertClean();
  });

  test('administrators cannot disable themselves', async ({ page }) => {
    await loginAs(page, 'admin');
    await page.goto('/admin/users');
    await page.getByRole('button', { name: 'Disable admin' }).click();
    await expect(page.getByRole('alert').filter({ hasText: /cannot demote or disable their own account/ })).toBeVisible();
  });

  test('audit logs list the administrator actions', async ({ page }) => {
    await loginAs(page, 'admin');
    await page.getByRole('link', { name: 'Audit logs' }).click();
    const log = page.getByRole('region', { name: 'Audit log' });
    await expect(log).toContainText('user created');
    await page.getByLabel('Entity type').selectOption('policy');
    await expect(log).toContainText('policy');
    await expect(log).not.toContainText('user created');
  });

  test('system settings: banner shows to all users and payments can be disabled', async ({ page }) => {
    await loginAs(page, 'admin');
    await page.getByRole('link', { name: 'System' }).click();
    await expect(page.getByText('SIMULATED (no gateway integrated)')).toBeVisible();
    await expect(page.getByText(/API key is never sent to the browser/)).toBeVisible();
    await page.getByLabel(/Maintenance banner/).fill('Planned maintenance tonight');
    await page.getByRole('button', { name: 'Save settings' }).click();
    await expect(toast(page, /Settings saved/)).toBeVisible(); // .first(): a second toast may still be on screen
    await page.getByRole('link', { name: 'Dashboard' }).click();
    await expect(page.getByText('Planned maintenance tonight')).toBeVisible();
    await page.getByRole('link', { name: 'System' }).click();
    await page.getByRole('button', { name: 'Test AI connection' }).click();
    await expect(page.getByRole('status').filter({ hasText: /OK|Failed/ })).toBeVisible();
    await page.getByLabel(/Maintenance banner/).fill('');
    await page.getByRole('button', { name: 'Save settings' }).click();
    await expect(toast(page, /Settings saved/)).toBeVisible(); // .first(): a second toast may still be on screen
  });
});

test.describe.serial('assessor repair-cost entry', () => {
  test('assessor takes a submitted claim and enters repair costs manually', async ({ page }) => {
    const w = watchBrowser(page);
    await loginAs(page, 'assessor');
    await page.getByRole('link', { name: 'Claims', exact: true }).click();
    await tab(page, 'All claims').click();
    await page.getByRole('link', { name: /CLM-\d{4}-00003/ }).click();
    await page.getByRole('button', { name: 'Move to: Under Assessment' }).click();
    await expect(page.getByRole('heading', { level: 1 })).toContainText('Under Assessment');
    await tab(page, 'Damage items').click();
    await page.getByRole('button', { name: 'Add damage item' }).first().click();
    const dlg = page.getByRole('dialog');
    await dlg.getByRole('button', { name: 'Save' }).click(); // validation
    await expect(dlg.getByText('Enter the component')).toBeVisible();
    await dlg.getByLabel('Component').fill('Motherboard');
    await dlg.getByLabel('Damage type').selectOption('Liquid damage');
    await dlg.getByLabel('Repair action').selectOption('Repair');
    await dlg.getByLabel('Parts cost (INR)').fill('9000');
    await dlg.getByLabel('Labour cost (INR)').fill('1500');
    await dlg.getByRole('button', { name: 'Save' }).click();
    const items = page.getByRole('region', { name: 'Damage items' });
    await expect(items).toContainText('₹9,000.00');
    await expect(items).toContainText('Human Verified');
    await page.getByRole('button', { name: 'Edit Motherboard' }).click();
    await page.getByRole('dialog').getByLabel('Parts cost (INR)').fill('9500');
    await page.getByRole('dialog').getByRole('button', { name: 'Save' }).click();
    await expect(items).toContainText('₹9,500.00');
    w.assertClean();
  });
});
