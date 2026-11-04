// Playwright config for Hack the World browser E2E.
//
// The app server must already run with the deterministic fixture:
//   HTW_E2E_FAKE_PROVIDER=1 python phone_app.py
// Serial workers are required: the demo server keeps one global session.
const { defineConfig } = require('@playwright/test');

module.exports = defineConfig({
  testDir: '.',
  testMatch: '**/*.spec.js',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [['list']],
  use: {
    baseURL: process.env.E2E_BASE_URL || 'http://127.0.0.1:8000',
    screenshot: 'only-on-failure',
    trace: 'on-first-retry',
  },
  projects: [{ name: 'chromium' }],
});
