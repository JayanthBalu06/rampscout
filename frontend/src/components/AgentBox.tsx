import { useState } from 'react'
import { api, ApiError } from '../api/client'
import type { AgentDraft, Contact, SendRoutesResponse } from '../api/types'
import { formatAmount, formatDecimal } from '../lib/money'
import { confirmContact, quoteRoutes, sendHref, startSendWatch, walletContact } from '../lib/sendApi'
import { PathChips } from './RouteView'

const EXAMPLES = [
  'Send 600 USDC to Mamá',
  'Send 600 USDC to Mamá when she gets at least 11,400 pesos by 11pm',
  'Send 50 USDC to Ana as BTC',
]

const MISSING: Record<string, string> = {
  amount: 'how much USDC',
  recipient: 'who to pay',
  receive_currency: 'what they receive',
  min_out: 'the minimum they should get',
  deadline: 'a deadline',
}

/** "Ask RampScout": plain English -> a reviewed send or send-when watch. */
export function AgentBox({ onCreated }: { onCreated: (authorizationId: string) => void }) {
  const [text, setText] = useState('')
  const [draft, setDraft] = useState<AgentDraft | null>(null)
  const [contact, setContact] = useState<Contact | null>(null)
  const [routes, setRoutes] = useState<SendRoutesResponse | null>(null)
  const [mode, setMode] = useState<'notify' | 'auto'>('notify')
  const [checked, setChecked] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function ask(input = text) {
    setBusy(true)
    setError(null)
    setDraft(null)
    setRoutes(null)
    setContact(null)
    setChecked(false)
    try {
      const d = await api<AgentDraft>('/agent/draft', { method: 'POST', body: JSON.stringify({ text: input }) })
      setDraft(d)
      if (d.mode !== 'send_now') setMode(d.mode)
      // Resolve the recipient so we can show what they'd get right now.
      let c: Contact | null = null
      if (d.contact_id) {
        c = (await api<Contact[]>('/contacts')).find((x) => x.id === d.contact_id) ?? null
      } else if (d.recipient_address && d.receive_currency) {
        c = await walletContact(d.recipient_address, d.receive_currency)
      }
      setContact(c)
      if (c && d.amount) setRoutes(await quoteRoutes(c.id, d.amount))
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  async function startWatch() {
    if (!draft || !contact || !draft.amount || !draft.min_out || !draft.deadline_utc) return
    setBusy(true)
    setError(null)
    try {
      if (contact.status === 'pending') await confirmContact(contact.id)
      const a = await startSendWatch({
        contact_id: contact.id,
        amount_usdc: draft.amount,
        min_out: draft.min_out,
        deadline: draft.deadline_utc,
        time_zone: draft.time_zone ?? 'America/Mexico_City',
        mode,
        intent_text: text.trim() || undefined,
      })
      onCreated(a.id)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const best = routes?.routes[0]
  const ready = draft && draft.missing.length === 0 && contact
  const short = best && draft?.min_out ? Number(best.amount_out) < Number(draft.min_out) : false // display only

  return (
    <section aria-labelledby="agent-title" className="space-y-3 rounded-2xl border border-violet-300 bg-violet-50/60 p-4 dark:border-violet-900 dark:bg-violet-950/20">
      <div className="flex items-center gap-2">
        <span aria-hidden className="flex h-7 w-7 items-center justify-center rounded-full bg-violet-600 text-sm text-white">
          ✦
        </span>
        <h2 id="agent-title" className="font-semibold">
          Ask RampScout
        </h2>
        <span className="text-xs text-neutral-500">AI agent · drafts only; you confirm</span>
      </div>
      <form
        onSubmit={(e) => {
          e.preventDefault()
          if (text.trim()) void ask()
        }}
        className="flex gap-2"
      >
        <input
          aria-label="Ask RampScout"
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Send 600 USDC to Mamá when she gets at least 11,400 pesos by 11pm"
          className="min-w-0 flex-1 rounded-lg border border-violet-300 bg-white px-3 py-2 text-sm dark:border-violet-800 dark:bg-neutral-950"
        />
        <button type="submit" disabled={busy || !text.trim()} className="rounded-lg bg-violet-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-50">
          {busy ? '…' : 'Ask'}
        </button>
      </form>
      {!draft && (
        <div className="flex flex-wrap gap-1.5">
          {EXAMPLES.map((ex) => (
            <button
              key={ex}
              type="button"
              onClick={() => {
                setText(ex)
                void ask(ex)
              }}
              className="rounded-full border border-violet-300 bg-white px-2.5 py-1 text-xs text-violet-800 hover:bg-violet-100 dark:border-violet-800 dark:bg-neutral-950 dark:text-violet-200"
            >
              {ex}
            </button>
          ))}
        </div>
      )}
      {error && (
        <p role="alert" className="text-sm text-red-700 dark:text-red-300">
          {error}
        </p>
      )}

      {draft && (
        <div aria-live="polite" className="space-y-3 rounded-xl bg-white p-4 text-sm dark:bg-neutral-950">
          <p className="text-xs text-neutral-500">
            Drafted by {draft.source === 'claude' ? `Claude (${draft.model})` : 'the rules parser'}
            {draft.model_note ? `. ${draft.model_note.replace(/\.$/, '')}` : ''}. Review before confirming.
          </p>
          <p className="text-base">
            <strong>{draft.mode === 'send_now' ? 'Send now: ' : 'Send when the price is right: '}</strong>
            {draft.amount ? `${formatDecimal(draft.amount)} USDC` : '? USDC'} → <strong>{draft.recipient_name ?? '?'}</strong>
            {draft.receive_currency && ` (receives ${draft.receive_currency})`}
          </p>
          {draft.mode !== 'send_now' && (
            <ul className="space-y-0.5 text-neutral-700 dark:text-neutral-300">
              <li>
                Only if they'd receive at least <strong>{draft.min_out && draft.receive_currency ? formatAmount(draft.receive_currency, draft.min_out) : '?'}</strong>
              </li>
              <li>Deadline: {draft.deadline_display ?? '?'}</li>
            </ul>
          )}
          {draft.missing.length > 0 && (
            <p className="text-amber-800 dark:text-amber-300">Missing: {draft.missing.map((m) => MISSING[m] ?? m).join(', ')}. Rephrase and ask again.</p>
          )}
          {draft.ambiguities.map((a, i) => (
            <p key={i} className="text-amber-800 dark:text-amber-300">
              ❓ {a.question}
            </p>
          ))}
          {draft.assumptions.map((a, i) => (
            <p key={i} className="text-neutral-500">
              • {a}
            </p>
          ))}

          {best && routes && (
            <div className="rounded-lg bg-neutral-50 p-3 dark:bg-neutral-900">
              <p className="text-xs text-neutral-500">Right now, live Bitso:</p>
              <p className="flex flex-wrap items-center gap-2">
                <span className="font-mono font-semibold">{formatAmount(best.to_ccy, best.amount_out)}</span>
                <PathChips path={best.path} />
              </p>
              {draft.mode !== 'send_now' && (
                <p className={short ? 'text-amber-800 dark:text-amber-300' : 'text-emerald-700 dark:text-emerald-400'}>
                  {short ? 'Below your minimum, so the agent will wait and keep checking.' : 'Already meets your minimum.'}
                </p>
              )}
            </div>
          )}

          {ready && draft.mode === 'send_now' && contact && draft.amount && (
            <a href={sendHref(contact.id, draft.amount)} className="inline-block rounded-md bg-emerald-600 px-4 py-2 font-medium text-white">
              Review and send
            </a>
          )}

          {ready && draft.mode !== 'send_now' && contact && (
            <div className="space-y-2">
              <fieldset className="grid grid-cols-2 gap-2">
                <legend className="sr-only">When the target is met</legend>
                {(
                  [
                    ['notify', 'Notify me', 'Alert only; nothing sends.'],
                    ['auto', 'Auto-send', 'Sends automatically, never below your minimum.'],
                  ] as const
                ).map(([v, label, hint]) => (
                  <label key={v} className={`cursor-pointer rounded-lg border p-2 ${mode === v ? 'border-emerald-500 bg-emerald-50 dark:bg-emerald-950/30' : 'border-neutral-300 dark:border-neutral-700'}`}>
                    <input type="radio" name="agent-mode" className="mr-1.5" checked={mode === v} onChange={() => setMode(v)} />
                    <span className="font-medium">{label}</span>
                    <span className="block text-xs text-neutral-500">{hint}</span>
                  </label>
                ))}
              </fieldset>
              {contact.status === 'pending' && (
                <label className="flex items-start gap-2 rounded-lg bg-amber-50 p-2 text-amber-900 dark:bg-amber-950/40 dark:text-amber-200">
                  <input type="checkbox" checked={checked} onChange={(e) => setChecked(e.target.checked)} className="mt-0.5" />
                  <span>New address {contact.wallet_address}. I've checked every character.</span>
                </label>
              )}
              <button
                type="button"
                onClick={startWatch}
                disabled={busy || (contact.status === 'pending' && !checked)}
                className="rounded-md bg-emerald-600 px-4 py-2 font-medium text-white disabled:opacity-50"
              >
                Confirm and start watching
              </button>
            </div>
          )}
        </div>
      )}
    </section>
  )
}
