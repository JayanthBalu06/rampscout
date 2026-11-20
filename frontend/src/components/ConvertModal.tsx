import { useEffect, useRef, useState } from 'react'
import { api, ApiError } from '../api/client'
import type { ApiErrorDetails, Authorization, Destination, Quote, Settlement } from '../api/types'
import { formatDecimal, formatMXN } from '../lib/money'
import { formatInTz } from '../lib/time'
import { FeeBreakdown } from './FeeBreakdown'

interface Props {
  quote: Quote
  destination: Destination
  settlement: Settlement
  onchainAmount: string
  tz: string
  onClose: () => void
  onDone: (authorizationId: string) => void
}

/** "Convert now" confirmation. The exact quote is part of the authorization; if it
 * changes, the user must confirm the new one (a new idempotency key). */
export function ConvertModal({ quote: initial, destination, settlement, onchainAmount, tz, onClose, onDone }: Props) {
  const ref = useRef<HTMLDialogElement>(null)
  const [quote, setQuote] = useState(initial)
  const [changed, setChanged] = useState(false)
  const [key, setKey] = useState(() => crypto.randomUUID())
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const d = ref.current
    d?.showModal()
    return () => d?.close()
  }, [])

  async function confirm() {
    setBusy(true)
    setError(null)
    try {
      const auth = await api<Authorization>('/authorizations', {
        method: 'POST',
        headers: { 'Idempotency-Key': key },
        body: JSON.stringify({
          mode: 'immediate',
          amount_usdc: quote.breakdown.input_usdc,
          min_payout_mxn: quote.net_mxn,
          destination_id: destination.id,
          time_zone: tz,
          selected_quote_id: quote.quote_id,
        }),
      })
      onDone(auth.id)
    } catch (e) {
      if (e instanceof ApiError && e.code === 'quote_changed') {
        const fresh = (e.details as ApiErrorDetails | undefined)?.fresh_quote
        if (fresh) {
          setQuote(fresh)
          setChanged(true)
          setKey(crypto.randomUUID()) // new terms -> new confirmation
        }
        setError(e.message)
      } else {
        setError(e instanceof ApiError ? e.message : String(e))
      }
    } finally {
      setBusy(false)
    }
  }

  const amount = formatDecimal(quote.breakdown.input_usdc)
  return (
    <dialog
      ref={ref}
      onCancel={onClose}
      aria-labelledby="convert-title"
      className="m-auto w-[min(34rem,calc(100vw-2rem))] rounded-2xl border border-neutral-200 bg-white p-0 text-neutral-900 shadow-2xl backdrop:bg-black/40 dark:border-neutral-800 dark:bg-neutral-950 dark:text-neutral-100"
    >
      <div className="space-y-4 p-6">
        <h2 id="convert-title" className="text-lg font-semibold">
          {changed ? 'Quote changed: review the new quote' : 'Confirm conversion'}
        </h2>
        {changed && (
          <p role="alert" className="rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-900 dark:bg-amber-950/40 dark:text-amber-200">
            The quote you saw expired. This is a fresh quote; nothing was converted. Confirm again to proceed.
          </p>
        )}
        <dl className="grid grid-cols-2 gap-3 text-sm">
          <div>
            <dt className="text-neutral-500">Exact input</dt>
            <dd className="font-mono text-base">{amount} USDC</dd>
          </div>
          <div>
            <dt className="text-neutral-500">Minimum payout</dt>
            <dd className="font-mono text-base">{formatMXN(quote.net_mxn)}</dd>
          </div>
          <div className="col-span-2">
            <dt className="text-neutral-500">Destination</dt>
            <dd>
              {destination.alias} · {destination.bank_name} {destination.masked_account}
            </dd>
          </div>
          <div className="col-span-2">
            <dt className="text-neutral-500">Quote</dt>
            <dd>
              {quote.route_name} · <span className="font-mono text-xs">{quote.quote_id}</span> · expires{' '}
              {formatInTz(quote.expires_at, tz, { date: false, seconds: true })}
            </dd>
          </div>
        </dl>
        <details>
          <summary className="cursor-pointer text-sm font-medium text-emerald-700 dark:text-emerald-400">Fee breakdown</summary>
          <div className="mt-2">
            <FeeBreakdown b={quote.breakdown} />
          </div>
        </details>
        <p className="text-xs text-neutral-500">
          {settlement.mode === 'testnet'
            ? `Sends ${formatDecimal(onchainAmount)} test USDC on Base Sepolia (demo scale ×${settlement.transfer_scale}) to Route ${quote.route_id}'s settlement wallet.`
            : `Settles on the local simulated ledger (no testnet signer configured).`}{' '}
          MXN conversion and bank deposit are simulated.
        </p>
        {error && !changed && (
          <p role="alert" className="text-sm text-red-700 dark:text-red-300">
            {error}
          </p>
        )}
        <div className="flex justify-end gap-2">
          <button type="button" onClick={onClose} className="rounded-md border border-neutral-300 px-4 py-2 dark:border-neutral-700">
            Cancel
          </button>
          <button
            type="button"
            onClick={confirm}
            disabled={busy}
            className="rounded-md bg-emerald-600 px-4 py-2 font-medium text-white hover:bg-emerald-700 disabled:opacity-50"
          >
            {busy ? 'Converting…' : changed ? 'Confirm new quote' : 'Confirm and convert'}
          </button>
        </div>
      </div>
    </dialog>
  )
}
