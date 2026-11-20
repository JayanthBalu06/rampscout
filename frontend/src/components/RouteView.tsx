import type { Hop, RouteQuote } from '../api/types'
import { formatAmount } from '../lib/money'

const SOURCE: Record<Hop['source'], { label: string; cls: string }> = {
  live: { label: 'Live · Bitso', cls: 'border-emerald-500 text-emerald-700 dark:text-emerald-300' },
  recorded: { label: 'Recorded · Bitso', cls: 'border-sky-500 text-sky-700 dark:text-sky-300' },
  assumption: { label: 'Assumption', cls: 'border-amber-500 text-amber-700 dark:text-amber-300' },
  fixture: { label: 'Synthetic', cls: 'border-neutral-400 text-neutral-500' },
  'real-onchain': { label: 'Real · Base Sepolia', cls: 'border-sky-600 text-sky-700 dark:text-sky-300' },
  simulated: { label: 'Simulated', cls: 'border-amber-500 text-amber-700 dark:text-amber-300' },
}

export function SourceBadge({ source }: { source: Hop['source'] }) {
  const s = SOURCE[source]
  return (
    <span className={`whitespace-nowrap rounded border border-dashed px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide ${s.cls}`}>
      {s.label}
    </span>
  )
}

const KIND_LABEL: Record<Hop['kind'], string> = {
  transfer: 'Transfer',
  swap: 'Swap',
  orderbook: 'Trade',
  payout: 'Payout',
}

/** "USDC → USD → MXN" as chips. */
export function PathChips({ path }: { path: string }) {
  const parts = path.split(' → ')
  return (
    <span className="inline-flex flex-wrap items-center gap-1" aria-label={`Route ${path}`}>
      {parts.map((p, i) => (
        <span key={i} className="inline-flex items-center gap-1">
          {i > 0 && <span className="text-neutral-400">→</span>}
          <span className="rounded-md bg-neutral-100 px-1.5 py-0.5 font-mono text-xs font-semibold dark:bg-neutral-800">{p}</span>
        </span>
      ))}
    </span>
  )
}

export function HopTable({ route }: { route: RouteQuote }) {
  return (
    <ol className="space-y-2 text-sm">
      {route.hops.map((h, i) => (
        <li key={i} className="rounded-lg border border-neutral-200 p-2.5 dark:border-neutral-800">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs font-semibold text-neutral-500">
              {i + 1}. {KIND_LABEL[h.kind]}
            </span>
            <span className="font-medium">{h.venue}</span>
            <span className="ml-auto">
              <SourceBadge source={h.source} />
            </span>
          </div>
          <div className="mt-1 flex flex-wrap justify-between gap-x-4 font-mono text-xs tabular-nums">
            <span>
              {formatAmount(h.from_ccy, h.amount_in)} → {formatAmount(h.to_ccy, h.amount_out)}
            </span>
            <span className="text-neutral-500">
              {h.avg_price && h.from_ccy !== h.to_ccy && `@ ${h.avg_price} ${h.to_ccy}/${h.from_ccy}`}
              {h.fee !== '0' && !/^0(\.0+)?$/.test(h.fee) && ` · fee ${formatAmount(h.to_ccy, h.fee)}`}
            </span>
          </div>
          {h.note && <p className="mt-0.5 text-xs text-neutral-500">{h.note}</p>}
        </li>
      ))}
    </ol>
  )
}
