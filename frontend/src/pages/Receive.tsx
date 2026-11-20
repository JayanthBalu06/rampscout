import QRCode from 'qrcode'
import { useEffect, useState } from 'react'
import { CopyButton } from '../components/CopyButton'
import { useWallet } from '../lib/useWallet'

export function Receive() {
  const { wallet } = useWallet()
  const [qr, setQr] = useState<string | null>(null)
  useEffect(() => {
    if (wallet) void QRCode.toDataURL(wallet.address, { margin: 1, width: 240 }).then(setQr)
  }, [wallet])
  return (
    <section aria-labelledby="receive-title" className="space-y-4 text-center">
      <h2 id="receive-title" className="text-xl font-semibold">
        Receive
      </h2>
      <p className="text-sm text-neutral-500">
        Send USDC on <strong>{wallet?.network ?? '…'}</strong> to this address.
      </p>
      {qr && <img src={qr} alt="QR code of your wallet address" className="mx-auto rounded-xl border border-neutral-200 bg-white p-2 dark:border-neutral-800" />}
      {wallet && (
        <div className="mx-auto max-w-sm space-y-2 rounded-xl bg-emerald-700 p-3 text-white">
          <p className="break-all font-mono text-sm">{wallet.address}</p>
          <CopyButton text={wallet.address} label="Copy address" />
        </div>
      )}
      {wallet?.mode === 'testnet' ? (
        <p className="text-xs text-neutral-500">
          Testnet only. Get free test USDC at{' '}
          <a className="underline" href="https://faucet.circle.com" target="_blank" rel="noreferrer">
            faucet.circle.com
          </a>{' '}
          (choose Base Sepolia). Never send real funds here.
        </p>
      ) : (
        <p className="text-xs text-neutral-500">This deployment uses a simulated ledger; configure a testnet wallet to receive real test USDC.</p>
      )}
    </section>
  )
}
