import { useEffect } from 'react'

export default function Toast({ msg, onDone, tone = 'info' }: { msg: string | null; onDone: () => void; tone?: 'info' | 'error' }) {
  useEffect(() => {
    if (!msg) return
    const id = window.setTimeout(onDone, 4500)
    return () => window.clearTimeout(id)
  }, [msg, onDone])
  if (!msg) return null
  return (
    <div className={`fixed bottom-4 left-1/2 z-50 -translate-x-1/2 rounded-md px-4 py-2 text-sm text-white shadow-lg ${tone === 'error' ? 'bg-red' : 'bg-ink'}`}>
      {msg}
    </div>
  )
}
