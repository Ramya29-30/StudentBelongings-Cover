import { defineConfig, devices } from '@playwright/test';

const port = process.env.E2E_PORT || '8765';
export default defineConfig({
  testDir: './tests',
  timeout: 45_000,
  expect: { timeout: 8_000 },
  fullyParallel: false,
  workers: 1, // one shared throw-away database; the lifecycle spec depends on order
  retries: 0,
  reporter: [['list'], ['json', { outputFile: 'results.json' }], ['html', { open: 'never', outputFolder: 'playwright-report' }]],
  use: {
    baseURL: `http://127.0.0.1:${port}`, trace: 'retain-on-failure', screenshot: 'only-on-failure',
    // Optional: run against a Chromium you already have (set E2E_CHROMIUM_PATH). Default behaviour is unchanged.
    ...(process.env.E2E_CHROMIUM_PATH ? { launchOptions: { executablePath: process.env.E2E_CHROMIUM_PATH, args: ['--no-sandbox', '--disable-gpu'] } } : {}),
  },
  projects: [
    { name: 'desktop-chromium', use: { ...devices['Desktop Chrome'] } },
  ],
  webServer: { command: 'node serve.mjs', url: `http://127.0.0.1:${port}/api/ready`, timeout: 60_000, reuseExistingServer: false },
});
