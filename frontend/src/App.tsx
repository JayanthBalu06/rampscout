import { useEffect, useState } from 'react'
import { api } from './api/client'
import type { DemoState } from './api/types'
import { DemoBar } from './components/DemoBar'
import { NotificationBanner } from './components/Notifications'
import { useHashRoute } from './lib/router'
import { Compare } from './pages/Compare'
import { Home } from './pages/Home'
import { Receive } from './pages/Receive'
import { Send } from './pages/Send'
import { WatchBuilder } from './pages/WatchBuilder'
import { WatchDetail } from './pages/WatchDetail'
import { WatchList } from './pages/WatchList'

type Tab = 'home' | 'send' | 'activity' | 'agent'

const TABS: Array<[Tab, string, string]> = [
  ['home', '/home', 'Home'],
  ['send', '/send', 'Send'],
  ['activity', '/activity', 'Activity'],
  ['agent', '/compare', 'Agent'],
]

export default function App() {
  const [demo, setDemo] = useState<DemoState | null>(null)
  const [busy, setBusy] = useState(false)
  const [refreshKey, setRefreshKey] = useState(0)
  const [showDemo, setShowDemo] = useState(false)
  const [path, navigate] = useHashRoute()

  useEffect(() => {
    api<DemoState>('/demo/state').then(setDemo, () => setDemo(null))
  }, [])

  async function run(p: string, body?: unknown) {
    setBusy(true)
    try {
      setDemo(await api<DemoState>(p, { method: 'POST', body: body ? JSON.stringify(body) : undefined }))
      setRefreshKey((k) => k + 1)
      if (p === '/demo/reset' && !path.startsWith('/compare')) navigate('/compare')
    } finally {
      setBusy(false)
    }
  }

  const detailId = path.match(/^\/(?:watch|a)\/([0-9a-f-]{36})$/)?.[1]
  const agentPage = path.startsWith('/compare') || path.startsWith('/watch/new')
  const tab: Tab | null = detailId
    ? null
    : agentPage
      ? 'agent'
      : path.startsWith('/send')
        ? 'send'
        : path.startsWith('/activity')
          ? 'activity'
          : path.startsWith('/receive')
            ? null
            : 'home'
  const wide = agentPage || !!detailId

  const demoBar = (
    <DemoBar
      state={demo}
      busy={busy}
      onAdvance={() => run('/demo/advance')}
      onReset={() => run('/demo/reset')}
      onReconcile={() => run('/demo/reconcile')}
      onChaos={(flag, on) => run('/demo/chaos', { flags: { [flag]: on } })}
    />
  )

  return (
    <div className="min-h-screen bg-neutral-50 text-neutral-900 dark:bg-neutral-950 dark:text-neutral-100">
      <main className={`mx-auto space-y-5 px-4 py-6 ${wide ? 'max-w-4xl' : 'max-w-xl'}`}>
        <header className="flex flex-wrap items-center justify-between gap-3">
          <a href="#/home" className="flex items-center gap-2">
            <span aria-hidden className="flex h-8 w-8 items-center justify-center rounded-xl bg-emerald-600 font-bold text-white">
              R
            </span>
            <span>
              <span className="block text-lg font-semibold leading-tight tracking-tight">RampScout</span>
              <span className="block text-xs text-neutral-500">Send USDC anywhere. We find the best route.</span>
            </span>
          </a>
          {!agentPage && !detailId && (
            <button
              type="button"
              onClick={() => setShowDemo((v) => !v)}
              aria-expanded={showDemo}
              className="rounded-md border border-neutral-300 px-2.5 py-1 text-xs text-neutral-600 dark:border-neutral-700 dark:text-neutral-400"
            >
              Demo controls
            </button>
          )}
        </header>

        <nav aria-label="Main" className="grid grid-cols-4 gap-1 rounded-xl bg-neutral-200/60 p-1 text-sm dark:bg-neutral-900">
          {TABS.map(([key, href, label]) => (
            <a
              key={key}
              href={`#${href}`}
              aria-current={tab === key ? 'page' : undefined}
              className={`rounded-lg px-3 py-1.5 text-center ${tab === key ? 'bg-white font-medium shadow-sm dark:bg-neutral-800' : 'text-neutral-600 dark:text-neutral-400'}`}
            >
              {label}
            </a>
          ))}
        </nav>

        {(agentPage || !!detailId || showDemo) && demoBar}
        <NotificationBanner refreshKey={refreshKey} />

        {agentPage && (
          <nav aria-label="Agent" className="flex gap-4 border-b border-neutral-200 text-sm dark:border-neutral-800">
            {(
              [
                ['/compare', 'Compare routes'],
                ['/watch/new', 'Watch for a target'],
              ] as const
            ).map(([href, label]) => (
              <a
                key={href}
                href={`#${href}`}
                aria-current={path.startsWith(href) ? 'page' : undefined}
                className={`-mb-px border-b-2 px-1 pb-2 ${path.startsWith(href) ? 'border-emerald-600 font-medium' : 'border-transparent text-neutral-500'}`}
              >
                {label}
              </a>
            ))}
          </nav>
        )}

        {detailId ? (
          <WatchDetail id={detailId} refreshKey={refreshKey} />
        ) : path.startsWith('/compare') ? (
          <Compare refreshKey={refreshKey} onConverted={(id) => navigate(`/a/${id}`)} />
        ) : path.startsWith('/watch/new') ? (
          <WatchBuilder onCreated={(id) => navigate(`/a/${id}`)} />
        ) : tab === 'send' ? (
          <Send onSent={(id) => navigate(`/a/${id}`)} refreshKey={refreshKey} />
        ) : path.startsWith('/receive') ? (
          <Receive />
        ) : tab === 'activity' ? (
          <WatchList refreshKey={refreshKey} title="Activity" emptyText="Nothing yet." />
        ) : (
          <Home refreshKey={refreshKey} />
        )}
      </main>
    </div>
  )
}
