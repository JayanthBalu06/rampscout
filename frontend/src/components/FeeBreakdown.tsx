import type { FeeBreakdown as FB } from '../api/types'
import { formatDecimal, formatMXN } from '../lib/money'

/** The waterfall that explains *why* a route pays what it pays. */
export function FeeBreakdown({ b }: { b: FB }) {
  const rows: Array<[string, string, string?]> = [
    ['Budget', `${formatDecimal(b.input_usdc)} USDC`],
    ['Provider fee', `− ${formatDecimal(b.usdc_fee)} USDC`, 'deducted from your USDC'],
  ]
  if (!b.gas_sponsored) rows.push(['Network gas', `− ${formatDecimal(b.gas_cost_usdc, 6)} USDC`])
  rows.push(
    ['Converted', `${formatDecimal(b.usdc_converted)} USDC`],
    ['Rate', `× ${b.rate_mxn_per_usdc} MXN/USDC`, 'spread already included'],
    ['Gross pesos', formatMXN(b.gross_mxn)],
    ['Withdrawal fee', `− ${formatMXN(b.mxn_withdrawal_fee)}`, 'charged in MXN'],
  )
  return (
    <div className="text-sm">
      <dl className="divide-y divide-neutral-200 dark:divide-neutral-800">
        {rows.map(([label, value, hint]) => (
          <div key={label} className="flex items-baseline justify-between gap-4 py-1.5">
            <dt className="text-neutral-600 dark:text-neutral-400">
              {label}
              {hint && <span className="ml-1 text-xs text-neutral-400 dark:text-neutral-500">({hint})</span>}
            </dt>
            <dd className="font-mono tabular-nums">{value}</dd>
          </div>
        ))}
        <div className="flex items-baseline justify-between gap-4 py-2 font-semibold">
          <dt>Recipient gets</dt>
          <dd className="font-mono tabular-nums" data-testid="net">
            {formatMXN(b.net_mxn)}
          </dd>
        </div>
      </dl>
      {b.gas_sponsored && (
        <p className="mt-1 text-xs text-neutral-500">
          Network gas: <strong>demo-sponsored</strong>, paid by RampScout's test wallet and not deducted.
        </p>
      )}
    </div>
  )
}
