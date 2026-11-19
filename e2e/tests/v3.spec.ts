import { expect, test } from '@playwright/test';
import { makePng, watchBrowser } from './helpers';

/**
 * Current v4 journey. It deliberately checks the evidence-approval gate and
 * the human-confirmation payout gate. The development AI mode is a workflow
 * simulation, not a trained damage detector.
 */
test.describe.serial('v4 student, evidence-review and claim journey', () => {
  const username = `e2e${Date.now() % 1000000}`;
  const password = 'Str0ng!pass-123';

  test('registration requires admin evidence approval before purchase; claims wait for staff confirmation', async ({ page }) => {
    const w = watchBrowser(page);

    // Create a student and register a laptop with the required front/back photos.
    await page.goto('/register');
    await page.getByLabel('Full name').fill('E2E Student');
    await page.getByLabel('Username').fill(username);
    await page.getByLabel('Email').fill(`${username}@example.edu`);
    await page.getByLabel('Password', { exact: true }).fill(password);
    await page.getByLabel('Repeat password').fill(password);
    await page.getByRole('button', { name: 'Create account' }).click();
    await expect(page).toHaveURL(/\/student$/);
    await page.getByRole('link', { name: 'My assets' }).click();
    await page.getByRole('button', { name: 'Add an asset' }).click();
    await page.getByLabel('Category').selectOption({ label: 'Laptop' });
    await page.getByLabel('Brand').fill('Acme');
    await page.getByLabel('Model').fill('Book 14');
    await page.getByLabel('Purchase price (INR)').fill('42000');
    await page.getByLabel('Purchase date').fill('2026-10-10');
    await page.getByLabel('Serial number').fill(`SN-${username}`);
    await page.getByLabel('Front photograph').setInputFiles({ name: 'front.png', mimeType: 'image/png', buffer: makePng(11) });
    await page.getByLabel('Back photograph').setInputFiles({ name: 'back.png', mimeType: 'image/png', buffer: makePng(12) });
    await page.getByLabel('Invoice or purchase receipt').setInputFiles({ name: 'invoice.png', mimeType: 'image/png', buffer: makePng(13) });
    await page.getByRole('button', { name: 'Check eligibility and register' }).click();
    await expect(page.getByText('Waiting for evidence approval')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Insure this asset' })).toHaveCount(0);

    // Admin reviews and approves the registration evidence.
    await page.context().clearCookies();
    await page.goto('/login');
    await page.getByLabel('Username').fill('admin');
    await page.getByLabel('Password').fill('admin123');
    await page.getByRole('button', { name: 'Sign in' }).click();
    await expect(page).toHaveURL(/\/admin$/);
    await page.getByRole('link', { name: 'Evidence review' }).click();
    await page.getByRole('link', { name: new RegExp(`Review.*Acme Book 14`) }).click();
    await expect(page.getByRole('heading', { name: 'Acme Book 14' })).toBeVisible();
    await page.getByRole('button', { name: 'Save decision' }).click();
    await expect(page.getByText('Evidence approved. The student can now buy a policy.')).toBeVisible();

    // Student can now purchase the policy.
    await page.context().clearCookies();
    await page.goto('/login');
    await page.getByLabel('Username').fill(username);
    await page.getByLabel('Password').fill(password);
    await page.getByRole('button', { name: 'Sign in' }).click();
    await page.getByRole('link', { name: 'My assets' }).click();
    await expect(page.getByRole('button', { name: 'Insure this asset' })).toBeVisible();
    await page.getByRole('button', { name: 'Insure this asset' }).click();
    await page.getByLabel(/I have read the coverage/).check();
    await page.getByRole('button', { name: /and activate/ }).click();
    await expect(page).toHaveURL(/\/student\/policies$/);

    // Submit a simulated claim. It must not auto-pay: a staff member confirms.
    await page.getByRole('link', { name: 'Submit a claim' }).click();
    await page.getByLabel('Insured asset').selectOption({ index: 1 });
    await page.getByRole('button', { name: 'Continue' }).click();
    await page.getByLabel('Type of damage').selectOption({ label: 'Broken screen' });
    await page.getByLabel('Describe the incident').fill('The laptop fell from my desk and the screen cracked.');
    await page.getByRole('button', { name: 'Continue to photos' }).click();
    await page.getByLabel('Add photos').setInputFiles({ name: 'damage.png', mimeType: 'image/png', buffer: makePng(77) });
    await page.getByRole('button', { name: /Upload 1 photo/ }).click();
    await expect(page.getByRole('button', { name: /Submit claim for AI verification/ })).toBeEnabled();
    await page.getByRole('button', { name: /Submit claim for AI verification/ }).click();
    await expect(page.getByRole('heading', { name: 'AI damage verification report' })).toBeVisible({ timeout: 30_000 });
    await expect(page.getByText('Development simulation.', { exact: false })).toBeVisible();
    await expect(page.getByText('Waiting for a staff member to confirm.')).toBeVisible();
    await expect(page.getByText('Claim approved and settled (simulated).')).toHaveCount(0);
    w.assertClean();
  });
});
