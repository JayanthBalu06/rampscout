import type { DecisionEvent } from '../api/types'
import { formatMXN } from '../lib/money'
import { formatInTz } from '../lib/time'

const META: Record<string, { label: string; dot: string }> = {
  confirmed: { label: 'You confirmed', dot: 'bg-neutral-500' },
  waiting_below_target: { label: 'Below target, waiting', dot: 'bg-sky-500' },
  no_eligible_route: { label: 'No eligible route', dot: 'bg-amber-500' },
  provider_error: { label: 'Provider problem', dot: 'bg-red-500' },
  matched: { label: 'Target met', dot: 'bg-emerald-500' },
  notified: { label: 'Notified you', dot: 'bg-emerald-600' },
  claimed: { label: 'Claimed for auto-convert', dot: 'bg-violet-500' },
  claim_released: { label: 'Re-check failed, claim released', dot: 'bg-amber-600' },
  execution_started: { label: 'Revalidated & executing', dot: 'bg-violet-600' },
  transfer_simulated: { label: 'Transfer (simulated)', dot: 'bg-violet-400' },
  payout_posted: { label: 'Payout posted (simulated)', dot: 'bg-emerald-600' },
  canceled: { label: 'Canceled', dot: 'bg-neutral-500' },
  expired: { label: 'Deadline reached', dot: 'bg-neutral-500' },
  check_failed: { label: 'Check failed, will retry', dot: 'bg-red-400' },
}

export function Timeline({ events, tz }: { events: DecisionEvent[]; tz: string }) {
  return (
    <ol className="relative space-y-4 border-l border-neutral-200 pl-5 dark:border-neutral-800" aria-label="Decision history">
      {events.map((e) => {
        const m = META[e.kind] ?? { label: e.kind, dot: 'bg-neutral-400' }
        return (
          <li key={e.seq} className="relative">
            <span className={`absolute -left-[1.6rem] top-1.5 h-2.5 w-2.5 rounded-full ring-4 ring-white dark:ring-neutral-950 ${m.dot}`} aria-hidden />
            <div className="flex flex-wrap items-baseline gap-x-2 text-sm">
              <span className="font-medium">{m.label}</span>
              <time className="text-xs text-neutral-500" dateTime={e.at}>
                {formatInTz(e.at, tz, { date: false })}
              </time>
              {e.best_net_mxn && (
                <span className="font-mono text-xs text-neutral-500">
                  best: Route {e.best_route} {formatMXN(e.best_net_mxn)}
                </span>
              )}
            </div>
            <p className="mt-0.5 text-sm text-neutral-600 dark:text-neutral-400">{e.reason}</p>
          </li>
        )
      })}
    </ol>
  )
}
