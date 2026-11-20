import { useEffect, useState } from 'react'
import { api } from './api/client'
import type { DemoState } from './api/types'
import { DemoBar } from './components/DemoBar'
import { NotificationBanner } from './components/Notifications'
import { useHashRoute } from './lib/router'
import { Compare } from './pages/Compare'
import { WatchBuilder } from './pages/WatchBuilder'
import { WatchDetail } from './pages/WatchDetail'
import { WatchList } from './pages/WatchList'

export default function App() {
  const [demo, setDemo] = useState<DemoState | null>(null)
  const [busy, setBusy] = useState(false)
  const [refreshKey, setRefreshKey] = useState(0)
  const [path, navigate] = useHashRoute()

  useEffect(() => {
    api<DemoState>('/demo/state').then(setDemo, () => setDemo(null))
  }, [])

  async function run(p: string, body?: unknown) {
    setBusy(true)
    try {
      setDemo(await api<DemoState>(p, { method: 'POST', body: body ? JSON.stringify(body) : undefined }))
      setRefreshKey((k) => k + 1)
      if (p === '/demo/reset') navigate('/compare')
    } finally {
      setBusy(false)
    }
  }

  const watchId = path.match(/^\/watch\/([0-9a-f-]{36})$/)?.[1]
  const tab = path.startsWith('/watch') ? 'watch' : 'compare'

  return (
    <div className="min-h-screen bg-white text-neutral-900 dark:bg-neutral-950 dark:text-neutral-100">
      <main className="mx-auto max-w-4xl space-y-6 px-4 py-8">
        <header className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="text-3xl font-semibold tracking-tight">RampScout</h1>
            <p className="text-neutral-500">USDC → MXN, ranked by pesos that actually reach the bank.</p>
          </div>
          <nav aria-label="Main" className="flex gap-1 rounded-lg bg-neutral-100 p-1 text-sm dark:bg-neutral-900">
            {(
              [
                ['compare', '/compare', 'Compare'],
                ['watch', '/watch/new', 'Watch for a target'],
              ] as const
            ).map(([key, href, label]) => (
              <a
                key={key}
                href={`#${href}`}
                aria-current={tab === key ? 'page' : undefined}
                className={`rounded-md px-3 py-1.5 ${tab === key ? 'bg-white font-medium shadow-sm dark:bg-neutral-800' : 'text-neutral-600 dark:text-neutral-400'}`}
              >
                {label}
              </a>
            ))}
          </nav>
        </header>
        <DemoBar
          state={demo}
          busy={busy}
          onAdvance={() => run('/demo/advance')}
          onReset={() => run('/demo/reset')}
          onReconcile={() => run('/demo/reconcile')}
          onChaos={(flag, on) => run('/demo/chaos', { flags: { [flag]: on } })}
        />
        <NotificationBanner refreshKey={refreshKey} />
        {watchId ? (
          <WatchDetail id={watchId} refreshKey={refreshKey} />
        ) : tab === 'watch' ? (
          <WatchBuilder onCreated={(id) => navigate(`/watch/${id}`)} />
        ) : (
          <Compare refreshKey={refreshKey} onConverted={(id) => navigate(`/watch/${id}`)} />
        )}
        <WatchList refreshKey={refreshKey} />
      </main>
    </div>
  )
}
