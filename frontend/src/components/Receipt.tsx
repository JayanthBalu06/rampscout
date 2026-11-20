import type { ReactNode } from 'react'
import type { Authorization } from '../api/types'
import { minimumText, modeLabel, recipientText } from '../lib/auth'
import { formatAmount, formatDecimal } from '../lib/money'
import { formatInTz } from '../lib/time'
import { FeeBreakdown } from './FeeBreakdown'
import { HopTable, PathChips } from './RouteView'

function Stamp({ kind }: { kind: 'testnet' | 'simulated' | 'fixture' }) {
  const cls = {
    testnet: 'border-sky-500 text-sky-700 dark:text-sky-300',
    simulated: 'border-amber-500 text-amber-700 dark:text-amber-300',
    fixture: 'border-neutral-400 text-neutral-500',
  }[kind]
  const label = { testnet: 'Testnet · real transfer', simulated: 'Simulated', fixture: 'Synthetic quote' }[kind]
  return <span className={`rounded border border-dashed px-1.5 py-0.5 text-[11px] font-medium uppercase tracking-wide ${cls}`}>{label}</span>
}

function Row({ k, v, mono }: { k: string; v: ReactNode; mono?: boolean }) {
  return (
    <div className="flex items-baseline justify-between gap-4 py-1">
      <dt className="text-neutral-500">{k}</dt>
      <dd className={`text-right ${mono ? 'font-mono' : ''}`}>{v}</dd>
    </div>
  )
}

const shortHash = (h: string) => `${h.slice(0, 10)}…${h.slice(-8)}`

export function Receipt({ auth }: { auth: Authorization }) {
  const ex = auth.execution
  if (!ex) return null
  const tz = auth.terms.time_zone
  const q = auth.executed_quote
  const chainOk = ex.chain_status === 'confirmed'
  const testnet = ex.settlement_mode === 'testnet'
  const ccy = ex.out_currency ?? 'MXN'
  const quoted = ex.quoted_out ?? ex.quoted_net_mxn
  const delivered = ex.delivered_out ?? ex.payout_mxn
  const walletDelivery = ccy === 'USDC'
  return (
    <section aria-labelledby="receipt-title" className="space-y-4 rounded-2xl border border-neutral-200 p-5 dark:border-neutral-800">
      <header className="flex flex-wrap items-center gap-2">
        <h3 id="receipt-title" className="text-lg font-semibold">
          Receipt
        </h3>
        <span className="text-sm text-neutral-500">· {ex.state_label}</span>
      </header>

      <div className="grid gap-4 md:grid-cols-2">
        <div className="space-y-3 rounded-xl bg-neutral-50 p-4 text-sm dark:bg-neutral-900">
          <h4 className="font-semibold">What you authorized</h4>
          <dl>
            <Row k="Mode" v={modeLabel(auth)} />
            <Row k="Total debit" v={`${formatDecimal(auth.terms.amount_usdc)} USDC`} mono />
            <Row k={auth.mode === 'send' ? 'They receive at least' : 'Minimum payout'} v={minimumText(auth)} mono />
            <Row k="Recipient" v={recipientText(auth)} />
            <Row k="Confirmed" v={formatInTz(auth.confirmed_at, tz)} />
          </dl>
          {auth.route && (
            <>
              <h4 className="flex flex-wrap items-center gap-2 pt-2 font-semibold">
                Executed route <PathChips path={auth.route.path} />
              </h4>
              <HopTable route={auth.route} />
            </>
          )}
          {q && !auth.route && (
            <>
              <h4 className="flex items-center gap-2 pt-2 font-semibold">
                Executed quote <Stamp kind="fixture" />
              </h4>
              <p className="font-mono text-xs text-neutral-500">
                {q.route_name} · {q.quote_id}
              </p>
              <FeeBreakdown b={q.breakdown} />
            </>
          )}
        </div>

        <div className="space-y-3 rounded-xl bg-neutral-50 p-4 text-sm dark:bg-neutral-900">
          <h4 className="flex items-center gap-2 font-semibold">
            USDC transfer <Stamp kind={testnet ? 'testnet' : 'simulated'} />
          </h4>
          <dl>
            <Row k="Network" v={ex.network} />
            <Row
              k="Amount sent"
              v={`${formatDecimal(ex.onchain_amount_usdc, 2)} USDC${ex.transfer_scale !== '1' ? ` (×${ex.transfer_scale} demo scale)` : ''}`}
              mono
            />
            <Row
              k="To"
              v={ex.recipient_address ? `${ex.recipient_label ?? `Route ${ex.route_id} wallet`} ${ex.recipient_address.slice(0, 8)}…` : '-'}
            />
            <Row
              k="Status"
              v={
                chainOk ? (
                  <span className="text-emerald-700 dark:text-emerald-400">Verified · block {ex.block_number}</span>
                ) : (
                  <span className="text-amber-700 dark:text-amber-400">{ex.state_label}</span>
                )
              }
            />
            <Row k="Broadcast attempts" v={ex.broadcast_attempts} />
            {ex.tx_hash && (
              <Row
                k="Tx hash"
                mono
                v={
                  ex.explorer_url ? (
                    <a href={ex.explorer_url} target="_blank" rel="noreferrer" className="text-sky-700 underline dark:text-sky-400">
                      {shortHash(ex.tx_hash)} ↗
                    </a>
                  ) : (
                    shortHash(ex.tx_hash)
                  )
                }
              />
            )}
          </dl>
          {!chainOk && (
            <p className="text-xs text-neutral-500">A pending transfer stays pending until its receipt is verified onchain.</p>
          )}

          <h4 className="flex items-center gap-2 pt-2 font-semibold">
            {walletDelivery ? 'Delivery' : `${ccy} payout`}{' '}
            <Stamp kind={walletDelivery ? (testnet ? 'testnet' : 'simulated') : 'simulated'} />
          </h4>
          <dl>
            <Row
              k="Status"
              v={
                ex.payout_status === 'posted'
                  ? walletDelivery
                    ? 'Delivered to wallet onchain'
                    : ccy === 'MXN'
                      ? 'Posted to bank (simulated SPEI)'
                      : 'Posted to bank (simulated)'
                  : ex.payout_status.replace('_', ' ')
              }
            />
            <Row k="Attempts" v={ex.payout_attempts} />
            {ex.payout_reference && <Row k="Reference" v={ex.payout_reference} mono />}
          </dl>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 rounded-xl border-2 border-emerald-500 p-4 text-center">
        <div>
          <p className="text-xs uppercase tracking-wide text-neutral-500">Quoted</p>
          <p className="font-mono text-2xl font-semibold tabular-nums">{quoted ? formatAmount(ccy, quoted) : '-'}</p>
        </div>
        <div>
          <p className="text-xs uppercase tracking-wide text-neutral-500">
            {walletDelivery ? `Delivered onchain${ex.transfer_scale !== '1' ? ` (×${ex.transfer_scale} demo scale)` : ''}` : 'Simulated payout received'}
          </p>
          <p className="font-mono text-2xl font-semibold tabular-nums">{delivered ? formatAmount(ccy, delivered) : 'pending'}</p>
        </div>
      </div>
    </section>
  )
}
