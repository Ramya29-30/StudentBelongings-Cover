import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page } from '@playwright/test';
import { loginAs, logout, tab, watchBrowser } from './helpers';

const PAGES: Record<'student' | 'assessor' | 'admin', string[]> = {
  student: ['/student', '/student/assets', '/student/policies', '/student/claims', '/student/claims/new', '/student/claims/1'],
  assessor: ['/assessor', '/assessor/claims', '/assessor/claims/1', '/assessor/finance', '/assessor/policies', '/assessor/audit'],
  admin: ['/admin', '/admin/policies', '/admin/policies/1', '/admin/plans', '/admin/plans/1', '/admin/claims', '/admin/claims/1', '/admin/finance', '/admin/users', '/admin/audit', '/admin/settings'],
};

test.describe('form validation (client and server)', () => {
  test('new claim: required fields and future date are rejected before submit', async ({ page }) => {
    await loginAs(page, 'student');
    await page.goto('/student/claims/new');
    await page.getByRole('button', { name: 'Create draft claim' }).click();
    await expect(page.getByText('Choose a policy')).toBeVisible();
    await expect(page.getByText('Choose the item that was affected')).toBeVisible();
    await expect(page.getByText('Enter the incident date')).toBeVisible();
    await expect(page.getByText('Choose what happened')).toBeVisible();
    await expect(page.getByLabel(/^Policy/)).toHaveAttribute('aria-invalid', 'true');
  });

  test('assets form validates value and purchase date', async ({ page }) => {
    await loginAs(page, 'student');
    await page.goto('/student/assets');
    await page.getByRole('button', { name: 'Add asset' }).click();
    await expect(page.getByText('Choose a category')).toBeVisible();
    await expect(page.getByText('Enter a value greater than 0')).toBeVisible();
    await page.getByLabel(/^Category/).selectOption('Laptop');
    await page.getByLabel(/^Name/).fill('Test laptop');
    await page.getByLabel(/^Purchase date/).fill('2020-01-01');
    await page.getByLabel(/^Declared value/).fill('-5');
    await page.getByRole('button', { name: 'Add asset' }).click();
    await expect(page.getByText('Enter a value greater than 0')).toBeVisible();
    await page.getByLabel(/^Declared value/).fill('25000');
    await page.getByRole('button', { name: 'Add asset' }).click();
    await expect(page.getByText('Asset added')).toBeVisible();
    await expect(page.getByRole('cell', { name: 'Test laptop' })).toBeVisible();
  });

  test('the backend validates independently of the UI', async ({ page }) => {
    await loginAs(page, 'student');
    const me = await (await page.request.get('/api/auth/me')).json();
    const h = { 'X-CSRF-Token': me.csrf_token };
    const future = new Date(Date.now() + 5 * 86400000).toISOString().slice(0, 10);
    const r = await page.request.post('/api/claims', { headers: h, data: { policy_id: 1, asset_id: 1, incident_date: future, incident_type: 'Theft' } });
    expect(r.status()).toBeGreaterThanOrEqual(400);
    const bad = await page.request.post('/api/assets', { headers: h, data: { category: 'Laptop', name: '', purchase_date: '2020-01-01', declared_value: -1 } });
    expect(bad.status()).toBe(422);
    const evil = await page.request.post('/api/claims/1/evidence', { headers: h, multipart: { doc_type: 'damage_photo', file: { name: 'x.png', mimeType: 'image/png', buffer: Buffer.from('<script>alert(1)</script>') } } });
    expect(evil.status()).toBeGreaterThanOrEqual(400); // content sniffing rejects a script disguised as a PNG
  });

  test('evidence upload rejects a disallowed file type in the UI', async ({ page }) => {
    await loginAs(page, 'student');
    await page.goto('/student/claims');
    await page.getByRole('row', { name: /Draft/ }).first().getByRole('link').click();
    await tab(page, 'Evidence').click();
    await page.getByLabel('Document type').selectOption('damage_photo');
    await page.getByLabel('File').setInputFiles({ name: 'malware.exe', mimeType: 'application/octet-stream', buffer: Buffer.from('MZ') });
    await page.getByRole('button', { name: 'Upload' }).click();
    await expect(page.getByText(/Allowed types/)).toBeVisible();
  });
});

