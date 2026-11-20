import { useState } from 'react'
import { api } from '../api/client'
import type { Wallet } from '../api/types'
import { usePolling } from './usePolling'

/** Wallet address + balances, refreshed every 15 s and whenever `refreshKey` changes. */
export function useWallet(refreshKey: unknown = 0) {
  const [wallet, setWallet] = useState<Wallet | null>(null)
  const refresh = async () => {
    try {
      setWallet(await api<Wallet>('/wallet'))
    } catch {
      /* keep last known */
    }
  }
  usePolling(refresh, 15_000, true, String(refreshKey))
  return { wallet, refresh }
}

export const short = (a: string) => `${a.slice(0, 6)}…${a.slice(-4)}`
