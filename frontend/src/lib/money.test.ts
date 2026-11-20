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
