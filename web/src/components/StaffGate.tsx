import { useEffect, useState, type ReactNode } from 'react'
import { api } from '../lib/api'
import { Signature } from './ui'

/** Staff pages (agent console, fraud desk, demo panel, metrics, recorder) need the staff PIN once per device. */
export default function StaffGate({ children }: { children: ReactNode }) {
  const [state, setState] = useState<'checking' | 'locked' | 'open'>('checking')
  const [pin, setPin] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    api
      .get<{ staff: boolean }>('/api/staff/me')
      .then((r) => setState(r.staff ? 'open' : 'locked'))
      .catch(() => setState('locked'))
  }, [])

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setErr(null)
    try {
      await api.post('/api/staff/login', { pin })
      setState('open')
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  if (state === 'open') return <>{children}</>
  if (state === 'checking') return <div className="grid h-full place-items-center text-muted">Loading…</div>
  return (
    <div className="grid min-h-full place-items-center px-4">
      <form onSubmit={submit} className="card w-full max-w-sm space-y-4 p-6">
        <div className="flex items-center gap-2">
          <Signature className="h-5 w-12 text-brand" />
          <span className="font-display text-lg font-bold">Staff only</span>
        </div>
        <p className="text-sm text-muted">Enter the staff PIN. The engine prints it in its console when it starts.</p>
        <input className="input text-center font-mono text-lg tracking-widest" inputMode="numeric" autoFocus value={pin} onChange={(e) => setPin(e.target.value)} aria-label="Staff PIN" />
        {err && <p className="text-sm text-red">{err}</p>}
        <button className="btn-primary w-full" disabled={!pin || busy}>
          {busy ? 'Checking…' : 'Unlock'}
        </button>
      </form>
    </div>
  )
}
