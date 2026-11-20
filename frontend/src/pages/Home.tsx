import { WalletCard } from '../components/WalletCard'
import { useWallet } from '../lib/useWallet'
import { WatchList } from './WatchList'

const ACTIONS: Array<[string, string, string]> = [
  ['#/send', '↗', 'Send'],
  ['#/receive', '↙', 'Receive'],
  ['#/compare', '◎', 'Rates'],
  ['#/watch/new', '⏱', 'Watch'],
]

export function Home({ refreshKey }: { refreshKey: number }) {
  const { wallet, refresh } = useWallet(refreshKey)
  return (
    <div className="space-y-6">
      <WalletCard wallet={wallet} onRefresh={refresh} />
      <nav aria-label="Wallet actions" className="grid grid-cols-4 gap-3">
        {ACTIONS.map(([href, icon, label]) => (
          <a
            key={label}
            href={href}
            className="flex flex-col items-center gap-1.5 rounded-2xl border border-neutral-200 py-3 text-sm font-medium hover:border-emerald-500 hover:bg-emerald-50 dark:border-neutral-800 dark:hover:bg-emerald-950/30"
          >
            <span aria-hidden className="flex h-10 w-10 items-center justify-center rounded-full bg-emerald-600 text-lg text-white">
              {icon}
            </span>
            {label}
          </a>
        ))}
      </nav>
      <WatchList refreshKey={refreshKey} title="Recent activity" limit={5} emptyText="No activity yet. Send some USDC to get started." />
    </div>
  )
}
