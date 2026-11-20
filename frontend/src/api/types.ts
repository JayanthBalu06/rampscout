import type { Decimal } from './client'

export interface Destination {
  id: string
  alias: string
  bank_name: string
  masked_account: string
  currency: string
  rail: string
}

export interface FeeBreakdown {
  input_usdc: Decimal
  usdc_fee: Decimal
  gas_cost_usdc: Decimal
  gas_sponsored: boolean
  usdc_converted: Decimal
  rate_mxn_per_usdc: Decimal
  gross_mxn: Decimal
  mxn_withdrawal_fee: Decimal
  net_mxn: Decimal
}

export interface Quote {
  quote_id: string
  provider_id: string
  route_id: string
  route_name: string
  rank: number | null
  net_mxn: Decimal
  breakdown: FeeBreakdown
  eta_seconds: number
  estimated_arrival: string
  issued_at: string
  expires_at: string
  source: string
}

export interface Excluded {
  quote: Quote
  reasons: string[]
  detail: string
}

export interface ProviderError {
  provider_id: string
  route_id: string
  kind: 'timeout' | 'unavailable' | 'error'
  message: string
}

export interface ClockInfo {
  now: string
  tick: number
  display_tz: string
  mode: 'fixture' | 'system'
}

export interface Settlement {
  mode: 'testnet' | 'simulated'
  reason: string
  chain_id: number
  network: string
  token_contract: string
  transfer_scale: Decimal
}

export interface QuotesResponse {
  amount_usdc: Decimal
  corridor: string
  destination: Destination
  deadline: string | null
  clock: ClockInfo
  quotes: Quote[]
  best_quote_id: string | null
  excluded: Excluded[]
  provider_errors: ProviderError[]
  insight: string | null
  settlement: Settlement
}

export interface DemoState {
  session_id: string
  clock: ClockInfo
  chaos: Record<string, boolean>
  settlement: Settlement
}
