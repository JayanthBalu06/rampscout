import { useEffect, useState } from 'react'
import { api, type Health } from './api/client'

export default function App() {
  const [health, setHealth] = useState<Health | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api<Health>('/health').then(setHealth, (e: Error) => setError(e.message))
  }, [])

  return (
    <main className="mx-auto max-w-3xl px-4 py-10">
      <h1 className="text-3xl font-semibold tracking-tight">RampScout</h1>
      <p className="mt-2 text-neutral-500">USDC → MXN route scout. Phase 0 scaffold.</p>
      <p className="mt-6 text-sm" role="status">
        API: {health ? `${health.status} (db ${health.db})` : error ? `unreachable: ${error}` : 'checking…'}
      </p>
    </main>
  )
}
