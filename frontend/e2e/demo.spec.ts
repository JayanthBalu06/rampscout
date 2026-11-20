import { expect, type Page, test } from '@playwright/test'

const EXAMPLE = 'Convert 600 USDC if I can receive at least 10,000 pesos by Friday at 5 p.m. Mexico City time.'

/** Fresh demo session at tick 0 with its quotes loaded (not the previous session's). */
async function freshSession(page: Page) {
  await page.goto('/#/compare')
  await expect(page.getByText(/tick \d+/)).toBeVisible()
  // Wait for the reset itself, then for the quotes fetched *after* it (on a slow host the
  // initial page-load quotes can arrive late and be mistaken for fresh ones).
  const reset = page.waitForResponse((r) => r.url().endsWith('/api/demo/reset') && r.ok())
  await page.getByRole('button', { name: 'Reset' }).click()
  await reset
  await page.waitForResponse((r) => r.url().endsWith('/api/quotes') && r.ok())
  await expect(page.getByText(/tick 0/)).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Compare routes' })).toBeVisible()
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
  await expect(page.getByText(/Drafted by/)).toBeVisible()
  await page.getByRole('button', { name: 'Review terms' }).click()
  await expect(page.getByRole('heading', { name: 'Review and confirm' })).toBeVisible()
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

test('home shows the wallet with send and receive', async ({ page }) => {
  await freshSession(page)
  await page.goto('/#/home')
  await expect(page.getByRole('region', { name: 'Your wallet' })).toBeVisible()
  await expect(page.getByText(/USDC/).first()).toBeVisible()
  await page.getByRole('link', { name: /Receive/ }).click()
  await expect(page.getByRole('img', { name: /QR code/ })).toBeVisible()
})

test('send to a bank account picks the best live route and pays', async ({ page }) => {
  await freshSession(page)
  await page.goto('/#/send')
  await page.getByRole('tab', { name: 'Bank account' }).click()
  await expect(page.getByText(/Mamá receives/)).toBeVisible({ timeout: 20_000 })
  await expect(page.getByText(/routes compared/)).toBeVisible()
  await page.getByRole('button', { name: /^Send 600/ }).click()
  await page.getByRole('button', { name: 'Confirm and send' }).click()
  await expect(page.getByRole('heading', { name: 'Receipt' })).toBeVisible()
  await expect(page.getByText('Executed route')).toBeVisible()
  await expect(page.getByText('Posted to bank (simulated SPEI)')).toBeVisible()
})

test('paste a wallet address, recipient wants BTC: best conversion route, confirm new address', async ({ page }) => {
  await freshSession(page)
  await page.goto('/#/send')
  await page.getByLabel(/Recipient address/).fill('0x' + '12'.repeat(20))
  await page.getByText('BTC', { exact: true }).click()
  await expect(page.getByText('Best route', { exact: true })).toBeVisible({ timeout: 20_000 })
  await expect(page.locator('article').getByText(/BTC$/).first()).toBeVisible()
  await page.getByRole('button', { name: /^Send 600/ }).click()
  const confirm = page.getByRole('button', { name: 'Confirm and send' })
  await expect(confirm).toBeDisabled() // new address must be acknowledged
  await page.getByRole('checkbox').check()
  await confirm.click()
  await expect(page.getByRole('heading', { name: 'Receipt' })).toBeVisible()
  await expect(page.getByText(/Simulated withdrawal/).first()).toBeVisible()
})

test('send USDC to a saved wallet is a direct onchain transfer', async ({ page }) => {
  await freshSession(page)
  await page.goto('/#/send')
  await page.getByRole('button', { name: /Ana · USDC/ }).click()
  await expect(page.getByText('Best route', { exact: true })).toBeVisible({ timeout: 20_000 })
  await page.getByRole('button', { name: /^Send 600/ }).click()
  await page.getByRole('button', { name: 'Confirm and send' }).click()
  await expect(page.getByText('Delivered to wallet onchain')).toBeVisible()
})

test('ask the agent: send now opens Send with the best route prefilled', async ({ page }) => {
  await freshSession(page)
  await page.goto('/#/home')
  await page.getByRole('button', { name: 'Send 600 USDC to Mamá', exact: true }).click()
  await expect(page.getByText(/Send now:/)).toBeVisible({ timeout: 20_000 })
  await page.getByRole('link', { name: 'Review and send' }).click()
  await expect(page.getByText(/Mamá receives/)).toBeVisible({ timeout: 20_000 })
})

test('ask the agent: a high target waits; check now; cancel', async ({ page }) => {
  await freshSession(page)
  await page.goto('/#/home')
  await page.getByRole('textbox', { name: 'Ask RampScout' }).fill('Send 600 USDC to Mamá when she gets at least 99,999 pesos by tomorrow 11pm')
  await page.getByRole('button', { name: 'Ask', exact: true }).click()
  await expect(page.getByText(/Below your minimum, so the agent will wait/)).toBeVisible({ timeout: 20_000 })
  await page.getByRole('button', { name: 'Confirm and start watching' }).click()
  await expect(page.getByText(/short of MX\$99,999.00/).first()).toBeVisible()
  await page.getByRole('button', { name: 'Check now' }).click()
  await expect(page.getByText(/short of MX\$99,999.00/).first()).toBeVisible()
  page.once('dialog', (d) => d.accept())
  await page.getByRole('button', { name: 'Cancel watch' }).click()
  await expect(page.getByText('Canceled').first()).toBeVisible()
})

test('ask the agent: auto-send fires when the target is already met', async ({ page }) => {
  await freshSession(page)
  await page.goto('/#/home')
  await page
    .getByRole('textbox', { name: 'Ask RampScout' })
    .fill('Automatically send 600 USDC to Mamá when she gets at least 100 pesos by tomorrow 11pm')
  await page.getByRole('button', { name: 'Ask', exact: true }).click()
  await expect(page.getByText('Already meets your minimum.')).toBeVisible({ timeout: 20_000 })
  await expect(page.getByLabel(/Auto-send/)).toBeChecked()
  await page.getByRole('button', { name: 'Confirm and start watching' }).click()
  await expect(page.getByRole('heading', { name: 'Receipt' })).toBeVisible()
  await expect(page.getByText('Posted to bank (simulated SPEI)')).toBeVisible()
})

test('send screen: let the agent wait for a better price', async ({ page }) => {
  await freshSession(page)
  await page.goto('/#/send')
  await page.getByRole('tab', { name: 'Bank account' }).click()
  await expect(page.getByText(/Mamá receives/)).toBeVisible({ timeout: 20_000 })
  await page.getByRole('button', { name: /let the agent wait/ }).click()
  await page.getByRole('button', { name: 'Start watching' }).click()
  await expect(page.getByText(/short of/).first()).toBeVisible()
  await expect(page.getByText('Agent · notify')).toBeVisible()
})
