import { useState } from 'react'
import { api, ApiError } from '../api/client'
import { type Authorization, TERMINAL_STATUSES } from '../api/types'
import { Receipt } from '../components/Receipt'
import { StatusPill } from '../components/StatusPill'
import { Timeline } from '../components/Timeline'
import { headline, minimumText, modeLabel, recipientText } from '../lib/auth'
import { formatDecimal } from '../lib/money'
import { formatInTz } from '../lib/time'
import { usePolling } from '../lib/usePolling'

export function WatchDetail({
  id,
  refreshKey,
  onLoaded,
}: {
  id: string
  refreshKey: number
  onLoaded?: (a: Authorization) => void
}) {
  const [auth, setAuth] = useState<Authorization | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [canceling, setCanceling] = useState(false)

  const live = !auth || !TERMINAL_STATUSES.has(auth.status)
  usePolling(
    async () => {
      try {
        const a = await api<Authorization>(`/authorizations/${id}`)
        setAuth(a)
        onLoaded?.(a)
      } catch (e) {
        setError(e instanceof ApiError ? e.message : String(e))
      }
    },
    2000,
    live,
    `${id}:${refreshKey}`,
  )

  async function checkNow() {
    setCanceling(true)
    try {
      setAuth(
        await api<Authorization>(`/authorizations/${id}/check`, {
          method: 'POST',
        }),
      )
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e))
    } finally {
      setCanceling(false)
    }
  }

  async function cancel() {
    if (!window.confirm('Cancel this watch? Nothing will be converted.')) return
    setCanceling(true)
    try {
      setAuth(
        await api<Authorization>(`/authorizations/${id}/cancel`, {
          method: 'POST',
        }),
      )
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e))
    } finally {
      setCanceling(false)
    }
  }

  if (error && !auth) return <p role="alert">{error}</p>
  if (!auth) return <p>Loading…</p>
  const tz = auth.terms.time_zone

  return (
    <section className="space-y-5" aria-labelledby="detail-title">
      <header className="flex flex-wrap items-center gap-3">
        <h2 id="detail-title" className="text-xl font-semibold">
          {headline(auth)}
        </h2>
        <StatusPill status={auth.status} />
        <span className="text-xs uppercase tracking-wide text-neutral-500">{modeLabel(auth)}</span>
      </header>

      {error && (
        <p role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-800 dark:bg-red-950/40 dark:text-red-200">
          {error}
        </p>
      )}

      <div className="grid gap-4 md:grid-cols-[1.2fr_1fr]">
        <div className="rounded-xl border border-neutral-200 p-4 dark:border-neutral-800" aria-live="polite">
          <h3 className="text-sm font-semibold text-neutral-500">Status</h3>
          <p className="mt-1">{auth.last_reason ?? 'Waiting for first check…'}</p>
          {(auth.mode === 'notify' || auth.mode === 'auto') && (
            <dl className="mt-3 grid grid-cols-2 gap-2 text-sm">
              <div>
                <dt className="text-neutral-500">Last check</dt>
                <dd>{auth.last_check_at ? formatInTz(auth.last_check_at, tz, { date: false }) : '-'}</dd>
              </div>
              <div>
                <dt className="text-neutral-500">Next check</dt>
                <dd>{auth.next_check_at ? formatInTz(auth.next_check_at, tz, { date: false }) : '-'}</dd>
              </div>
            </dl>
          )}
          {auth.can_cancel && auth.contact && (
            <button
              type="button"
              onClick={checkNow}
              disabled={canceling}
              className="mr-2 mt-4 rounded-md bg-violet-600 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
            >
              Check now
            </button>
          )}
          {auth.can_cancel && (
            <button
              type="button"
              onClick={cancel}
              disabled={canceling}
              className="mt-4 rounded-md border border-red-300 px-3 py-1.5 text-sm text-red-700 hover:bg-red-50 disabled:opacity-50 dark:border-red-800 dark:text-red-300 dark:hover:bg-red-950/40"
            >
              Cancel watch
            </button>
          )}
          {(auth.status === 'claimed' || auth.status === 'executing') && (
            <p className="mt-3 text-sm text-neutral-500">Execution is claimed; this can no longer be canceled.</p>
          )}
        </div>

        <div className="rounded-xl border border-neutral-200 p-4 text-sm dark:border-neutral-800">
          <h3 className="font-semibold text-neutral-500">Confirmed terms</h3>
          <dl className="mt-2 space-y-1.5">
            <div>
              <dt className="inline text-neutral-500">Total debit: </dt>
              <dd className="inline font-mono">{formatDecimal(auth.terms.amount_usdc)} USDC</dd>
            </div>
            <div>
              <dt className="inline text-neutral-500">{auth.mode === 'send' ? 'They receive at least: ' : 'Minimum payout: '}</dt>
              <dd className="inline font-mono">{minimumText(auth)}</dd>
            </div>
            {auth.terms.deadline_display && (
              <div>
                <dt className="inline text-neutral-500">Deadline: </dt>
                <dd className="inline">{auth.terms.deadline_display}</dd>
              </div>
            )}
            <div>
              <dt className="inline text-neutral-500">To: </dt>
              <dd className="inline">{recipientText(auth)}</dd>
            </div>
            {auth.intent_text && (
              <div>
                <dt className="inline text-neutral-500">Your words: </dt>
                <dd className="inline italic">“{auth.intent_text}”</dd>
              </div>
            )}
          </dl>
        </div>
      </div>

      <Receipt auth={auth} />

      {auth.status === 'notified' && (
        <a
          href="#/compare"
          className="inline-block rounded-md bg-emerald-600 px-4 py-2 font-medium text-white hover:bg-emerald-700"
        >
          Review current quotes and convert now
        </a>
      )}

      <div>
        <h3 className="mb-3 font-semibold">Decision history</h3>
        <Timeline events={auth.events} tz={tz} />
      </div>
    </section>
  )
}
