const DECIMALS: Record<string, number> = { MXN: 2, ARS: 2, COP: 2, BRL: 2, USDC: 6, USDT: 6, BTC: 8, ETH: 8 }

export const DECIMALS_HINT: Record<string, string> = Object.fromEntries(
  Object.entries(DECIMALS).map(([k, v]) => [k, `up to ${v} decimals`]),
)

/** A suggested target: today's best payout + 0.2%, rounded down to the currency's precision.
 * Computed on the decimal string (no float rounding leaks into the amount). */
export function suggestTarget(best: string, ccy: string): string {
  const places = DECIMALS[ccy] ?? 2
  const [i, f = ''] = best.split('.')
  const scaled = BigInt(i + f.padEnd(places, '0').slice(0, places)) // best in minor units
  const bumped = (scaled * 1002n) / 1000n
  const s = bumped.toString().padStart(places + 1, '0')
  return places ? `${s.slice(0, -places)}.${s.slice(-places)}` : s
}
