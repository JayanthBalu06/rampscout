import { useState } from 'react'

export function CopyButton({ text, label = 'Copy' }: { text: string; label?: string }) {
  const [done, setDone] = useState(false)
  return (
    <button
      type="button"
      onClick={async () => {
        await navigator.clipboard.writeText(text)
        setDone(true)
        window.setTimeout(() => setDone(false), 1500)
      }}
      className="rounded-md border border-white/40 px-2 py-0.5 text-xs hover:bg-white/10"
    >
      {done ? 'Copied' : label}
    </button>
  )
}
