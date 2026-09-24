import { defineConfig } from '@playwright/test'

if (!process.env.E2E_BASE_URL || !process.env.E2E_API_URL) {
  throw new Error('Set E2E_BASE_URL and E2E_API_URL for the isolated E2E stand')
}

export default defineConfig({
  testDir: './e2e',
  timeout: 30000,
  expect: { timeout: 10000 },
  use: {
    baseURL: process.env.E2E_BASE_URL,
    browserName: 'chromium',
    trace: 'retain-on-failure',
  },
  workers: 1,
})
