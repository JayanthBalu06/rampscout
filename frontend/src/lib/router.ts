import { useEffect, useState } from 'react'

/** Minimal hash router: #/compare, #/watch/new, #/watch/<id>. Survives reloads. */
export function useHashRoute(): [string, (path: string) => void] {
  const read = () => window.location.hash.replace(/^#/, '') || '/compare'
  const [path, setPath] = useState(read)
  useEffect(() => {
    const onChange = () => setPath(read())
    window.addEventListener('hashchange', onChange)
    return () => window.removeEventListener('hashchange', onChange)
  }, [])
  return [path, (p: string) => (window.location.hash = p)]
}
