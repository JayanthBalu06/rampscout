import { useCallback, useEffect, useRef, useState } from 'react'
import { api, ApiError } from '../api/client'
import type { Destination, QuotesResponse } from '../api/types'
import { RouteCard } from '../components/RouteCard'
import { SettlementBanner } from '../components/SettlementBanner'
import { formatInTz } from '../lib/time'

const REASON_LABEL: Record<string, string> = {
  arrives_after_deadline: 'Arrives too late',
  quote_expired: 'Quote expired',
  over_budget: 'Over budget',
  unsupported_destination: 'Destination not supported',
  payout_not_positive: 'Fees exceed amount',
}

export function Compare({ refreshKey }: { refreshKey: number }) {
  const [destinations, setDestinations] = useState<Destination[]>([])
  const [amount, setAmount] = useState('600')
  const [deadlineLocal, setDeadlineLocal] = useState('')
  const [data, setData] = useState<QuotesResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    api<Destination[]>('/destinations').then(setDestinations, (e: Error) => setError(e.message))
  }, [])

  const destination = destinations[0]
  const tz = data?.clock.display_tz ?? 'America/Mexico_City'

  const fetchQuotes = useCallback(async () => {
    if (!destination) return
    setLoading(true)
    setError(null)
    try {
      const body: Record<string, string> = { amount_usdc: amount.trim(), destination_id: destination.id }
      if (deadlineLocal) {
        body.deadline_local = deadlineLocal.length === 16 ? `${deadlineLocal}:00` : deadlineLocal
        body.time_zone = tz
      }
      setData(await api<QuotesResponse>('/quotes', { method: 'POST', body: JSON.stringify(body) }))
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [destination, amount, deadlineLocal, tz])

  // Re-quote when the destination loads or the demo clock / chaos flags change.
  const fetchRef = useRef(fetchQuotes)
  useEffect(() => {
    fetchRef.current = fetchQuotes
  })
  useEffect(() => {
    void fetchRef.current()
  }, [destination, refreshKey])

  // Ordering only (badge placement); money values themselves are never parsed to numbers.
  const highestRateId = data?.quotes.length
    ? [...data.quotes].sort((a, b) => Number(b.breakdown.rate_mxn_per_usdc) - Number(a.breakdown.rate_mxn_per_usdc))[0]
        .quote_id
    : null

  return (
    <section aria-labelledby="compare-title" className="space-y-5">
      <h2 id="compare-title" className="text-xl font-semibold">
        Compare routes
      </h2>

      <form
        onSubmit={(e) => {
          e.preventDefault()
          void fetchQuotes()
        }}
        className="grid gap-4 rounded-xl border border-neutral-200 p-4 sm:grid-cols-[1fr_1fr_auto] dark:border-neutral-800"
      >
        <label className="text-sm">
          <span className="font-medium">Total budget (USDC)</span>
          <input
            inputMode="decimal"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            className="mt-1 w-full rounded-md border border-neutral-300 bg-transparent px-3 py-2 font-mono dark:border-neutral-700"
          />
        </label>
        <label className="text-sm">
          <span className="font-medium">Must arrive by (optional, {tz.replace('_', ' ')})</span>
          <input
            type="datetime-local"
            value={deadlineLocal}
            onChange={(e) => setDeadlineLocal(e.target.value)}
            className="mt-1 w-full rounded-md border border-neutral-300 bg-transparent px-3 py-2 dark:border-neutral-700"
          />
        </label>
        <button
          type="submit"
          disabled={loading || !destination}
          className="self-end rounded-md bg-emerald-600 px-4 py-2 font-medium text-white hover:bg-emerald-700 disabled:opacity-50"
        >
          {loading ? 'Quoting…' : 'Get quotes'}
        </button>
        {destination && (
          <p className="text-sm text-neutral-500 sm:col-span-3">
            Paying out to <strong className="text-neutral-800 dark:text-neutral-200">{destination.alias}</strong> ·{' '}
            {destination.bank_name} {destination.masked_account}
          </p>
        )}
      </form>

      {error && (
        <p role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-800 dark:bg-red-950/40 dark:text-red-200">
          {error}
        </p>
      )}

      {data && (
        <>
          <SettlementBanner s={data.settlement} />
          {data.insight && (
            <p className="rounded-lg border-l-4 border-emerald-500 bg-emerald-50 px-3 py-2 text-sm dark:bg-emerald-950/30">
              <strong>Why the ranking:</strong> {data.insight}
            </p>
          )}
          {data.deadline && (
            <p className="text-sm text-neutral-500">
              Deadline {formatInTz(data.deadline, tz)} · routes must land with a 2-minute safety margin.
            </p>
          )}

          <div className="grid items-start gap-4 md:grid-cols-2">
            {data.quotes.map((q) => (
              <RouteCard
                key={q.quote_id}
                quote={q}
                best={q.quote_id === data.best_quote_id}
                highestRate={q.quote_id === highestRateId}
                tz={tz}
              />
            ))}
          </div>
          {data.quotes.length === 0 && <p className="text-sm text-neutral-500">No eligible route right now.</p>}

          {data.excluded.length > 0 && (
            <div>
              <h3 className="mb-2 text-sm font-semibold">Excluded routes</h3>
              <ul className="space-y-1 text-sm">
                {data.excluded.map((e) => (
                  <li key={e.quote.quote_id} className="rounded-md bg-neutral-100 px-3 py-2 dark:bg-neutral-900">
                    <strong>{e.quote.route_name}</strong>: {e.reasons.map((r) => REASON_LABEL[r] ?? r).join(', ')}{' '}
                    <span className="text-neutral-500">({e.detail})</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {data.provider_errors.length > 0 && (
            <div>
              <h3 className="mb-2 text-sm font-semibold">Provider problems</h3>
              <ul className="space-y-1 text-sm">
                {data.provider_errors.map((e) => (
                  <li key={e.provider_id} className="rounded-md bg-red-50 px-3 py-2 dark:bg-red-950/30">
                    Route {e.route_id}: {e.kind === 'timeout' ? 'timed out' : e.kind} ({e.message})
                  </li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}
    </section>
  )
}
