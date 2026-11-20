import type { FullConfig } from '@playwright/test'

/** Refuse to run against a server that would make real testnet transfers, unless asked. */
export default async function globalSetup(config: FullConfig) {
  const base = config.projects[0].use.baseURL ?? 'http://localhost:8000'
  const res = await fetch(`${base}/api/health/settlement`)
  const status = (await res.json()) as { mode: string }
  if (status.mode === 'testnet' && process.env.E2E_ALLOW_TESTNET !== '1') {
    throw new Error(
      `${base} is in TESTNET mode: these tests would send real test USDC. ` +
        'Point them at a simulated stack, or set E2E_ALLOW_TESTNET=1 to proceed deliberately.',
    )
  }
}
