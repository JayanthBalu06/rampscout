import type { Authorization } from '../api/types'
import { formatAmount, formatDecimal, formatMXN } from './money'

export const modeLabel = (a: Authorization) =>
  ({ send: 'Send', immediate: 'Convert now', auto: 'Auto-convert', notify: 'Notify' })[a.mode]

export const recipientText = (a: Authorization) =>
  a.contact
    ? `${a.contact.name} (${a.contact.account_masked})`
    : a.terms.destination
      ? `${a.terms.destination.alias} (${a.terms.destination.masked_account})`
      : '-'

export const minimumText = (a: Authorization) =>
  a.min_out && a.out_currency
    ? formatAmount(a.out_currency, a.min_out)
    : a.terms.min_payout_mxn
      ? formatMXN(a.terms.min_payout_mxn)
      : '-'

export const headline = (a: Authorization) =>
  a.mode === 'send'
    ? `Send: ${formatDecimal(a.terms.amount_usdc)} USDC → ${a.contact?.name ?? 'contact'}`
    : `${a.mode === 'immediate' ? 'Conversion' : 'Watch'}: ${formatDecimal(a.terms.amount_usdc)} USDC → ≥ ${minimumText(a)}`
