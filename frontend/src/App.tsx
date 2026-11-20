import { useEffect, useState } from 'react'
import { api } from './api/client'
import type { DemoState } from './api/types'
import { DemoBar } from './components/DemoBar'
import { Compare } from './pages/Compare'

export default function App() {
  const [demo, setDemo] = useState<DemoState | null>(null)
  const [busy, setBusy] = useState(false)
  const [refreshKey, setRefreshKey] = useState(0)

  useEffect(() => {
    api<DemoState>('/demo/state').then(setDemo, () => setDemo(null))
  }, [])

  async function run(path: string, body?: unknown) {
    setBusy(true)
    try {
      setDemo(await api<DemoState>(path, { method: 'POST', body: body ? JSON.stringify(body) : undefined }))
      setRefreshKey((k) => k + 1)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="min-h-screen bg-white text-neutral-900 dark:bg-neutral-950 dark:text-neutral-100">
      <main className="mx-auto max-w-4xl space-y-6 px-4 py-8">
        <header>
          <h1 className="text-3xl font-semibold tracking-tight">RampScout</h1>
          <p className="text-neutral-500">USDC → MXN, ranked by pesos that actually reach the bank.</p>
        </header>
        <DemoBar
          state={demo}
          busy={busy}
          onAdvance={() => run('/demo/advance')}
          onReset={() => run('/demo/reset')}
          onChaos={(flag, on) => run('/demo/chaos', { flags: { [flag]: on } })}
        />
        <Compare refreshKey={refreshKey} />
      </main>
    </div>
  )
}
