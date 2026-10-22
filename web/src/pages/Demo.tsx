import { useEffect, useState } from 'react'
import QRCode from 'qrcode'
import { api } from '../lib/api'
import { usePoll } from '../lib/events'
import type { Customer } from '../lib/types'
import { TopBar } from '../components/ui'
import { useToast } from '../lib/useToast'

type World = {
  customers: Record<string, Customer>
  fri: Record<string, string>
  sim_swaps: Record<string, number>
  recent_calls: Record<string, number>
  on_call?: Record<string, string>
}
type Stored = {
  voiceprints: number
  calls_with_speaker_embeddings_in_memory: number
  audio_files_on_disk: { file: string; bytes: number; encrypted: boolean }[]
  live_audio_seconds_in_memory: Record<string, number>
  case_rows: { id: string; tier: string; reasons: string[]; status: string; outcome: string | null }[]
  audit_events: number
  transcripts_stored: number
}
type Health = { models: Record<string, string>; s1_version: string; p95_ms: number | null; live_calls: number; rp_id: string; public_url?: string }

function QR({ path, label }: { path: string; label: string }) {
  const [src, setSrc] = useState('')
  const url = `${location.origin}${path}`
  useEffect(() => {
    QRCode.toDataURL(url, { margin: 1, width: 180 }).then(setSrc)
  }, [url])
  return (
    <a href={path} target="_blank" rel="noreferrer" className="card block p-3 text-center no-underline">
      {src && <img src={src} alt={`QR code for ${label}`} className="mx-auto h-36 w-36" />}
      <div className="mt-2 text-sm font-semibold text-ink">{label}</div>
      <div className="truncate font-mono text-[11px] text-muted">{path}</div>
    </a>
  )
}

/** A one-time login link for a customer's bank app, as a QR code. Each scan logs one phone in. */
function LoginQR({ customer, label, base }: { customer: string; label: string; base: string }) {
  const [path, setPath] = useState('')
  const [src, setSrc] = useState('')
  const [n, setN] = useState(0)
  useEffect(() => {
    let live = true
    api.post<{ path: string }>(`/api/demo/login-link/${customer}`).then((r) => live && setPath(r.path), () => live && setPath(''))
    const t = window.setTimeout(() => setN((x) => x + 1), 9 * 60 * 1000) // links last 10 minutes
    return () => {
      live = false
      window.clearTimeout(t)
    }
  }, [customer, n])
  useEffect(() => {
    if (path) QRCode.toDataURL(`${base}${path}`, { margin: 1, width: 180 }).then(setSrc)
  }, [base, path])
  return (
    <button className="card block w-full p-3 text-center" onClick={() => setN((x) => x + 1)} title="New code">
      {src ? <img src={src} alt={`Login QR code for ${label}`} className="mx-auto h-36 w-36" /> : <div className="mx-auto h-36 w-36" />}
      <div className="mt-2 text-sm font-semibold text-ink">{label}</div>
      <div className="text-[11px] text-muted">one phone, 10 min · tap for a new code</div>
    </button>
  )
}

