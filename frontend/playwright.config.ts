import { defineConfig } from '@playwright/test'

// Runs against a live stack (API + built UI on one origin), e.g. `make e2e`
// or `docker compose --profile app up`. Override with E2E_BASE_URL.
export default defineConfig({
  testDir: './e2e',
  globalSetup: './e2e/global-setup.ts',
  timeout: 60_000,
  retries: process.env.CI ? 1 : 0,
  use: {
    baseURL: process.env.E2E_BASE_URL ?? 'http://localhost:8000',
    trace: 'retain-on-failure',
  },
})
