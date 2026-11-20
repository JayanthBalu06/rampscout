import { useEffect, useRef } from 'react'

/** Run `fn` now and every `ms` while `active`. `key` restarts the cycle when it changes. */
export function usePolling(fn: () => void | Promise<void>, ms: number, active: boolean, key: string | number = '') {
  const saved = useRef(fn)
  useEffect(() => {
    saved.current = fn
  })
  useEffect(() => {
    if (!active) return
    void saved.current()
    const id = window.setInterval(() => void saved.current(), ms)
    return () => window.clearInterval(id)
  }, [active, ms, key])
}
