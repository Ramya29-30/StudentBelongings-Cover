import { expect, test } from '@playwright/test';
import { loginAs, watchBrowser } from './helpers';

test('app loads, serves the built React UI and has a clean console', async ({ page }) => {
  const w = watchBrowser(page);
  await page.goto('/');
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByRole('heading', { name: 'StudentBelongings Cover' })).toBeVisible();
  await loginAs(page, 'student');
  w.assertClean();
});
