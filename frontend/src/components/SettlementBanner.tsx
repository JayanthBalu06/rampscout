import type { Settlement } from '../api/types'

export function SettlementBanner({ s }: { s: Settlement }) {
  const scale = s.transfer_scale === '1' ? '' : ` · onchain transfers scaled ×${s.transfer_scale}`
  return s.mode === 'testnet' ? (
    <p className="rounded-lg bg-sky-50 px-3 py-2 text-sm text-sky-900 dark:bg-sky-950/40 dark:text-sky-200">
      <strong>Testnet settlement:</strong> real USDC transfer on {s.network} (chain {s.chain_id}){scale}. MXN
      conversion and bank deposit are <strong>simulated</strong>.
    </p>
  ) : (
    <p className="rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-900 dark:bg-amber-950/40 dark:text-amber-200">
      <strong>Simulated settlement.</strong> {s.reason}. MXN conversion and bank deposit are always simulated.
    </p>
  )
}
