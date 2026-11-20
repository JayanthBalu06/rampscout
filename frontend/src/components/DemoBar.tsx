import type { DemoState } from '../api/types'
import { formatInTz } from '../lib/time'

const CHAOS: Array<[string, string]> = [
  ['provider_a_down', 'Route A down'],
  ['provider_b_down', 'Route B down'],
  ['provider_b_timeout', 'Route B times out'],
]

interface Props {
  state: DemoState | null
  busy: boolean
  onAdvance: () => void
  onReset: () => void
  onChaos: (flag: string, on: boolean) => void
}

export function DemoBar({ state, busy, onAdvance, onReset, onChaos }: Props) {
  return (
    <section
      aria-label="Demo controls"
      className="rounded-xl border border-violet-300 bg-violet-50 px-4 py-3 text-sm dark:border-violet-800 dark:bg-violet-950/40"
    >
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <span className="font-semibold text-violet-900 dark:text-violet-200">Demo clock</span>
        <span className="tabular-nums" aria-live="polite">
          {state ? `${formatInTz(state.clock.now, state.clock.display_tz)} · tick ${state.clock.tick}` : '…'}
        </span>
        <div className="ml-auto flex gap-2">
          <button
            type="button"
            onClick={onAdvance}
            disabled={busy}
            className="rounded-md bg-violet-700 px-3 py-1.5 font-medium text-white hover:bg-violet-800 disabled:opacity-50"
          >
            Advance 1 tick
          </button>
          <button
            type="button"
            onClick={onReset}
            disabled={busy}
            className="rounded-md border border-violet-400 px-3 py-1.5 hover:bg-violet-100 disabled:opacity-50 dark:hover:bg-violet-900"
          >
            Reset
          </button>
        </div>
      </div>
      <fieldset className="mt-2 flex flex-wrap gap-x-4 gap-y-1">
        <legend className="sr-only">Failure injection</legend>
        <span className="text-violet-900 dark:text-violet-300">Chaos:</span>
        {CHAOS.map(([flag, label]) => (
          <label key={flag} className="inline-flex items-center gap-1.5">
            <input
              type="checkbox"
              checked={!!state?.chaos[flag]}
              onChange={(e) => onChaos(flag, e.target.checked)}
              disabled={busy}
            />
            {label}
          </label>
        ))}
      </fieldset>
    </section>
  )
}
