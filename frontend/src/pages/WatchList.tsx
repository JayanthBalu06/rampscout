import { useState } from 'react'
import { api } from '../api/client'
import type { Authorization } from '../api/types'
import { StatusPill } from '../components/StatusPill'
import { headline } from '../lib/auth'
import { usePolling } from '../lib/usePolling'

export function WatchList({
  refreshKey,
  title = 'Your activity',
  limit,
  emptyText,
}: {
  refreshKey: number
  title?: string
  limit?: number
  emptyText?: string
}) {
  const [items, setItems] = useState<Authorization[]>([])
  usePolling(async () => setItems(await api<Authorization[]>('/authorizations')), 3000, true, refreshKey)
  const shown = limit ? items.slice(0, limit) : items
  if (items.length === 0) return emptyText ? <p className="text-sm text-neutral-500">{emptyText}</p> : null
  return (
    <section aria-labelledby="list-title">
      <h2 id="list-title" className="mb-2 text-sm font-semibold uppercase tracking-wide text-neutral-500">
        {title}
      </h2>
      <ul className="divide-y divide-neutral-200 rounded-xl border border-neutral-200 dark:divide-neutral-800 dark:border-neutral-800">
        {shown.map((a) => (
          <li key={a.id}>
            <a href={`#/a/${a.id}`} className="flex flex-wrap items-center gap-3 px-4 py-3 hover:bg-neutral-50 dark:hover:bg-neutral-900">
              <StatusPill status={a.status} />
              <span className="font-mono text-sm">
                {headline(a).replace(/^\w[\w ]*: /, '')}
              </span>
              <span className="min-w-0 flex-1 truncate text-sm text-neutral-500">{a.last_reason}</span>
            </a>
          </li>
        ))}
      </ul>
    </section>
  )
}
