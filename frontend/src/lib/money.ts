/**
 * Money arrives from the API as decimal strings ("9993.25"). We never parse it into
 * a JS number. Formatting works on the string so no float rounding can occur.
 */
const DECIMAL_RE = /^-?\d+(\.\d+)?$/

export function formatDecimal(value: string, fractionDigits = 2): string {
  if (!DECIMAL_RE.test(value)) throw new Error(`Not a decimal string: ${value}`)
  const negative = value.startsWith('-')
  const [intPart, frac = ''] = (negative ? value.slice(1) : value).split('.')
  const grouped = intPart.replace(/\B(?=(\d{3})+(?!\d))/g, ',')
  // Display truncates (never rounds up) to match the server's ROUND_DOWN policy.
  const fracOut = fractionDigits > 0 ? '.' + frac.padEnd(fractionDigits, '0').slice(0, fractionDigits) : ''
  return `${negative ? '-' : ''}${grouped}${fracOut}`
}

export const formatMXN = (v: string) => `MX$${formatDecimal(v, 2)}`
export const formatUSDC = (v: string) => `${formatDecimal(v, 2)} USDC`
