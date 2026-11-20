import type { Wallet } from '../api/types'
import { formatDecimal } from '../lib/money'
import { short } from '../lib/useWallet'
import { CopyButton } from './CopyButton'

export function WalletCard({ wallet, onRefresh }: { wallet: Wallet | null; onRefresh?: () => void }) {
  return (
    <section
      aria-label="Your wallet"
      className="rounded-3xl bg-gradient-to-br from-emerald-600 via-emerald-700 to-teal-800 p-6 text-white shadow-lg"
    >
      <div className="flex items-center gap-2 text-sm text-emerald-50">
        <span className="font-medium">Your wallet</span>
        <span className="rounded-full bg-white/15 px-2 py-0.5 text-[11px] font-medium uppercase tracking-wide">
          {wallet ? (wallet.mode === 'testnet' ? 'Base Sepolia · testnet' : 'Simulated ledger') : '…'}
        </span>
        {onRefresh && (
          <button type="button" onClick={onRefresh} className="ml-auto text-xs underline-offset-2 hover:underline">
            Refresh
          </button>
        )}
      </div>
      <p className="mt-4 text-4xl font-semibold tabular-nums tracking-tight">
        {wallet?.usdc != null ? formatDecimal(wallet.usdc, 2) : '-'} <span className="text-2xl font-medium">USDC</span>
      </p>
      <p className="text-sm text-emerald-100">
        Gas: {wallet?.eth != null ? formatDecimal(wallet.eth, 6) : '-'} ETH
        {wallet?.mode === 'testnet' ? ' · test funds, no real value' : ' · demo balance'}
      </p>
      {wallet && (
        <div className="mt-4 flex flex-wrap items-center gap-2 text-sm">
          <span className="font-mono">{short(wallet.address)}</span>
          <CopyButton text={wallet.address} />
          {wallet.explorer_url && (
            <a href={wallet.explorer_url} target="_blank" rel="noreferrer" className="text-xs underline">
              View on Basescan ↗
            </a>
          )}
        </div>
      )}
      {wallet?.shared && <p className="mt-2 text-xs text-emerald-100/80">{wallet.note}.</p>}
    </section>
  )
}
