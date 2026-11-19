import { expect, type Page, type TestInfo } from '@playwright/test';

export const USERS = {
  student: { username: 'aarav', password: 'student123', home: /\/student$/, heading: /Welcome, Aarav/ },
  student2: { username: 'meera', password: 'student123', home: /\/student$/, heading: /Welcome, Meera/ },
  assessor: { username: 'assessor', password: 'assessor123', home: /\/assessor$/, heading: /Assessor dashboard/ },
  admin: { username: 'admin', password: 'admin123', home: /\/admin$/, heading: /Administrator dashboard/ },
} as const;

/** Collects problems the browser reports. Page errors and CSP violations always fail; expected 4xx network noise is ignored. */
export function watchBrowser(page: Page) {
  const problems: string[] = [];
  page.on('pageerror', e => problems.push('pageerror: ' + e.message));
  page.on('console', m => {
    if (m.type() !== 'error' && m.type() !== 'warning') return;
    const t = m.text();
    if (/Failed to load resource: the server responded with a status of 4\d\d/.test(t)) return;
    problems.push(`console.${m.type()}: ${t}`);
  });
  return { problems, assertClean: () => expect(problems, 'browser console / CSP / page errors').toEqual([]) };
}

export async function loginAs(page: Page, who: keyof typeof USERS) {
  const u = USERS[who];
  await page.goto('/login');
  await page.getByLabel('Username').fill(u.username);
  await page.getByLabel('Password').fill(u.password);
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page).toHaveURL(u.home);
  await expect(page.getByRole('heading', { level: 1 })).toContainText(u.heading);
}

export async function logout(page: Page) {
  await page.getByRole('button', { name: 'Sign out' }).click();
  await expect(page).toHaveURL(/\/login$/);
}

export const isoDaysAgo = (n: number) => new Date(Date.now() - n * 86400000).toISOString().slice(0, 10);
export const tab = (page: Page, name: string) => page.getByRole('tab', { name });
export const note = (info: TestInfo, text: string) => info.annotations.push({ type: 'note', description: text });

/** Select an <option> by a regex on its visible text (Playwright's label option only takes exact strings). */
export async function selectByText(select: import('@playwright/test').Locator, re: RegExp) {
  const value = await select.evaluate((el, src) => {
    const rx = new RegExp(src.source, src.flags);
    const o = Array.from((el as HTMLSelectElement).options).find(x => rx.test(x.text));
    return o ? o.value : null;
  }, { source: re.source, flags: re.flags });
  expect(value, `option matching ${re}`).not.toBeNull();
  await select.selectOption(value!);
}

/** A real 1x1 PNG so the server's content sniffing accepts it. */
export const PNG = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==', 'base64');
export const toast = (page: import('@playwright/test').Page, text: RegExp) => page.getByText(text).first();