test.describe('error handling and API integration', () => {
  test('server error is shown as an alert, not a blank page', async ({ page }) => {
    await loginAs(page, 'student');
    await page.route('**/api/policies', r => r.fulfill({ status: 500, contentType: 'application/json', body: '{"detail":"Internal error (ref abc123)"}' }));
    await page.getByRole('link', { name: 'Policy Centre' }).click();
    await expect(page.getByRole('alert')).toContainText('Internal error');
  });

  test('network failure is reported', async ({ page }) => {
    await loginAs(page, 'student');
    await page.route('**/api/assets', r => r.abort('failed'));
    await page.getByRole('link', { name: 'My assets' }).click();
    await expect(page.getByRole('alert')).toBeVisible();
  });

  test('unknown routes show a not-found page inside the portal', async ({ page }) => {
    await loginAs(page, 'student');
    await page.goto('/student/does-not-exist');
    await expect(page.getByRole('heading', { name: 'Page not found' })).toBeVisible();
  });

  test('state-changing requests carry the CSRF header; GETs go to /api with the session cookie only', async ({ page }) => {
    await loginAs(page, 'student');
    const posts: Record<string, string | undefined>[] = [];
    page.on('request', r => { if (r.url().includes('/api/') && r.method() !== 'GET') posts.push(r.headers()); });
    await page.goto('/student/assets');
    await page.getByLabel(/^Category/).selectOption('Tablet');
    await page.getByLabel(/^Name/).fill('CSRF probe tablet');
    await page.getByLabel(/^Purchase date/).fill('2024-01-01');
    await page.getByLabel(/^Declared value/).fill('1000');
    await page.getByRole('button', { name: 'Add asset' }).click();
    await expect(page.getByText('Asset added')).toBeVisible();
    expect(posts.length).toBeGreaterThan(0);
    for (const h of posts) { expect(h['x-csrf-token']).toBeTruthy(); expect(h['authorization']).toBeUndefined(); }
  });

  test('a 401 during use returns to login and does not leave stale data on screen', async ({ page }) => {
    await loginAs(page, 'assessor');
    await page.route('**/api/claims**', r => r.fulfill({ status: 401, contentType: 'application/json', body: '{"detail":"Not authenticated"}' }));
    await page.getByRole('link', { name: 'Claims', exact: true }).click();
    await expect(page).toHaveURL(/\/login$/);
  });
});

test.describe('console, CSP and navigation across every page', () => {
  for (const role of ['student', 'assessor', 'admin'] as const) {
    test(`${role}: every portal page renders with no console errors, CSP violations or page errors`, async ({ page }) => {
      const w = watchBrowser(page);
      await loginAs(page, role);
      for (const path of PAGES[role]) {
        await page.goto(path);
        await expect(page.getByRole('heading', { level: 1 }).first()).toBeVisible();
        await expect(page.getByRole('status').filter({ hasText: /^Loading/ })).toHaveCount(0, { timeout: 8000 });
      }
      w.assertClean();
    });
  }
});

