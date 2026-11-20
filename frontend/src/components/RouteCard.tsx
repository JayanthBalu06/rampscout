import type { Quote } from '../api/types'
import { formatMXN } from '../lib/money'
import { formatInTz, minutes } from '../lib/time'
import { FeeBreakdown } from './FeeBreakdown'

interface Props {
  quote: Quote
  best: boolean
  highestRate: boolean
  tz: string
  onConvert?: () => void
}

export function RouteCard({ quote, best, highestRate, tz, onConvert }: Props) {
  return (
    <article
      aria-label={`${quote.route_name}${best ? ', best payout' : ''}`}
      className={`rounded-xl border p-5 ${
        best
          ? 'border-emerald-500 bg-emerald-50/50 dark:border-emerald-600 dark:bg-emerald-950/30'
          : 'border-neutral-200 dark:border-neutral-800'
      }`}
    >
      <header className="flex flex-wrap items-center gap-2">
        <h3 className="font-semibold">{quote.route_name}</h3>
        {best && (
          <span className="rounded-full bg-emerald-600 px-2 py-0.5 text-xs font-medium text-white">Best payout</span>
        )}
        {highestRate && !best && (
          <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-900 dark:bg-amber-900/50 dark:text-amber-200">
            Higher rate, fewer pesos
          </span>
        )}
        <span className="ml-auto rounded border border-dashed border-neutral-400 px-1.5 py-0.5 text-[11px] uppercase tracking-wide text-neutral-500">
          Synthetic quote
        </span>
      </header>

      <p className="mt-3 text-3xl font-semibold tabular-nums tracking-tight">{formatMXN(quote.net_mxn)}</p>
      <p className="text-sm text-neutral-500">
        estimated to the bank · rate {quote.breakdown.rate_mxn_per_usdc} MXN/USDC
      </p>

      <dl className="mt-3 grid grid-cols-2 gap-2 text-sm">
        <div>
          <dt className="text-neutral-500">Arrives by</dt>
          <dd>
            {formatInTz(quote.estimated_arrival, tz, { date: false })}{' '}
            <span className="text-neutral-500">(~{minutes(quote.eta_seconds)})</span>
          </dd>
        </div>
        <div>
          <dt className="text-neutral-500">Quote expires</dt>
          <dd>{formatInTz(quote.expires_at, tz, { date: false, seconds: true })}</dd>
        </div>
      </dl>

      <details className="group mt-3">
        <summary className="cursor-pointer select-none text-sm font-medium text-emerald-700 hover:underline dark:text-emerald-400">
          Fee breakdown
        </summary>
        <div className="mt-2">
          <FeeBreakdown b={quote.breakdown} />
        </div>
      </details>
      <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
        <p className="font-mono text-[11px] text-neutral-400">{quote.quote_id}</p>
        {onConvert && (
          <button
            type="button"
            onClick={onConvert}
            className={`rounded-md px-3 py-1.5 text-sm font-medium ${
              best
                ? 'bg-emerald-600 text-white hover:bg-emerald-700'
                : 'border border-neutral-300 hover:bg-neutral-50 dark:border-neutral-700 dark:hover:bg-neutral-900'
            }`}
          >
            Convert now
          </button>
        )}
      </div>
    </article>
  )
}
