import { useEffect, useState } from 'react'
import { api, ApiError } from '../api/client'
import type { Authorization, AuthorizationRequest, Destination, IntentParseResponse, PreviewResponse } from '../api/types'
import { formatDecimal, formatMXN } from '../lib/money'

const EXAMPLE =
  'Convert 600 USDC if I can receive at least 10,000 pesos by Friday at 5 p.m. Mexico City time.'
const ZONES = ['America/Mexico_City', 'America/Chicago', 'America/New_York', 'America/Los_Angeles', 'UTC']
const FIELD_LABEL: Record<string, string> = {
  amount: 'amount',
  min_payout_mxn: 'minimum payout',
  deadline_local: 'deadline',
  destination: 'destination',
  time_zone: 'time zone',
  currency: 'currency',
}

interface Form {
  amount: string
  minPayout: string
  deadlineLocal: string
  timeZone: string
  destinationId: string
  mode: 'notify' | 'auto'
}

const inputCls =
  'mt-1 w-full rounded-md border border-neutral-300 bg-transparent px-3 py-2 dark:border-neutral-700'

export function WatchBuilder({ onCreated }: { onCreated: (id: string) => void }) {
  const [destinations, setDestinations] = useState<Destination[]>([])
  const [text, setText] = useState('')
  const [parsing, setParsing] = useState(false)
  const [parsed, setParsed] = useState<IntentParseResponse | null>(null)
  const [form, setForm] = useState<Form>({
    amount: '600',
    minPayout: '10000',
    deadlineLocal: '',
    timeZone: 'America/Mexico_City',
    destinationId: '',
    mode: 'notify',
  })
  const [preview, setPreview] = useState<PreviewResponse | null>(null)
  const [idemKey, setIdemKey] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api<Destination[]>('/destinations').then((d) => {
      setDestinations(d)
      setForm((f) => ({ ...f, destinationId: f.destinationId || d[0]?.id || '' }))
    })
  }, [])

  const set = <K extends keyof Form>(k: K, v: Form[K]) => {
    setForm((f) => ({ ...f, [k]: v }))
    setPreview(null) // any edit invalidates the review
  }

  async function draft() {
    setParsing(true)
    setError(null)
    try {
      const r = await api<IntentParseResponse>('/intents/parse', { method: 'POST', body: JSON.stringify({ text }) })
      setParsed(r)
      const d = r.draft
      setForm((f) => ({
        amount: d.amount ?? f.amount,
        minPayout: d.min_payout_mxn ?? f.minPayout,
        deadlineLocal: d.deadline_local ?? '',
        timeZone: d.time_zone ?? f.timeZone,
        destinationId: d.destination_id ?? f.destinationId,
        mode: d.mode,
      }))
      setPreview(null)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e))
    } finally {
      setParsing(false)
    }
  }

  function request(): AuthorizationRequest {
    return {
      mode: form.mode,
      amount_usdc: form.amount.trim(),
      min_payout_mxn: form.minPayout.trim(),
      destination_id: form.destinationId,
      deadline_local: form.deadlineLocal.length === 16 ? `${form.deadlineLocal}:00` : form.deadlineLocal,
      time_zone: form.timeZone,
      intent_text: parsed && text.trim() ? text.trim() : undefined,
    }
  }

  async function review(mode = form.mode) {
    setBusy(true)
    setError(null)
    try {
      const body = { ...request(), mode }
      setPreview(await api<PreviewResponse>('/authorizations/preview', { method: 'POST', body: JSON.stringify(body) }))
      setIdemKey(crypto.randomUUID()) // one key per reviewed set of terms
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  async function confirm() {
    setBusy(true)
    setError(null)
    try {
      const auth = await api<Authorization>('/authorizations', {
        method: 'POST',
        body: JSON.stringify(request()),
        headers: { 'Idempotency-Key': idemKey },
      })
      onCreated(auth.id)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const dest = destinations.find((d) => d.id === form.destinationId)

  return (
    <section aria-labelledby="watch-title" className="space-y-5">
      <div>
        <h2 id="watch-title" className="text-xl font-semibold">
          Watch for a target
        </h2>
        <p className="text-sm text-neutral-500">
          The agent re-checks quotes every tick and acts only within the terms you confirm. Waiting can end with a
          worse rate or no conversion at all.
        </p>
      </div>

      <div className="rounded-xl border border-neutral-200 p-4 dark:border-neutral-800">
        <label htmlFor="ask" className="text-sm font-medium">
          Ask the agent <span className="font-normal text-neutral-500">(optional; you'll review an editable draft)</span>
        </label>
        <textarea
          id="ask"
          rows={2}
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={EXAMPLE}
          className={inputCls}
        />
        <div className="mt-2 flex flex-wrap gap-2">
          <button
            type="button"
            onClick={draft}
            disabled={parsing || !text.trim()}
            className="rounded-md bg-neutral-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-neutral-700 disabled:opacity-40 dark:bg-white dark:text-neutral-900"
          >
            {parsing ? 'Drafting…' : 'Draft terms'}
          </button>
          <button type="button" onClick={() => setText(EXAMPLE)} className="text-sm text-emerald-700 hover:underline dark:text-emerald-400">
            Use the example
          </button>
        </div>
        {parsed && (
          <div className="mt-3 space-y-1 text-sm" aria-live="polite">
            <p className="text-xs text-neutral-500">
              Drafted by {parsed.source === 'claude' ? `Claude (${parsed.model})` : 'the rules parser'}
              {parsed.model_note ? `. ${parsed.model_note.replace(/\.$/, '')}` : ''}. Review before confirming.
            </p>
            {parsed.missing.length > 0 && (
              <p className="text-amber-800 dark:text-amber-300">
                Missing: {parsed.missing.map((m) => FIELD_LABEL[m] ?? m).join(', ')}. Fill these in below.
              </p>
            )}
            {parsed.ambiguities.map((a, i) => (
              <p key={i} className="text-amber-800 dark:text-amber-300">
                ❓ {a.question}
              </p>
            ))}
            {parsed.assumptions.map((a, i) => (
              <p key={i} className="text-neutral-500">
                • {a}
              </p>
            ))}
          </div>
        )}
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault()
          void review()
        }}
        className="grid gap-4 rounded-xl border border-neutral-200 p-4 sm:grid-cols-2 dark:border-neutral-800"
      >
        <label className="text-sm">
          <span className="font-medium">Convert (total USDC)</span>
          <input inputMode="decimal" required value={form.amount} onChange={(e) => set('amount', e.target.value)} className={`${inputCls} font-mono`} />
        </label>
        <label className="text-sm">
          <span className="font-medium">Only if I receive at least (MXN)</span>
          <input inputMode="decimal" required value={form.minPayout} onChange={(e) => set('minPayout', e.target.value)} className={`${inputCls} font-mono`} />
        </label>
        <label className="text-sm">
          <span className="font-medium">Deadline</span>
          <input type="datetime-local" required value={form.deadlineLocal} onChange={(e) => set('deadlineLocal', e.target.value)} className={inputCls} />
        </label>
        <label className="text-sm">
          <span className="font-medium">Time zone</span>
          <select value={form.timeZone} onChange={(e) => set('timeZone', e.target.value)} className={inputCls}>
            {ZONES.map((z) => (
              <option key={z} value={z}>
                {z.replace('_', ' ')}
              </option>
            ))}
          </select>
        </label>
        <label className="text-sm sm:col-span-2">
          <span className="font-medium">Pay out to</span>
          <select value={form.destinationId} onChange={(e) => set('destinationId', e.target.value)} className={inputCls}>
            {destinations.map((d) => (
              <option key={d.id} value={d.id}>
                {d.alias} · {d.bank_name} {d.masked_account}
              </option>
            ))}
          </select>
        </label>
        <div className="sm:col-span-2">
          <button
            type="submit"
            disabled={busy}
            className="rounded-md bg-emerald-600 px-4 py-2 font-medium text-white hover:bg-emerald-700 disabled:opacity-50"
          >
            Review terms
          </button>
        </div>
      </form>

      {error && (
        <p role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-800 dark:bg-red-950/40 dark:text-red-200">
          {error}
        </p>
      )}

      {preview && (
        <section aria-labelledby="review-title" className="rounded-xl border-2 border-emerald-500 p-5">
          <h3 id="review-title" className="text-lg font-semibold">
            Review and confirm
          </h3>
          <dl className="mt-3 grid gap-x-6 gap-y-3 text-sm sm:grid-cols-2">
            <div>
              <dt className="text-neutral-500">Total debit</dt>
              <dd className="font-mono text-base">{formatDecimal(preview.amount_usdc)} USDC</dd>
            </div>
            <div>
              <dt className="text-neutral-500">Minimum payout</dt>
              <dd className="font-mono text-base">{formatMXN(preview.min_payout_mxn)}</dd>
            </div>
            <div className="sm:col-span-2">
              <dt className="text-neutral-500">Deadline</dt>
              <dd className="text-base">{preview.deadline_display}</dd>
            </div>
            <div className="sm:col-span-2">
              <dt className="text-neutral-500">Destination</dt>
              <dd>
                {dest?.alias} · {preview.destination.bank_name} {preview.destination.masked_account}
              </dd>
            </div>
          </dl>

          <fieldset className="mt-4">
            <legend className="text-sm font-medium">When the target is met</legend>
            <div className="mt-2 grid gap-2 sm:grid-cols-2">
              {(
                [
                  ['notify', 'Notify me', 'One in-app alert. Nothing converts until you confirm.'],
                  [
                    'auto',
                    'Auto-convert',
                    `The agent re-checks a fresh quote, then sends ${formatDecimal(preview.onchain_amount_usdc, 2)} ${
                      preview.settlement.mode === 'testnet' ? 'test USDC on Base Sepolia' : 'USDC (simulated)'
                    }${preview.transfer_scale !== '1' ? ` (demo scale ×${preview.transfer_scale})` : ''}. Never below your minimum.`,
                  ],
                ] as const
              ).map(([value, label, hint]) => (
                <label
                  key={value}
                  className={`cursor-pointer rounded-lg border p-3 text-sm ${
                    form.mode === value ? 'border-emerald-500 bg-emerald-50 dark:bg-emerald-950/30' : 'border-neutral-300 dark:border-neutral-700'
                  }`}
                >
                  <input
                    type="radio"
                    name="mode"
                    value={value}
                    checked={form.mode === value}
                    onChange={() => {
                      setForm((f) => ({ ...f, mode: value }))
                      void review(value)
                    }}
                    className="mr-2"
                  />
                  <span className="font-medium">{label}</span>
                  <span className="mt-1 block text-neutral-500">{hint}</span>
                </label>
              ))}
            </div>
          </fieldset>

          <p className="mt-4 text-sm text-neutral-600 dark:text-neutral-400">
            Right now:{' '}
            {preview.current_best_net_mxn
              ? `Route ${preview.current_best_route} would pay ${formatMXN(preview.current_best_net_mxn)}, ${
                  preview.meets_target_now ? 'which already meets your minimum.' : 'below your minimum, so the agent will wait.'
                }`
              : 'no eligible route.'}{' '}
            MXN conversion and bank deposit are simulated in this prototype.
          </p>

          <div className="mt-4 flex gap-2">
            <button
              type="button"
              onClick={confirm}
              disabled={busy}
              className="rounded-md bg-emerald-600 px-4 py-2 font-medium text-white hover:bg-emerald-700 disabled:opacity-50"
            >
              Confirm and start watching
            </button>
            <button type="button" onClick={() => setPreview(null)} className="rounded-md border border-neutral-300 px-4 py-2 dark:border-neutral-700">
              Edit
            </button>
          </div>
        </section>
      )}
    </section>
  )
}
