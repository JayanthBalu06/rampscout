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
  signer_address: string | null
  signer_usdc: string | null
  signer_eth: string | null
  explorer_tx_url: string | null
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
  onchain_amount_usdc: Decimal
}

export interface DemoState {
  session_id: string
  clock: ClockInfo
  chaos: Record<string, boolean>
  settlement: Settlement
}

export type Mode = 'immediate' | 'notify' | 'auto'

export interface IntentDraft {
  amount: Decimal | null
  currency: string | null
  min_payout_mxn: Decimal | null
  destination_id: string | null
  destination_alias: string | null
  deadline_local: string | null
  time_zone: string | null
  mode: 'notify' | 'auto'
}

export interface IntentParseResponse {
  draft: IntentDraft
  deadline_utc: string | null
  deadline_display: string | null
  missing: string[]
  ambiguities: Array<{ field: string; question: string }>
  assumptions: string[]
  source: 'claude' | 'rules'
  model: string | null
  model_note: string | null
}

export interface AuthorizationRequest {
  mode: Mode
  amount_usdc: Decimal
  min_payout_mxn: Decimal
  destination_id: string
  deadline_local?: string
  time_zone: string
  selected_quote_id?: string
  intent_text?: string
}

export interface PreviewResponse {
  mode: Mode
  amount_usdc: Decimal
  min_payout_mxn: Decimal
  destination: Destination
  deadline_utc: string | null
  deadline_display: string | null
  time_zone: string
  onchain_amount_usdc: Decimal
  transfer_scale: Decimal
  settlement: Settlement
  current_best_route: string | null
  current_best_net_mxn: Decimal | null
  meets_target_now: boolean
}

export interface DecisionEvent {
  seq: number
  at: string
  kind: string
  reason: string
  best_quote_id: string | null
  best_route: string | null
  best_net_mxn: Decimal | null
  payload: Record<string, unknown>
}

export interface Execution {
  id: string
  quote_id: string
  route_id: string
  input_usdc: Decimal
  quoted_net_mxn: Decimal
  onchain_amount_usdc: Decimal
  transfer_scale: Decimal
  settlement_mode: 'testnet' | 'simulated'
  chain_id: number | null
  token_contract: string | null
  recipient_address: string | null
  chain_status: string
  tx_hash: string | null
  explorer_url: string | null
  signer_address: string | null
  network: string
  broadcast_attempts: number
  payout_attempts: number
  block_number: number | null
  payout_status: string
  payout_mxn: Decimal | null
  payout_reference: string | null
  state_label: string
}

export interface Authorization {
  id: string
  mode: Mode
  status: string
  version: number
  can_cancel: boolean
  terms: {
    amount_usdc: Decimal
    currency: string
    min_payout_mxn: Decimal
    destination: Destination
    deadline_utc: string | null
    deadline_display: string | null
    time_zone: string
    selected_quote_id: string | null
  }
  intent_text: string | null
  confirmed_at: string
  closed_at: string | null
  last_check_at: string | null
  next_check_at: string | null
  last_reason: string | null
  last_best_route: string | null
  last_best_net_mxn: Decimal | null
  events: DecisionEvent[]
  execution: Execution | null
  executed_quote: Quote | null
  clock: ClockInfo
}

export interface AppNotification {
  id: string
  authorization_id: string
  kind: string
  title: string
  body: string
  at: string
  read: boolean
}

export const TERMINAL_STATUSES = new Set(['notified', 'completed', 'canceled', 'expired', 'requote_required', 'failed'])

export interface ApiErrorDetails {
  fresh_quote?: Quote | null
}
