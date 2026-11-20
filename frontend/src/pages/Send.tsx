import { useEffect, useRef, useState } from 'react'
import { api, ApiError } from '../api/client'
import type { Authorization, Contact, SendRoutesResponse } from '../api/types'
import { HopTable, PathChips, SourceBadge } from '../components/RouteView'
import { formatAmount, formatDecimal } from '../lib/money'
import { formatInTz } from '../lib/time'
import { short, useWallet } from '../lib/useWallet'
import { confirmContact, startSendWatch } from '../lib/sendApi'
import { DECIMALS_HINT, suggestTarget } from '../lib/targets'

const TZ = 'America/Mexico_City'
const inputCls = 'mt-1 w-full rounded-md border border-neutral-300 bg-transparent px-3 py-2 dark:border-neutral-700'

export function ContactCard({ c, selected, onSelect }: { c: Contact; selected: boolean; onSelect: () => void }) {
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={selected}
      className={`w-full rounded-xl border p-3 text-left transition ${
        selected
          ? 'border-emerald-500 bg-emerald-50 dark:bg-emerald-950/30'
          : 'border-neutral-200 hover:border-neutral-400 dark:border-neutral-800'
      }`}
    >
      <div className="flex items-center gap-2">
        <span className="flex h-8 w-8 items-center justify-center rounded-full bg-neutral-200 text-sm font-semibold dark:bg-neutral-800">
          {c.name.slice(0, 1)}
        </span>
        <span className="font-medium">{c.name}</span>
        <span className="ml-auto rounded bg-neutral-100 px-1.5 py-0.5 font-mono text-xs dark:bg-neutral-800">{c.currency}</span>
      </div>
      <p className="mt-1 text-xs text-neutral-500">
        {c.kind === 'bank' ? `${c.bank_name} · ${c.account_masked}` : `Wallet · ${c.account_masked}`}
        {c.status === 'pending' && ' · pending confirmation'}
      </p>
    </button>
  )
}

export function AddContact({ onDone }: { onDone: (c: Contact) => void }) {
  const kind = 'bank' as const
  const [form, setForm] = useState({ name: '', currency: 'MXN', bank_name: '', account: '' })
  const [pending, setPending] = useState<Contact | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function create(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    try {
      const body = { name: form.name, kind, currency: form.currency, bank_name: form.bank_name, account: form.account }
      setPending(await api<Contact>('/contacts', { method: 'POST', body: JSON.stringify(body) }))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err))
    }
  }

  if (pending) {
    return (
      <div className="space-y-3 rounded-xl border-2 border-amber-400 p-4 text-sm">
        <p className="font-semibold">Confirm this contact</p>
        <p>
          <strong>{pending.name}</strong> receives <strong>{pending.currency}</strong>
          {pending.kind === 'bank' ? ` at ${pending.bank_name} ${pending.account_masked}` : ' at'}
        </p>
        {pending.wallet_address && <p className="break-all font-mono text-xs">{pending.wallet_address}</p>}
        <p className="text-xs text-neutral-500">
          Check every character. RampScout only ever sends to confirmed contacts; money sent to a wrong address can't be recovered.
        </p>
        <div className="flex gap-2">
          <button
            type="button"
            className="rounded-md bg-emerald-600 px-3 py-1.5 font-medium text-white"
            onClick={async () => onDone(await api<Contact>(`/contacts/${pending.id}/confirm`, { method: 'POST' }))}
          >
            Confirm contact
          </button>
          <button type="button" className="rounded-md border px-3 py-1.5" onClick={() => setPending(null)}>
            Edit
          </button>
        </div>
      </div>
    )
  }

  return (
    <form onSubmit={create} className="space-y-3 rounded-xl border border-neutral-200 p-4 text-sm dark:border-neutral-800">
      <label className="block">
        Name
        <input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className={inputCls} />
      </label>
      {kind === 'bank' && (
        <>
          <label className="block">
            Receives
            <select value={form.currency} onChange={(e) => setForm({ ...form, currency: e.target.value })} className={inputCls}>
              <option value="MXN">MXN · Mexico (CLABE)</option>
              <option value="ARS">ARS · Argentina</option>
              <option value="COP">COP · Colombia</option>
              <option value="BRL">BRL · Brazil</option>
            </select>
          </label>
          <label className="block">
            Bank
            <input required value={form.bank_name} onChange={(e) => setForm({ ...form, bank_name: e.target.value })} className={inputCls} />
          </label>
          <label className="block">
            {form.currency === 'MXN' ? 'CLABE (18 digits)' : 'Account number'}
            <input required inputMode="numeric" value={form.account} onChange={(e) => setForm({ ...form, account: e.target.value })} className={`${inputCls} font-mono`} />
          </label>
        </>
      )}
      {error && (
        <p role="alert" className="text-red-700 dark:text-red-300">
          {error}
        </p>
      )}
      <button type="submit" className="rounded-md bg-neutral-900 px-3 py-1.5 font-medium text-white dark:bg-white dark:text-neutral-900">
        Review contact
      </button>
    </form>
  )
}