export default function Demo() {
  const world = usePoll(() => api.get<World>('/api/demo/world'), 4000)
  const stored = usePoll(() => api.get<Stored>('/api/demo/stored'), 3000)
  const health = usePoll(() => api.get<Health>('/api/health'), 5000)
  const { show, node: toast } = useToast()
  const w = world.data
  const insecure = location.protocol !== 'https:' && location.hostname !== 'localhost' && location.hostname !== '127.0.0.1'

  const call = async (p: string, body: unknown, msg: string) => {
    try {
      await api.post(p, body)
      show(msg)
      world.reload()
      stored.reload()
    } catch (e) {
      show((e as Error).message, 'error')
    }
  }

  const rahul = w?.customers.rahul
  const swapOn = rahul ? rahul.registered_mobile in (w?.sim_swaps || {}) : false
  const sunitaCall = !!w?.recent_calls.sunita || !!w?.on_call?.sunita
  const sunitaLive = w?.on_call?.sunita

  return (
    <div className="min-h-full">
      <TopBar title="Demo operator" />
      <main className="mx-auto max-w-6xl space-y-6 p-4 sm:p-6">
        {insecure && (
          <p className="rounded-md bg-amber-soft p-3 text-sm">
            This page is on plain HTTP over the network, so phones can't use passkeys or the mic here. Open it through the HTTPS tunnel (see docs/RUNBOOK.md).
          </p>
        )}
        <section className="card flex flex-wrap items-center gap-4 p-4">
          <div className="w-40">
            <QR path="/try" label="Judges: try it yourself" />
          </div>
          <div className="max-w-xl text-sm">
            <div className="text-lg font-bold">For judges</div>
            <p className="mt-1">
              Scan, and the phone gets its own demo account. Call the bank as yourself or play a cloned voice; a virtual agent answers, and the approval arrives on the same
              phone. Nothing to install, no PIN, no teammate needed. Android phones can also download the CS Bank app from that page for real call alerts.
            </p>
          </div>
        </section>

        <section>
          <h2 className="text-xl font-bold">Open on the phones</h2>
          <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
            <LoginQR customer="rahul" label="Rahul's bank app" base={health.data?.public_url || location.origin} />
            <LoginQR customer="sunita" label="Sunita's bank app" base={health.data?.public_url || location.origin} />
            <QR path="/call" label="Call the bank" />
            <QR path="/agent" label="Agent console" />
            <QR path="/fraud" label="Fraud desk" />
            <QR path="/metrics" label="Metrics" />
          </div>
        </section>

        <section className="grid gap-4 lg:grid-cols-3">
          <div className="card space-y-3 p-4">
            <div className="label">Scenario controls</div>
            <button className="btn-danger w-full" onClick={() => confirm('Reset requests, cases and calls? Bound passkeys are kept.') && call('/api/demo/reset', {}, 'World reset')}>
              Reset demo world
            </button>
            <button className="btn-outline w-full" onClick={() => call('/api/demo/recent-call', { customer_id: 'sunita', on: !sunitaCall, minutes_ago: 2 }, sunitaCall ? 'Cleared' : 'Sunita was on a call 2 min ago')}>
              {sunitaCall ? 'Clear' : 'Set'} “Sunita was on a call 2 min ago”
            </button>
            {sunitaLive && (
              <p className="text-xs text-muted">
                Sunita’s phone reports {sunitaLive === 'internet' ? 'an internet call (WhatsApp or similar)' : 'a phone call'} in progress (CS Bank app).
              </p>
            )}
            <button className="btn-outline w-full" onClick={() => call('/api/demo/sim-swap', { customer_id: 'rahul', on: !swapOn, hours_ago: 5 }, swapOn ? 'SIM swap cleared' : 'SIM swap on Rahul’s number 5 h ago')}>
              {swapOn ? 'Clear' : 'Simulate'} SIM swap on Rahul’s number
            </button>
            <div className="grid grid-cols-2 gap-2">
              {['rahul', 'sunita'].map((c) => (
                <button key={c} className="btn-ghost border border-line text-xs" onClick={async () => {
                  if (!confirm(`Unbind all phones (passkeys) from ${c}'s account?`)) return
                  try {
                    await api.del(`/api/app/${c}/passkeys`)
                    show(`${c}'s phones unbound`)
                  } catch (e) {
                    show((e as Error).message, 'error')
                  }
                }}>
                  Unbind {c}'s phones
                </button>
              ))}
            </div>
            <div className="text-xs text-muted">
              FRI-rated numbers:{' '}
              {Object.entries(w?.fri || {}).map(([k, v]) => (
                <span key={k} className="mr-2 font-mono">{k} ({v})</span>
              ))}
            </div>
          </div>

          <div className="card p-4">
            <div className="label">Engine</div>
            {health.data ? (
              <dl className="mt-2 space-y-1 text-sm">
                <div className="flex justify-between"><dt className="text-muted">S1</dt><dd className="font-mono">{health.data.models.s1} · {health.data.s1_version}</dd></div>
                <div className="flex justify-between"><dt className="text-muted">S2</dt><dd className="font-mono">{health.data.models.s2}</dd></div>
                <div className="flex justify-between"><dt className="text-muted">ASR</dt><dd className="font-mono">{health.data.models.asr}</dd></div>
                <div className="flex justify-between"><dt className="text-muted">p95 per window</dt><dd className="font-mono">{health.data.p95_ms ? `${health.data.p95_ms.toFixed(0)} ms` : '—'}</dd></div>
                <div className="flex justify-between"><dt className="text-muted">Live calls</dt><dd className="font-mono">{health.data.live_calls}</dd></div>
                <div className="flex justify-between"><dt className="text-muted">Passkey RP ID</dt><dd className="font-mono">{health.data.rp_id === 'auto' ? location.hostname : health.data.rp_id}</dd></div>
              </dl>
            ) : (
              <p className="text-sm text-red">Engine not reachable.</p>
            )}
            {health.data?.models.s1 === 'dummy' && <p className="mt-2 rounded bg-amber-soft p-2 text-xs">S1 is the placeholder scorer. Run ml/port_sls_checkpoint.py to load the real detector.</p>}
          </div>

          <div className="card p-4">
            <div className="label">What Countersign holds right now</div>
            {stored.data && (
              <dl className="mt-2 space-y-1 text-sm">
                <div className="flex justify-between"><dt>Voiceprints</dt><dd className="font-semibold">{stored.data.voiceprints}</dd></div>
                <div className="flex justify-between"><dt>Call transcripts</dt><dd className="font-semibold">{stored.data.transcripts_stored}</dd></div>
                <div className="flex justify-between"><dt>Calls with audio in memory</dt><dd className="font-semibold">{Object.values(stored.data.live_audio_seconds_in_memory).filter((s) => s > 0).length}</dd></div>
                <div className="flex justify-between"><dt>Audio files on disk</dt><dd className="font-semibold">{stored.data.audio_files_on_disk.length} {stored.data.audio_files_on_disk.length > 0 && '(RED clips, encrypted)'}</dd></div>
                <div className="flex justify-between"><dt>Case rows (scores, reasons)</dt><dd className="font-semibold">{stored.data.case_rows.length}</dd></div>
                <div className="flex justify-between"><dt>Audit events</dt><dd className="font-semibold">{stored.data.audit_events}</dd></div>
              </dl>
            )}
          </div>
        </section>
      </main>
      {toast}
    </div>
  )
}
