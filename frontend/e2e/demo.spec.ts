import { expect, type Page, test } from '@playwright/test'

const EXAMPLE = 'Convert 600 USDC if I can receive at least 10,000 pesos by Friday at 5 p.m. Mexico City time.'

/** Fresh demo session at tick 0 with its quotes loaded (not the previous session's). */
async function freshSession(page: Page) {
  await page.goto('/#/compare')
  await expect(page.getByText(/tick \d+/)).toBeVisible()
  const quoted = page.waitForResponse((r) => r.url().endsWith('/api/quotes') && r.ok())
  await page.getByRole('button', { name: 'Reset' }).click()
  await quoted
  await expect(page.getByText(/tick 0/)).toBeVisible()
}

test('compare shows why the higher rate pays fewer pesos', async ({ page }) => {
  await freshSession(page)
  await expect(page.getByText('MX$9,993.25').first()).toBeVisible()
  await expect(page.getByText('MX$9,976.30').first()).toBeVisible()
  await expect(page.getByText(/Route A has the higher rate/)).toBeVisible()
  await page.getByText('Fee breakdown').nth(1).click()
  await expect(page.getByText('MX$10,076.30')).toBeVisible()
})

test('notify watch waits at tick 0, matches at tick 1, never converts', async ({ page }) => {
  await freshSession(page)
  await page.getByRole('link', { name: 'Watch for a target' }).click()
  await page.getByLabel(/Ask the agent/).fill(EXAMPLE)
  await page.getByRole('button', { name: 'Draft terms' }).click()
  await expect(page.getByText(/Drafted by/)).toBeVisible()
  await page.getByRole('button', { name: 'Review terms' }).click()
  await expect(page.getByText(/Friday, November 27, 2026 at 5:00 PM CST/)).toBeVisible()
  await page.getByRole('button', { name: 'Confirm and start watching' }).click()
  await expect(page.getByText(/MX\$6.75 short/).first()).toBeVisible()
  await page.getByRole('button', { name: 'Advance 1 tick' }).click()
  await expect(page.getByText(/Target reached: MX\$10,023.20/)).toBeVisible()
  await expect(page.getByText('Notified you', { exact: true })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Receipt' })).toHaveCount(0)
})

test('auto watch revalidates and settles with a receipt', async ({ page }) => {
  await freshSession(page)
  await page.goto('/#/watch/new')
  await page.getByLabel(/Ask the agent/).fill(EXAMPLE)
  await page.getByRole('button', { name: 'Draft terms' }).click()
  await page.getByRole('button', { name: 'Review terms' }).click()
  await page.getByLabel(/Auto-convert/).check()
  await expect(page.getByText(/demo scale/)).toBeVisible()
  await page.getByRole('button', { name: 'Confirm and start watching' }).click()
  await expect(page.getByText(/short of your/).first()).toBeVisible()
  await page.getByRole('button', { name: 'Advance 1 tick' }).click()
  await expect(page.getByRole('heading', { name: 'Receipt' })).toBeVisible()
  await expect(page.getByText('Posted to bank (simulated SPEI)')).toBeVisible()
  await expect(page.getByText('Revalidated & executing')).toBeVisible()
})

test('lost broadcast response is reconciled by the original hash', async ({ page }) => {
  await freshSession(page)
  await page.getByLabel('Lose next broadcast response').click()
  await expect(page.getByLabel('Lose next broadcast response')).toBeChecked()
  await page.getByRole('button', { name: 'Convert now' }).first().click()
  await page.getByRole('button', { name: 'Confirm and convert' }).click()
  await expect(page.getByText(/Reconciled by original hash|broadcast outcome unknown/).first()).toBeVisible()
  await page.getByRole('button', { name: 'Restart worker' }).click()
  await expect(page.getByText(/Reconciled by original hash/)).toBeVisible()
  await expect(page.getByText('Posted to bank (simulated SPEI)')).toBeVisible()
})

test('expired quote requires fresh confirmation', async ({ page }) => {
  await freshSession(page)
  await page.getByRole('button', { name: 'Convert now' }).first().click()
  await page.request.post('/api/demo/advance')
  await page.getByRole('button', { name: 'Confirm and convert' }).click()
  await expect(page.getByRole('heading', { name: /Quote changed/ })).toBeVisible()
  await page.getByRole('button', { name: 'Confirm new quote' }).click()
  await expect(page.getByText('Posted to bank (simulated SPEI)')).toBeVisible()
})
