import { useState } from 'react'
import { api } from '../api/client'
import type { AppNotification } from '../api/types'
import { usePolling } from '../lib/usePolling'

export function NotificationBanner({ refreshKey }: { refreshKey: number }) {
  const [items, setItems] = useState<AppNotification[]>([])
  usePolling(async () => setItems(await api<AppNotification[]>('/notifications')), 3000, true, refreshKey)
  const unread = items.filter((n) => !n.read)
  if (unread.length === 0) return null
  const n = unread[0]
  async function dismiss() {
    await api(`/notifications/${n.id}/read`, { method: 'POST' })
    setItems((xs) => xs.map((x) => (x.id === n.id ? { ...x, read: true } : x)))
  }
  return (
    <div role="status" className="flex flex-wrap items-start gap-3 rounded-xl bg-emerald-600 px-4 py-3 text-white shadow">
      <span aria-hidden className="text-xl">🔔</span>
      <div className="min-w-0 flex-1">
        <p className="font-semibold">{n.title}</p>
        <p className="text-sm text-emerald-50">{n.body}</p>
      </div>
      <div className="flex gap-2">
        <a href={`#/watch/${n.authorization_id}`} className="rounded-md bg-white px-3 py-1.5 text-sm font-medium text-emerald-800">
          View
        </a>
        <button type="button" onClick={dismiss} className="rounded-md border border-white/60 px-3 py-1.5 text-sm">
          Dismiss
        </button>
      </div>
    </div>
  )
}