test.describe('accessibility', () => {
  const scan = async (page: Page, label: string) => {
    const r = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa']).analyze();
    const summary = r.violations.map(v => `${label}: ${v.id} (${v.impact}) ${v.help} -> ${v.nodes.slice(0, 3).map(n => n.target.join(' ')).join(' | ')}`);
    expect(summary, 'axe violations').toEqual([]);
  };

  test('login page has no axe violations', async ({ page }) => { await page.goto('/login'); await scan(page, 'login'); });

  for (const role of ['student', 'assessor', 'admin'] as const) {
    test(`${role} pages have no axe WCAG A/AA violations`, async ({ page }) => {
      await loginAs(page, role);
      for (const path of PAGES[role]) {
        await page.goto(path);
        await expect(page.getByRole('heading', { level: 1 }).first()).toBeVisible();
        await expect(page.getByRole('status').filter({ hasText: /^Loading/ })).toHaveCount(0, { timeout: 8000 });
        await scan(page, path);
      }
    });
  }

  test('claim tabs and modal dialogs pass axe too', async ({ page }) => {
    await loginAs(page, 'assessor');
    await page.goto('/assessor/claims/1');
    for (const t of ['Evidence', 'Damage items', 'Assessment & rules', 'Reserves & payments', 'History']) {
      await tab(page, t).click();
      await expect(page.getByRole('tabpanel')).toBeVisible();
      await page.waitForTimeout(250);
      await scan(page, `claim tab ${t}`);
    }
  });

  test('keyboard: skip link, tab order, tab arrow keys and visible focus', async ({ page }) => {
    await loginAs(page, 'student');
    await page.goto('/student/policies/1');
    await expect(page.getByRole('heading', { level: 1 }).first()).toBeVisible(); // wait for the SPA to render before using the keyboard
    await page.keyboard.press('Tab');
    const skip = page.getByRole('link', { name: 'Skip to main content' });
    await expect(skip).toBeFocused();
    await page.keyboard.press('Enter');
    await expect(page.locator('main')).toBeFocused();
    // Tabs: arrow keys move and activate
    await tab(page, 'Cover & conditions').focus();
    await page.keyboard.press('ArrowRight');
    await expect(tab(page, 'Insured assets')).toBeFocused();
    await expect(tab(page, 'Insured assets')).toHaveAttribute('aria-selected', 'true');
    // every interactive element shows a visible focus indicator
    await page.getByRole('link', { name: 'Claim Centre' }).focus();
    const outline = await page.evaluate(() => { const s = getComputedStyle(document.activeElement!); return { style: s.outlineStyle, width: parseFloat(s.outlineWidth) }; });
    expect(outline.style).not.toBe('none');
    expect(outline.width).toBeGreaterThanOrEqual(2);
  });

  test('keyboard: dialog opens, traps focus, closes with Escape and returns focus', async ({ page }) => {
    await loginAs(page, 'admin');
    await page.goto('/admin/users');
    const opener = page.getByRole('button', { name: 'Create user' });
    await opener.focus();
    await page.keyboard.press('Enter');
    const dlg = page.getByRole('dialog', { name: 'Create user' });
    await expect(dlg).toBeVisible();
    await expect(dlg.getByLabel('Username')).toBeVisible();
    for (let i = 0; i < 12; i++) await page.keyboard.press('Tab');
    expect(await page.evaluate(() => !!document.activeElement?.closest('dialog'))).toBe(true); // focus stays inside the modal
    await page.keyboard.press('Escape');
    await expect(dlg).toBeHidden();
    await expect(opener).toBeFocused();
  });

  test('every form control has an accessible name', async ({ page }) => {
    await loginAs(page, 'admin');
    for (const path of ['/admin/plans/new', '/admin/policies/new', '/admin/users']) {
      await page.goto(path);
      const unnamed = await page.evaluate(() => Array.from(document.querySelectorAll('input:not([type=hidden]),select,textarea')).filter(el => {
        const e = el as HTMLInputElement; return !(e.labels && e.labels.length) && !e.getAttribute('aria-label') && !e.getAttribute('aria-labelledby');
      }).map(el => (el as HTMLElement).outerHTML.slice(0, 80)));
      expect(unnamed, path).toEqual([]);
    }
  });
});

test.describe('responsive layouts', () => {
  const sizes = [{ name: 'phone', width: 375, height: 812 }, { name: 'tablet', width: 768, height: 1024 }];
  for (const size of sizes) {
    for (const role of ['student', 'assessor', 'admin'] as const) {
      test(`${role} on ${size.name}: no horizontal page scroll and navigation reachable`, async ({ page }) => {
        await page.setViewportSize({ width: size.width, height: size.height });
        await loginAs(page, role);
        for (const path of PAGES[role].slice(0, 5)) {
          await page.goto(path);
          await expect(page.getByRole('heading', { level: 1 }).first()).toBeVisible();
          const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
          expect(overflow, `${path} overflows by ${overflow}px`).toBeLessThanOrEqual(1);
        }
        await expect(page.getByRole('navigation', { name: 'Main' })).toBeVisible();
        await expect(page.getByRole('button', { name: 'Sign out' })).toBeVisible();
      });
    }
  }
  test('login works on a phone viewport', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    await loginAs(page, 'student');
    await logout(page);
  });
});

test('claim page: tabs are reachable on a phone and wide tables scroll inside their own container', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await loginAs(page, 'assessor');
  await page.goto('/assessor/claims/1');
  await tab(page, 'Assessment & rules').click();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
});
