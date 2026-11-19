import { expect, test } from '@playwright/test';
import { USERS, loginAs, logout, watchBrowser } from './helpers';

test.describe('authentication', () => {
  for (const who of ['student', 'assessor', 'admin'] as const) {
    test(`${who} can sign in and sign out`, async ({ page }) => {
      const w = watchBrowser(page);
      await loginAs(page, who);
      await expect(page.getByRole('navigation', { name: 'Main' })).toBeVisible();
      await logout(page);
      w.assertClean();
    });
  }

  test('wrong password shows a generic error and stays on the login page', async ({ page }) => {
    await page.goto('/login');
    await page.getByLabel('Username').fill('aarav');
    await page.getByLabel('Password').fill('not-the-password');
    await page.getByRole('button', { name: 'Sign in' }).click();
    await expect(page.getByRole('alert').filter({ hasText: 'Invalid username or password' })).toBeVisible();
    await expect(page).toHaveURL(/\/login$/);
  });

  test('login form validates empty fields on the client', async ({ page }) => {
    await page.goto('/login');
    await page.getByRole('button', { name: 'Sign in' }).click();
    await expect(page.getByText('Enter your username')).toBeVisible();
    await expect(page.getByText('Enter your password')).toBeVisible();
    await expect(page.getByLabel('Username')).toHaveAttribute('aria-invalid', 'true');
  });

  test('protected pages redirect to login when signed out', async ({ page }) => {
    for (const path of ['/student', '/assessor/claims', '/admin/users']) {
      await page.goto(path);
      await expect(page).toHaveURL(/\/login$/);
    }
  });

  test('role restrictions: a role cannot open another role\'s pages or APIs', async ({ page }) => {
    await loginAs(page, 'student');
    await page.goto('/admin/users');
    await expect(page).toHaveURL(/\/student$/);
    await page.goto('/assessor/claims');
    await expect(page).toHaveURL(/\/student$/);
    // The backend enforces it too, independent of the UI.
    const r = await page.request.get('/api/users');
    expect(r.status()).toBe(403);
    const r2 = await page.request.get('/api/admin/overview');
    expect(r2.status()).toBe(403);
    await logout(page);
    await loginAs(page, 'assessor');
    await page.goto('/admin');
    await expect(page).toHaveURL(/\/assessor$/);
    expect((await page.request.get('/api/users')).status()).toBe(403);
  });

  test('session expiry returns the user to login with an explanation', async ({ page, context }) => {
    await loginAs(page, 'student');
    await context.clearCookies(); // the server no longer recognises the browser
    await page.getByRole('link', { name: 'Claim Centre' }).click();
    await expect(page).toHaveURL(/\/login$/);
    await expect(page.getByText('Your session has expired')).toBeVisible();
  });

  test('server-side logout invalidates the session', async ({ page, context }) => {
    await loginAs(page, 'student');
    const cookies = await context.cookies();
    const sess = cookies.find(c => c.name === 'sbc_session');
    expect(sess).toBeTruthy();
    await logout(page);
    await context.addCookies([sess!]); // replay the old cookie
    const r = await page.request.get('/api/auth/me');
    expect(r.status()).toBe(401);
  });

  test('no authentication secret is exposed to JavaScript', async ({ page, context }) => {
    await loginAs(page, 'student');
    const cookie = (await context.cookies()).find(c => c.name === 'sbc_session')!;
    expect(cookie.httpOnly).toBe(true);
    expect(cookie.sameSite).toBe('Strict');
    const seen = await page.evaluate(() => ({ cookie: document.cookie, local: JSON.stringify(localStorage), session: JSON.stringify(sessionStorage) }));
    expect(seen.cookie).not.toContain('sbc_session');
    expect(seen.local + seen.session).not.toMatch(/token|bearer|sbc_session/i);
  });

  test('writes without the CSRF token are rejected', async ({ page }) => {
    await loginAs(page, 'student');
    const r = await page.request.post('/api/claims/1/submit'); // cookie is sent, CSRF header is not
    expect(r.status()).toBe(403);
    expect(await r.text()).toContain('CSRF');
  });

  test('CSP forbids inline scripts and security headers are present', async ({ page }) => {
    const r = await page.goto('/login');
    const h = r!.headers();
    const csp = h['content-security-policy'];
    expect(csp).toContain("default-src 'self'");
    const scriptSrc = csp.split(';').map(s => s.trim()).find(s => s.startsWith('script-src'))!;
    expect(scriptSrc).not.toContain('unsafe-inline');
    expect(scriptSrc).not.toContain('unsafe-eval');
    const styleSrc = csp.split(';').map(s => s.trim()).find(s => s.startsWith('style-src'))!;
    expect(styleSrc).not.toContain('unsafe-inline');
    expect(csp).toContain("object-src 'none'");
    expect(csp).toContain("frame-ancestors 'none'");
    expect(h['x-frame-options']).toBe('DENY');
    expect(h['x-content-type-options']).toBe('nosniff');
  });

  test('login rate limiting blocks an account after repeated failures', async ({ page }) => {
    const name = 'lockout-probe'; // a throw-away username so the demo accounts stay usable for later tests
    for (let i = 0; i < 5; i++) {
      const r = await page.request.post('/api/auth/login', { data: { username: name, password: 'wrong-' + i } });
      expect(r.status()).toBe(401);
    }
    await page.goto('/login');
    await page.getByLabel('Username').fill(name);
    await page.getByLabel('Password').fill('wrong-again');
    await page.getByRole('button', { name: 'Sign in' }).click();
    await expect(page.getByRole('alert').filter({ hasText: /Too many failed sign-in attempts/ })).toBeVisible();
  });
});