const ADDRESS_RE = /^0x[0-9a-fA-F]{40}$/
const TOKENS = ['USDC', 'USDT', 'BTC', 'ETH'] as const

export function Send({ onSent, refreshKey }: { onSent: (id: string) => void; refreshKey: number }) {
  const { wallet } = useWallet(refreshKey)
  const [contacts, setContacts] = useState<Contact[]>([])
  const [to, setTo] = useState<'wallet' | 'bank'>('wallet')
  const [address, setAddress] = useState('')
  const [token, setToken] = useState<(typeof TOKENS)[number]>('USDC')
  const [bankId, setBankId] = useState<string | null>(null)
  const [pasted, setPasted] = useState<{ key: string; id: string } | null>(null)
  const [addingBank, setAddingBank] = useState(false)
  const [amount, setAmount] = useState('600')
  const [source, setSource] = useState<'live' | 'recorded'>('live')
  const [data, setData] = useState<SendRoutesResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [showAlts, setShowAlts] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [checked, setChecked] = useState(false)
  const [busy, setBusy] = useState(false)
  const keyRef = useRef(crypto.randomUUID())

  useEffect(() => {
    api<Contact[]>('/contacts').then((cs) => {
      setContacts(cs)
      // Prefill from the agent: #/send?to=<contactId>&amount=600
      const params = new URLSearchParams(window.location.hash.split('?')[1] ?? '')
      const amt = params.get('amount')
      if (amt) setAmount(amt)
      const c = cs.find((x) => x.id === params.get('to'))
      if (c?.kind === 'bank') {
        setTo('bank')
        setBankId(c.id)
      } else if (c?.wallet_address) {
        setTo('wallet')
        setAddress(c.wallet_address)
        setToken(c.currency as (typeof TOKENS)[number])
      }
    })
  }, [])

  const savedWallets = contacts.filter((c) => c.kind === 'wallet' && c.status === 'confirmed')
  const banks = contacts.filter((c) => c.kind === 'bank')

  // Pasted address + chosen token -> a (pending or existing) recipient on the server.
  const trimmed = address.trim()
  const addressValid = ADDRESS_RE.test(trimmed)
  const pasteKey = `${trimmed.toLowerCase()}|${token}`
  useEffect(() => {
    if (to !== 'wallet' || !ADDRESS_RE.test(trimmed)) return
    let cancelled = false
    api<Contact>('/contacts', {
      method: 'POST',
      body: JSON.stringify({ kind: 'wallet', currency: token, wallet_address: trimmed }),
    }).then(
      (c) => {
        if (cancelled) return
        setContacts((cs) => (cs.some((x) => x.id === c.id) ? cs.map((x) => (x.id === c.id ? c : x)) : [...cs, c]))
        setPasted({ key: `${trimmed.toLowerCase()}|${token}`, id: c.id })
      },
      (e) => !cancelled && setError(e instanceof ApiError ? e.message : String(e)),
    )
    return () => {
      cancelled = true
    }
  }, [to, trimmed, token])

  const contactId =
    to === 'wallet' ? (addressValid && pasted?.key === pasteKey ? pasted.id : null) : (bankId ?? banks[0]?.id ?? null)
  const addressError = to === 'wallet' && trimmed.length >= 42 && !addressValid ? 'That is not a valid address' : null

  // Best route, found automatically whenever who/what/how-much changes; refreshed before expiry.
  useEffect(() => {
    if (!contactId || !/^\d+(\.\d{1,6})?$/.test(amount.trim()) || Number(amount) <= 0) return
    let cancelled = false
    const load = async () => {
      setLoading(true)
      try {
        const r = await api<SendRoutesResponse>('/send/routes', {
          method: 'POST',
          body: JSON.stringify({ contact_id: contactId, amount_usdc: amount.trim(), source }),
        })
        if (!cancelled) {
          setData(r)
          setError(null)
          keyRef.current = crypto.randomUUID()
        }
      } catch (e) {
        if (!cancelled) setError(e instanceof ApiError ? e.message : String(e))
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    const t = window.setTimeout(load, 350)
    const every = window.setInterval(load, 20_000)
    return () => {
      cancelled = true
      window.clearTimeout(t)
      window.clearInterval(every)
    }
  }, [contactId, amount, source])

  const contact = contacts.find((c) => c.id === contactId)
  const best = data && contactId && data.contact.id === contactId ? data.routes[0] : undefined
  const isNew = contact?.status === 'pending'

  async function send() {
    if (!data || !best || !contact) return
    setBusy(true)
    setError(null)
    try {
      if (isNew) await api(`/contacts/${contact.id}/confirm`, { method: 'POST' })
      const a = await api<Authorization>('/send', {
        method: 'POST',
        headers: { 'Idempotency-Key': keyRef.current },
        body: JSON.stringify({ contact_id: contact.id, amount_usdc: data.amount_usdc, route_quote_id: best.route_quote_id }),
      })
      onSent(a.id)
    } catch (e) {
      if (e instanceof ApiError && e.code === 'route_changed') {
        const fresh = (e.details as { routes?: SendRoutesResponse } | undefined)?.routes
        if (fresh) setData(fresh)
        keyRef.current = crypto.randomUUID()
      }
      setError(e instanceof ApiError ? e.message : String(e))
    } finally {
      setBusy(false)
      setConfirming(false)
      setChecked(false)
    }
  }

  const tabCls = (on: boolean) =>
    `flex-1 rounded-md px-3 py-1.5 text-sm ${on ? 'bg-white font-medium shadow-sm dark:bg-neutral-800' : 'text-neutral-600 dark:text-neutral-400'}`

  return (
    <section aria-labelledby="send-title" className="space-y-5">
      <h2 id="send-title" className="text-xl font-semibold">
        Send
      </h2>

      <div className="rounded-2xl border border-neutral-200 p-4 dark:border-neutral-800">
        <p className="text-xs font-semibold uppercase tracking-wide text-neutral-500">From</p>
        <div className="mt-1 flex items-center justify-between gap-2">
          <span className="font-medium">
            Your wallet <span className="font-mono text-sm text-neutral-500">{wallet ? short(wallet.address) : '…'}</span>
          </span>
          <span className="font-mono text-sm tabular-nums">{wallet?.usdc != null ? `${formatDecimal(wallet.usdc, 2)} USDC` : ''}</span>
        </div>
      </div>

      <div className="space-y-3 rounded-2xl border border-neutral-200 p-4 dark:border-neutral-800">
        <p className="text-xs font-semibold uppercase tracking-wide text-neutral-500">To</p>
        <div role="tablist" className="flex gap-1 rounded-lg bg-neutral-100 p-1 dark:bg-neutral-900">
          <button role="tab" aria-selected={to === 'wallet'} type="button" className={tabCls(to === 'wallet')} onClick={() => setTo('wallet')}>
            Wallet address
          </button>
          <button role="tab" aria-selected={to === 'bank'} type="button" className={tabCls(to === 'bank')} onClick={() => setTo('bank')}>
            Bank account
          </button>
        </div>

        {to === 'wallet' ? (
          <>
            <label className="block text-sm">
              <span className="font-medium">Recipient address (Base Sepolia)</span>
              <input
                value={address}
                onChange={(e) => setAddress(e.target.value)}
                placeholder="0x…"
                spellCheck={false}
                className={`${inputCls} font-mono text-sm`}
              />
            </label>
            {savedWallets.length > 0 && (
              <div className="flex flex-wrap items-center gap-2 text-xs">
                <span className="text-neutral-500">Saved:</span>
                {savedWallets.map((c) => (
                  <button
                    key={c.id}
                    type="button"
                    onClick={() => {
                      setAddress(c.wallet_address ?? '')
                      setToken(c.currency as (typeof TOKENS)[number])
                    }}
                    className="rounded-full border border-neutral-300 px-2.5 py-1 hover:border-emerald-500 dark:border-neutral-700"
                  >
                    {c.name} · {c.currency}
                  </button>
                ))}
              </div>
            )}
            <fieldset>
              <legend className="text-sm font-medium">They receive</legend>
              <div className="mt-1 grid grid-cols-4 gap-2">
                {TOKENS.map((t) => (
                  <label key={t} className={`cursor-pointer rounded-lg border py-2 text-center font-mono text-sm ${token === t ? 'border-emerald-500 bg-emerald-50 font-semibold dark:bg-emerald-950/30' : 'border-neutral-300 dark:border-neutral-700'}`}>
                    <input type="radio" name="token" className="sr-only" checked={token === t} onChange={() => setToken(t)} />
                    {t}
                  </label>
                ))}
              </div>
            </fieldset>
          </>
        ) : (
          <div className="space-y-2">
            {banks.map((c) => (
              <ContactCard key={c.id} c={c} selected={c.id === contactId} onSelect={() => setBankId(c.id)} />
            ))}
            {addingBank ? (
              <AddContact
                onDone={(c) => {
                  setContacts((cs) => [...cs, c])
                  setBankId(c.id)
                  setAddingBank(false)
                }}
              />
            ) : (
              <button type="button" onClick={() => setAddingBank(true)} className="w-full rounded-xl border border-dashed border-neutral-300 p-3 text-sm text-neutral-600 hover:border-neutral-500 dark:border-neutral-700 dark:text-neutral-400">
                + New bank account
              </button>
            )}
          </div>
        )}
      </div>

      <div className="flex flex-wrap items-end gap-4 rounded-2xl border border-neutral-200 p-4 dark:border-neutral-800">
        <label className="text-sm">
          <span className="text-xs font-semibold uppercase tracking-wide text-neutral-500">Amount</span>
          <div className="mt-1 flex items-center gap-2">
            <input aria-label="You send (USDC)" inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} className="w-40 rounded-md border border-neutral-300 bg-transparent px-3 py-2 font-mono text-lg dark:border-neutral-700" />
            <span className="font-mono">USDC</span>
          </div>
        </label>
        <fieldset className="ml-auto flex items-center gap-1 rounded-lg bg-neutral-100 p-1 text-xs dark:bg-neutral-900">
          <legend className="sr-only">Market data</legend>
          {(['live', 'recorded'] as const).map((s) => (
            <label key={s} className={`cursor-pointer rounded-md px-2 py-1 ${source === s ? 'bg-white font-medium shadow-sm dark:bg-neutral-800' : ''}`}>
              <input type="radio" className="sr-only" checked={source === s} onChange={() => setSource(s)} />
              {s === 'live' ? 'Live Bitso' : 'Recorded snapshot'}
            </label>
          ))}
        </fieldset>
      </div>

      {(addressError ?? error) && (
        <p role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-800 dark:bg-red-950/40 dark:text-red-200">
          {addressError ?? error}
        </p>
      )}
      {data?.market.fell_back && (
        <p className="rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-900 dark:bg-amber-950/40 dark:text-amber-200">
          Bitso is unreachable right now, so these routes use the recorded snapshot.
        </p>
      )}

      {best && data && contact ? (
        <article aria-live="polite" className={`space-y-3 rounded-2xl border-2 border-emerald-500 p-5 ${loading ? 'opacity-70' : ''}`}>
          <div className="flex flex-wrap items-center gap-2 text-xs text-neutral-500">
            <span className="rounded-full bg-emerald-600 px-2 py-0.5 font-medium text-white">Best route</span>
            <span>
              {data.market.source === 'live' ? 'Live' : 'Recorded'} {data.market.venue} · as of{' '}
              {formatInTz(data.market.as_of, TZ, { date: data.market.source !== 'live', seconds: true })}
            </span>
            <span className="ml-auto">{data.routes.length} routes compared</span>
          </div>
          <div>
            <p className="text-sm text-neutral-500">{contact.name} receives</p>
            <p className="text-4xl font-semibold tabular-nums tracking-tight">{formatAmount(best.to_ccy, best.amount_out)}</p>
            {data.min_out && (
              <p className="text-sm text-neutral-500">
                guaranteed at least {formatAmount(best.to_ccy, data.min_out)} ({(data.slippage_bps / 100).toFixed(2)}% price protection) · ~
                {Math.max(1, Math.round(best.eta_seconds / 60))} min
              </p>
            )}
          </div>
          <PathChips path={best.path} />
          <details>
            <summary className="cursor-pointer text-sm font-medium text-emerald-700 dark:text-emerald-400">How this route works</summary>
            <div className="mt-2">
              <HopTable route={best} />
            </div>
          </details>
          <div className="flex flex-wrap items-center gap-3 pt-1">
            <button type="button" onClick={() => setConfirming(true)} disabled={busy || loading} className="rounded-md bg-emerald-600 px-5 py-2.5 font-medium text-white hover:bg-emerald-700 disabled:opacity-50">
              Send {formatDecimal(data.amount_usdc)} USDC
            </button>
            <span className="text-xs text-neutral-500">
              Onchain: {formatDecimal(data.onchain_amount_usdc, 2)} USDC
              {data.settlement.transfer_scale !== '1' && ` (demo scale ×${data.settlement.transfer_scale})`}
            </span>
          </div>
        </article>
      ) : (
        <p className="text-sm text-neutral-500">
          {loading ? 'Finding the best route…' : to === 'wallet' ? 'Paste a wallet address to see the best route.' : 'Choose a bank account.'}
        </p>
      )}

      {best && data && data.routes.length > 1 && (
        <div>
          <button type="button" onClick={() => setShowAlts((v) => !v)} className="text-sm font-medium text-neutral-600 hover:underline dark:text-neutral-400">
            {showAlts ? 'Hide' : 'Show'} {data.routes.length - 1} other routes
          </button>
          {showAlts && (
            <ul className="mt-2 divide-y divide-neutral-200 rounded-xl border border-neutral-200 text-sm dark:divide-neutral-800 dark:border-neutral-800">
              {data.routes.slice(1).map((r) => (
                <li key={r.route_quote_id} className="flex flex-wrap items-center gap-3 px-4 py-2.5">
                  <PathChips path={r.path} />
                  <span className="ml-auto font-mono tabular-nums">{formatAmount(r.to_ccy, r.amount_out)}</span>
                  <span className="w-28 text-right font-mono text-xs text-red-700 tabular-nums dark:text-red-400">−{formatAmount(r.to_ccy, r.behind_best ?? '0')}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {best && data && contact && (
        <WaitForBetter
          key={contact.id + data.amount_usdc}
          contact={contact}
          amount={data.amount_usdc}
          bestOut={best.amount_out}
          ccy={best.to_ccy}
          onCreated={onSent}
        />
      )}

      {best && data?.routes.some((r) => r.hops.some((h) => h.source === 'assumption')) && (
        <p className="flex flex-wrap items-center gap-2 text-xs text-neutral-500">
          <SourceBadge source="assumption" /> Bitso lists no USDC market, so USDC enters through an assumed 1:1 stablecoin swap. Exchange legs use{' '}
          {data.market.source === 'live' ? 'live' : 'recorded'} Bitso order books and published taker fees; payouts and withdrawals are simulated.
        </p>
      )}

      {confirming && best && data && contact && (
        <div role="dialog" aria-modal="true" aria-labelledby="confirm-send" className="fixed inset-0 z-10 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-md space-y-3 rounded-2xl bg-white p-6 text-neutral-900 shadow-2xl dark:bg-neutral-950 dark:text-neutral-100">
            <h3 id="confirm-send" className="text-lg font-semibold">
              Confirm send
            </h3>
            <dl className="space-y-1 text-sm">
              <div className="flex justify-between">
                <dt className="text-neutral-500">You send</dt>
                <dd className="font-mono">{formatDecimal(data.amount_usdc)} USDC</dd>
              </div>
              <div className="flex justify-between gap-4">
                <dt className="text-neutral-500">To</dt>
                <dd className="text-right">
                  {contact.kind === 'wallet' ? <span className="break-all font-mono text-xs">{contact.wallet_address}</span> : `${contact.name} · ${contact.account_masked}`}
                </dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-neutral-500">They receive</dt>
                <dd className="font-mono">≈ {formatAmount(best.to_ccy, best.amount_out)}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-neutral-500">At least</dt>
                <dd className="font-mono">{data.min_out && formatAmount(best.to_ccy, data.min_out)}</dd>
              </div>
              <div className="flex justify-between gap-4">
                <dt className="text-neutral-500">Route</dt>
                <dd>
                  <PathChips path={best.path} />
                </dd>
              </div>
            </dl>
            {isNew && (
              <label className="flex items-start gap-2 rounded-lg bg-amber-50 p-3 text-sm text-amber-900 dark:bg-amber-950/40 dark:text-amber-200">
                <input type="checkbox" checked={checked} onChange={(e) => setChecked(e.target.checked)} className="mt-0.5" />
                <span>New address. I've checked every character; funds sent to a wrong address can't be recovered.</span>
              </label>
            )}
            <p className="text-xs text-neutral-500">Right before sending, RampScout re-prices this exact route. If they'd receive less than the minimum, nothing is sent.</p>
            <div className="flex justify-end gap-2">
              <button type="button" onClick={() => setConfirming(false)} className="rounded-md border border-neutral-300 px-4 py-2 dark:border-neutral-700">
                Cancel
              </button>
              <button type="button" onClick={send} disabled={busy || (isNew && !checked)} className="rounded-md bg-emerald-600 px-4 py-2 font-medium text-white disabled:opacity-50">
                {busy ? 'Sending…' : 'Confirm and send'}
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  )
}

function WaitForBetter({
  contact,
  amount,
  bestOut,
  ccy,
  onCreated,
}: {
  contact: Contact
  amount: string
  bestOut: string
  ccy: string
  onCreated: (id: string) => void
}) {
  const [open, setOpen] = useState(false)
  const [minOut, setMinOut] = useState(() => suggestTarget(bestOut, ccy))
  const [deadline, setDeadline] = useState(() => {
    const d = new Date(Date.now() + 2 * 3600_000)
    const local = new Date(d.toLocaleString('en-US', { timeZone: TZ }))
    const pad = (n: number) => String(n).padStart(2, '0')
    return `${local.getFullYear()}-${pad(local.getMonth() + 1)}-${pad(local.getDate())}T${pad(local.getHours())}:${pad(local.getMinutes())}`
  })
  const [mode, setMode] = useState<'notify' | 'auto'>('notify')
  const [checked, setChecked] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function start() {
    setBusy(true)
    setError(null)
    try {
      if (contact.status === 'pending') await confirmContact(contact.id)
      const a = await startSendWatch({
        contact_id: contact.id,
        amount_usdc: amount,
        min_out: minOut.trim(),
        deadline_local: `${deadline}:00`,
        time_zone: TZ,
        mode,
      })
      onCreated(a.id)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="rounded-2xl border border-violet-300 p-4 dark:border-violet-900">
      <button type="button" onClick={() => setOpen((v) => !v)} aria-expanded={open} className="flex w-full items-center gap-2 text-left">
        <span aria-hidden className="flex h-6 w-6 items-center justify-center rounded-full bg-violet-600 text-xs text-white">
          ✦
        </span>
        <span className="font-medium">Or let the agent wait for a better price</span>
        <span className="ml-auto text-xs text-neutral-500">{open ? 'Hide' : 'Set a target'}</span>
      </button>
      {open && (
        <div className="mt-3 space-y-3 text-sm">
          <p className="text-neutral-500">
            The agent re-checks live routes every 30 seconds until {contact.name} would get your minimum, then notifies you or sends. Waiting can
            end with a worse price or nothing sent.
          </p>
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="block">
              <span className="font-medium">Only if they receive at least ({ccy})</span>
              <input inputMode="decimal" value={minOut} onChange={(e) => setMinOut(e.target.value)} className={`${inputCls} font-mono`} />
              <span className="text-xs text-neutral-500">
                Now: {formatAmount(ccy, bestOut)} · {DECIMALS_HINT[ccy] ?? ''}
              </span>
            </label>
            <label className="block">
              <span className="font-medium">Deadline (Mexico City time)</span>
              <input type="datetime-local" value={deadline} onChange={(e) => setDeadline(e.target.value)} className={inputCls} />
            </label>
          </div>
          <fieldset className="grid grid-cols-2 gap-2">
            <legend className="sr-only">When the target is met</legend>
            {(
              [
                ['notify', 'Notify me', 'Alert only; nothing sends.'],
                ['auto', 'Auto-send', 'Sends automatically, never below your minimum.'],
              ] as const
            ).map(([v, label, hint]) => (
              <label key={v} className={`cursor-pointer rounded-lg border p-2 ${mode === v ? 'border-emerald-500 bg-emerald-50 dark:bg-emerald-950/30' : 'border-neutral-300 dark:border-neutral-700'}`}>
                <input type="radio" name="wait-mode" className="mr-1.5" checked={mode === v} onChange={() => setMode(v)} />
                <span className="font-medium">{label}</span>
                <span className="block text-xs text-neutral-500">{hint}</span>
              </label>
            ))}
          </fieldset>
          {contact.status === 'pending' && (
            <label className="flex items-start gap-2 rounded-lg bg-amber-50 p-2 text-amber-900 dark:bg-amber-950/40 dark:text-amber-200">
              <input type="checkbox" checked={checked} onChange={(e) => setChecked(e.target.checked)} className="mt-0.5" />
              <span>New address. I've checked every character.</span>
            </label>
          )}
          {error && (
            <p role="alert" className="text-red-700 dark:text-red-300">
              {error}
            </p>
          )}
          <button
            type="button"
            onClick={start}
            disabled={busy || !minOut.trim() || !deadline || (contact.status === 'pending' && !checked)}
            className="rounded-md bg-violet-600 px-4 py-2 font-medium text-white disabled:opacity-50"
          >
            {busy ? 'Starting…' : 'Start watching'}
          </button>
        </div>
      )}
    </div>
  )
}
