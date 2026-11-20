import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { FeeBreakdown } from './FeeBreakdown'

describe('FeeBreakdown', () => {
  it('shows the exact waterfall for route A at tick 0', () => {
    render(
      <FeeBreakdown
        b={{
          input_usdc: '600',
          usdc_fee: '2',
          gas_cost_usdc: '0',
          gas_sponsored: true,
          usdc_converted: '598',
          rate_mxn_per_usdc: '16.85',
          gross_mxn: '10076.30',
          mxn_withdrawal_fee: '100',
          net_mxn: '9976.30',
        }}
      />,
    )
    expect(screen.getByText('MX$10,076.30')).toBeTruthy()
    expect(screen.getByTestId('net').textContent).toBe('MX$9,976.30')
    expect(screen.getByText(/demo-sponsored/)).toBeTruthy()
  })
})
