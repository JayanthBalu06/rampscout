import { describe, expect, it } from 'vitest'
import { formatDecimal, formatMXN } from './money'

describe('formatDecimal', () => {
  it('groups thousands and keeps centavos exact', () => {
    expect(formatDecimal('9993.25')).toBe('9,993.25')
    expect(formatDecimal('10023.2')).toBe('10,023.20')
    expect(formatDecimal('600')).toBe('600.00')
  })
  it('truncates rather than rounds', () => {
    expect(formatDecimal('9976.309')).toBe('9,976.30')
  })
  it('rejects non-decimal input', () => {
    expect(() => formatDecimal('1e3')).toThrow()
  })
  it('formats MXN', () => {
    expect(formatMXN('9976.30')).toBe('MX$9,976.30')
  })
})

import { formatAmount } from './money'

describe('formatAmount', () => {
  it('formats fiat with symbols and crypto with codes', () => {
    expect(formatAmount('ARS', '1049621.00')).toBe('AR$1,049,621.00')
    expect(formatAmount('USDC', '600')).toBe('600.00 USDC')
    expect(formatAmount('BTC', '0.00198440')).toBe('0.0019844 BTC')
  })
})
